"""
Proactive job scanning system — searches job boards, deduplicates,
evaluates fit using Haiku, and formats results.

Imports memory (base module) and tools (for web search/fetch).
Lazy-imports models for Haiku fit assessment. No circular dependencies.
"""

import json
import os
import re
import time
from datetime import datetime, timedelta
from hashlib import sha256

import memory


# --- Constants ---

SCAN_LOG = os.path.join(memory.BASE_DIR, "logs", "scan.log")
SEEN_JOBS_FILE = os.path.join(
    memory.PROJECTS_DIR, memory.JOB_SEARCH_PROJECT, "seen_jobs.json"
)
SCAN_RESULTS_FILE = os.path.join(
    memory.PROJECTS_DIR, memory.JOB_SEARCH_PROJECT, "scan_results.json"
)

MAX_JOBS_PER_SCAN = 30
FETCH_DELAY_SECONDS = 2
MANUAL_SCANS_PER_DAY = 3
AUTO_SCANS_PER_DAY = 1

# Site-restricted DuckDuckGo queries for each platform
JOB_PLATFORMS = [
    {
        "name": "LinkedIn",
        "query_suffix": "site:linkedin.com/jobs",
        "max_results": 8,
    },
    {
        "name": "Indeed",
        "query_suffix": "site:indeed.com",
        "max_results": 6,
    },
    {
        "name": "Glassdoor",
        "query_suffix": "site:glassdoor.com/job-listing",
        "max_results": 4,
    },
    {
        "name": "General",
        "query_suffix": "jobs hiring",
        "max_results": 6,
    },
]

def _build_fit_prompt():
    """Build the fit assessment prompt from user_profile config."""
    profile = memory.load_config().get("user_profile", {})
    name = profile.get("name", "the user")
    title = profile.get("title", "")
    experience = profile.get("experience_summary", "")
    tools_list = profile.get("tools", [])
    credits_list = profile.get("credits", [])
    location = profile.get("location", "")
    target_roles = profile.get("target_roles", [])

    # Build profile lines
    lines = [f"You are evaluating job postings for {name}.\n", f"{name}'s profile:"]
    if title:
        lines.append(f"- {title}")
    if experience:
        lines.append(f"- {experience}")
    if credits_list:
        lines.append(f"- Credits: {', '.join(str(c) for c in credits_list)}")
    if tools_list:
        lines.append(f"- Tools: {', '.join(str(t) for t in tools_list)}")
    if location:
        lines.append(f"- Based in {location}")
    if target_roles:
        lines.append(f"- Looking for: {', '.join(str(r) for r in target_roles)}")

    lines.append("")
    lines.append(
        "Rate this job posting on a scale of 1-5 for fit:\n"
        "5 = Perfect match (core skills, ideal role)\n"
        "4 = Strong match (closely related role at relevant company)\n"
        "3 = Decent match (related role, might be worth applying)\n"
        "2 = Weak match (tangentially related, probably not worth pursuing)\n"
        "1 = No match (completely different field or skills)\n"
        "\n"
        "Return ONLY valid JSON:\n"
        '{"score": <1-5>, "reason": "<one sentence explanation>", '
        '"title": "<cleaned job title>", "company": "<company name if detectable>", '
        '"location": "<location if detectable>"}\n'
        "\n"
        "Job posting:\n"
    )
    return "\n".join(lines)


# --- Seen jobs tracking ---

def load_seen_jobs():
    """Load seen job URLs/hashes. Prunes entries older than 30 days."""
    if not os.path.exists(SEEN_JOBS_FILE):
        return {}
    try:
        with open(SEEN_JOBS_FILE, "r") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    # Prune old entries
    cutoff = (memory.local_now() - timedelta(days=30)).isoformat()
    pruned = {k: v for k, v in data.items() if isinstance(v, dict) and v.get("seen_at", "") > cutoff}
    return pruned


def save_seen_jobs(seen):
    """Save seen jobs tracking data."""
    os.makedirs(os.path.dirname(SEEN_JOBS_FILE), exist_ok=True)
    with open(SEEN_JOBS_FILE, "w") as f:
        json.dump(seen, f, indent=2)


def _job_key(url):
    """Generate a stable key for a job URL."""
    # Normalize URL: strip trailing slashes, query params for dedup
    normalized = re.sub(r'[?#].*$', '', url.rstrip('/').lower())
    return sha256(normalized.encode()).hexdigest()[:16]


def mark_job_seen(seen, url, score=None):
    """Mark a job URL as seen."""
    key = _job_key(url)
    seen[key] = {
        "url": url,
        "seen_at": memory.local_now().isoformat(),
        "score": score,
    }


def is_job_seen(seen, url):
    """Check if a job URL has been seen before."""
    return _job_key(url) in seen


# --- Scan results storage ---

def load_scan_results():
    """Load the most recent scan results."""
    if not os.path.exists(SCAN_RESULTS_FILE):
        return None
    try:
        with open(SCAN_RESULTS_FILE, "r") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


def save_scan_results(results):
    """Save scan results."""
    os.makedirs(os.path.dirname(SCAN_RESULTS_FILE), exist_ok=True)
    with open(SCAN_RESULTS_FILE, "w") as f:
        json.dump(results, f, indent=2)


# --- Rate limiting ---

def _count_scans_today(scan_type="manual"):
    """Count how many scans of the given type have run today."""
    if not os.path.exists(SCAN_LOG):
        return 0
    today_str = memory.local_now().strftime("%Y-%m-%d")
    count = 0
    try:
        with open(SCAN_LOG, "r") as f:
            for line in f:
                if today_str in line and f"type={scan_type}" in line:
                    count += 1
    except OSError:
        pass
    return count


def check_scan_rate_limit(scan_type="manual"):
    """Check if we're under the rate limit. Returns True if OK to scan."""
    count = _count_scans_today(scan_type)
    limit = MANUAL_SCANS_PER_DAY if scan_type == "manual" else AUTO_SCANS_PER_DAY
    return count < limit


def get_scan_count_today(scan_type="manual"):
    """Return how many scans of the given type have run today."""
    return _count_scans_today(scan_type)


# --- Logging ---

def log_scan(scan_type, query_count, new_count, total_assessed, cost):
    """Log a scan event to the audit log."""
    log_dir = os.path.dirname(SCAN_LOG)
    os.makedirs(log_dir, exist_ok=True)
    timestamp = memory.local_now().strftime("%Y-%m-%d %H:%M:%S")
    entry = (
        f"[{timestamp}] type={scan_type} queries={query_count} "
        f"new={new_count} assessed={total_assessed} cost=${cost:.4f}\n"
    )
    with open(SCAN_LOG, "a") as f:
        f.write(entry)


# --- Core scan engine ---

def run_scan(queries=None, progress_fn=None, scan_type="manual"):
    """Run a job scan across configured platforms.

    queries: list of search query strings, or None to use config defaults.
    progress_fn(msg): optional callback for status updates.
    scan_type: 'manual' or 'auto' (affects rate limiting).

    Returns a dict:
        {
            'ok': True/False,
            'error': None or error string,
            'high': [jobs with score >= 4],
            'medium': [jobs with score == 3],
            'low': [jobs with score <= 2],
            'total_searched': int,
            'total_new': int,
            'total_assessed': int,
            'cost': float,
            'scan_time': str (ISO format),
        }
    """
    import tools

    if not check_scan_rate_limit(scan_type):
        limit = MANUAL_SCANS_PER_DAY if scan_type == "manual" else AUTO_SCANS_PER_DAY
        count = get_scan_count_today(scan_type)
        return {
            "ok": False,
            "error": f"Scan rate limit reached ({count}/{limit} {scan_type} scans today).",
            "high": [], "medium": [], "low": [],
            "total_searched": 0, "total_new": 0, "total_assessed": 0,
            "cost": 0.0, "scan_time": memory.local_now().isoformat(),
        }

    # Load config for queries
    config = memory.load_config().get("job_scan", {})
    if queries is None:
        queries = config.get("queries", [
            "assistant editor animation",
            "video editor post production",
            "editorial animation studio",
        ])

    if not queries:
        return {
            "ok": False,
            "error": "No search queries configured. Use /scan query add <query>.",
            "high": [], "medium": [], "low": [],
            "total_searched": 0, "total_new": 0, "total_assessed": 0,
            "cost": 0.0, "scan_time": memory.local_now().isoformat(),
        }

    seen = load_seen_jobs()
    all_results = []
    total_searched = 0
    query_count = 0

    if progress_fn:
        progress_fn(f"Starting scan with {len(queries)} quer{'y' if len(queries) == 1 else 'ies'}...")

    # Search each query on each platform
    for query in queries:
        for platform in JOB_PLATFORMS:
            if total_searched >= MAX_JOBS_PER_SCAN:
                break

            full_query = f"{query} {platform['query_suffix']}"
            max_results = platform["max_results"]
            query_count += 1

            if progress_fn:
                progress_fn(f"Searching {platform['name']}: {query}...")

            try:
                import contextlib, io
                from ddgs import DDGS
                # Suppress primp "Impersonate ... does not exist" warnings
                with contextlib.redirect_stderr(io.StringIO()):
                    raw_results = DDGS().text(full_query, max_results=max_results)
            except Exception as e:
                if progress_fn:
                    progress_fn(f"Search failed ({platform['name']}): {e}")
                continue

            if not raw_results:
                continue

            for r in raw_results:
                url = r.get("href", "")
                title = r.get("title", "")
                body = r.get("body", "")

                if not url:
                    continue

                total_searched += 1

                # Skip already seen
                if is_job_seen(seen, url):
                    continue

                all_results.append({
                    "url": url,
                    "title": title,
                    "body": body,
                    "platform": platform["name"],
                })

            # Politeness delay between searches
            time.sleep(FETCH_DELAY_SECONDS)

        if total_searched >= MAX_JOBS_PER_SCAN:
            break

    if progress_fn:
        progress_fn(f"Found {len(all_results)} new listing(s). Assessing fit...")

    # Assess fit using Haiku (batch to save cost)
    total_cost = 0.0
    assessed_results = []

    if all_results:
        assessed_results, cost = _assess_fit_batch(all_results, progress_fn)
        total_cost += cost

    # Classify results
    high = []
    medium = []
    low = []

    for job in assessed_results:
        score = job.get("score", 1)
        mark_job_seen(seen, job["url"], score=score)

        if score >= 4:
            high.append(job)
        elif score == 3:
            medium.append(job)
        else:
            low.append(job)

    # Mark any unassessed results as seen too
    for job in all_results:
        if not is_job_seen(seen, job["url"]):
            mark_job_seen(seen, job["url"], score=0)

    save_seen_jobs(seen)

    # Log the scan
    log_scan(scan_type, query_count, len(all_results), len(assessed_results), total_cost)

    # Save results
    scan_data = {
        "scan_time": memory.local_now().isoformat(),
        "scan_type": scan_type,
        "queries": queries,
        "high": high,
        "medium": medium,
        "low": low,
        "total_searched": total_searched,
        "total_new": len(all_results),
        "total_assessed": len(assessed_results),
        "cost": total_cost,
    }
    save_scan_results(scan_data)

    if progress_fn:
        progress_fn(
            f"Scan complete: {len(high)} strong, {len(medium)} possible, "
            f"{len(low)} weak ({total_searched} searched, {len(all_results)} new)"
        )

    return {
        "ok": True,
        "error": None,
        "high": high,
        "medium": medium,
        "low": low,
        "total_searched": total_searched,
        "total_new": len(all_results),
        "total_assessed": len(assessed_results),
        "cost": total_cost,
        "scan_time": memory.local_now().isoformat(),
    }


def _assess_fit_batch(jobs, progress_fn=None):
    """Assess fit for a batch of jobs using Haiku.

    Returns (assessed_jobs_list, total_cost).
    Each job dict gets 'score', 'reason', 'clean_title', 'company', 'location' added.
    """
    import models

    assessed = []
    total_cost = 0.0
    fit_prompt = _build_fit_prompt()

    # Batch jobs into groups of 5 for efficiency
    batch_size = 5
    for i in range(0, len(jobs), batch_size):
        batch = jobs[i:i + batch_size]

        for job in batch:
            # Build assessment text from title + body
            text = f"Title: {job['title']}\nURL: {job['url']}\n\n{job['body'][:1500]}"

            try:
                response = models.get_client().messages.create(
                    model="claude-haiku-4-5",
                    max_tokens=200,
                    messages=[{"role": "user", "content": fit_prompt + text}],
                )
                result_text = response.content[0].text.strip()
                cost = models.track_usage(
                    response.usage.input_tokens,
                    response.usage.output_tokens,
                    "claude-haiku-4-5",
                )
                total_cost += cost

                # Parse JSON response
                try:
                    parsed = json.loads(result_text)
                except json.JSONDecodeError:
                    match = re.search(r'\{.*\}', result_text, re.DOTALL)
                    if match:
                        parsed = json.loads(match.group(0))
                    else:
                        parsed = {"score": 1, "reason": "Could not parse assessment"}

                job["score"] = parsed.get("score", 1)
                job["reason"] = parsed.get("reason", "")
                job["clean_title"] = parsed.get("title", job["title"])
                job["company"] = parsed.get("company", "")
                job["location"] = parsed.get("location", "")
                assessed.append(job)

            except Exception as e:
                # If assessment fails, still include with low score
                job["score"] = 0
                job["reason"] = f"Assessment failed: {e}"
                job["clean_title"] = job["title"]
                job["company"] = ""
                job["location"] = ""
                assessed.append(job)

        if progress_fn and i + batch_size < len(jobs):
            progress_fn(f"Assessed {min(i + batch_size, len(jobs))}/{len(jobs)}...")

    return assessed, total_cost


# --- Formatting ---

def format_scan_ansi(results):
    """Format scan results for terminal display with ANSI colors."""
    R = memory.RESET
    C = memory.CYAN
    D = memory.DIM
    RED = memory.RED
    YEL = memory.YELLOW
    BOLD = memory.BOLD
    GREEN = memory.GREEN

    lines = []

    if not results.get("ok"):
        return f"{RED}{results.get('error', 'Unknown error')}{R}"

    high = results.get("high", [])
    medium = results.get("medium", [])
    low = results.get("low", [])

    lines.append(f"\n{C}{'━' * 3} JOB SCAN RESULTS {'━' * 3}{R}")
    lines.append(f"{D}  Searched {results.get('total_searched', 0)} listings, "
                 f"{results.get('total_new', 0)} new, "
                 f"{results.get('total_assessed', 0)} assessed{R}")

    if high:
        lines.append(f"\n{GREEN}STRONG MATCHES ({len(high)}):{R}")
        for i, job in enumerate(high, 1):
            score_bar = "★" * job["score"] + "☆" * (5 - job["score"])
            lines.append(f"  {GREEN}{i}. [{score_bar}] {job['clean_title']}{R}")
            if job.get("company"):
                lines.append(f"     {BOLD}{job['company']}{R}"
                             + (f" — {job['location']}" if job.get("location") else ""))
            lines.append(f"     {D}{job['url']}{R}")
            if job.get("reason"):
                lines.append(f"     {D}{job['reason']}{R}")

    if medium:
        lines.append(f"\n{YEL}POSSIBLE MATCHES ({len(medium)}):{R}")
        for i, job in enumerate(medium, 1):
            lines.append(f"  {YEL}{i}. {job['clean_title']}{R}")
            if job.get("company"):
                lines.append(f"     {job['company']}"
                             + (f" — {job['location']}" if job.get("location") else ""))
            lines.append(f"     {D}{job['url']}{R}")
            if job.get("reason"):
                lines.append(f"     {D}{job['reason']}{R}")

    if not high and not medium:
        lines.append(f"\n{D}  No strong or possible matches found.{R}")
    elif low:
        lines.append(f"\n{D}  ({len(low)} weak/unrelated listing(s) filtered out){R}")

    lines.append(f"\n{D}  Scan cost: ${results.get('cost', 0):.4f}{R}")

    return "\n".join(lines)


def format_scan_discord(results):
    """Format scan results for Discord display."""
    lines = []

    if not results.get("ok"):
        return f"*{results.get('error', 'Unknown error')}*"

    high = results.get("high", [])
    medium = results.get("medium", [])
    low = results.get("low", [])

    lines.append(f"**━━━ JOB SCAN RESULTS ━━━**")
    lines.append(f"Searched {results.get('total_searched', 0)} listings, "
                 f"{results.get('total_new', 0)} new, "
                 f"{results.get('total_assessed', 0)} assessed")

    if high:
        lines.append(f"\n**STRONG MATCHES ({len(high)}):**")
        for i, job in enumerate(high, 1):
            score_bar = "★" * job["score"] + "☆" * (5 - job["score"])
            company_info = f" — {job['company']}" if job.get("company") else ""
            location_info = f" ({job['location']})" if job.get("location") else ""
            lines.append(f"**{i}. [{score_bar}] {job['clean_title']}**{company_info}{location_info}")
            lines.append(f"  {job['url']}")
            if job.get("reason"):
                lines.append(f"  > {job['reason']}")

    if medium:
        lines.append(f"\n**POSSIBLE MATCHES ({len(medium)}):**")
        for i, job in enumerate(medium, 1):
            company_info = f" — {job['company']}" if job.get("company") else ""
            lines.append(f"{i}. {job['clean_title']}{company_info}")
            lines.append(f"  {job['url']}")
            if job.get("reason"):
                lines.append(f"  > {job['reason']}")

    if not high and not medium:
        lines.append("\nNo strong or possible matches found.")
    elif low:
        lines.append(f"\n*({len(low)} weak/unrelated listing(s) filtered out)*")

    lines.append(f"\n*Scan cost: ${results.get('cost', 0):.4f}*")

    return "\n".join(lines)


def format_scan_notification_discord(results):
    """Format a scan notification for Discord DM (high matches only)."""
    high = results.get("high", [])
    if not high:
        return None

    lines = [f"**🔍 Job Scan Alert** — {len(high)} strong match{'es' if len(high) != 1 else ''}"]
    for job in high[:5]:  # Cap at 5 per notification
        company_info = f" at {job['company']}" if job.get("company") else ""
        lines.append(f"• **{job['clean_title']}**{company_info}")
        lines.append(f"  {job['url']}")
        if job.get("reason"):
            lines.append(f"  > {job['reason']}")

    if len(high) > 5:
        lines.append(f"*...and {len(high) - 5} more. Use `!scan results` to see all.*")

    medium_count = len(results.get("medium", []))
    if medium_count:
        lines.append(f"\n*Also found {medium_count} possible match{'es' if medium_count != 1 else ''} — `!scan results`*")

    return "\n".join(lines)


def format_scan_summary_discord(results):
    """Format a brief scan summary for Discord (used in batched/briefing context)."""
    high = len(results.get("high", []))
    medium = len(results.get("medium", []))
    total = results.get("total_searched", 0)

    if high == 0 and medium == 0:
        return f"Job scan: {total} listings checked, no matches."

    parts = []
    if high:
        parts.append(f"**{high}** strong")
    if medium:
        parts.append(f"{medium} possible")

    return f"Job scan: {', '.join(parts)} match{'es' if high + medium != 1 else ''} ({total} checked)"


# --- Status ---

def get_scan_status():
    """Get current scan configuration and status."""
    config = memory.load_config().get("job_scan", {})
    last_results = load_scan_results()

    manual_today = get_scan_count_today("manual")
    auto_today = get_scan_count_today("auto")

    last_scan_time = None
    if last_results:
        last_scan_time = last_results.get("scan_time", "never")
        try:
            dt = datetime.fromisoformat(last_scan_time)
            last_scan_time = dt.strftime("%Y-%m-%d %H:%M")
        except (ValueError, TypeError):
            pass

    return {
        "enabled": config.get("enabled", True),
        "queries": config.get("queries", []),
        "auto_time": config.get("auto_time", "07:00"),
        "skip_weekends": config.get("skip_weekends", True),
        "monday_time": config.get("monday_time", "06:00"),
        "last_scan": last_scan_time,
        "manual_today": manual_today,
        "manual_limit": MANUAL_SCANS_PER_DAY,
        "auto_today": auto_today,
        "auto_limit": AUTO_SCANS_PER_DAY,
        "seen_count": len(load_seen_jobs()),
    }
