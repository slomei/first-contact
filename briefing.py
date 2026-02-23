"""
Daily briefing aggregator.

Gathers email, tasks, jobs, reminders, and watchlist data into a
formatted briefing. Supports ANSI (terminal) and plain text (Discord).

Imports memory (base module), tasks, tools. Lazy-imports models for
Haiku summarization. No circular dependencies.
"""

import json
import os
from datetime import datetime, timedelta

import memory
import tasks
import tools
import job_scanner


# --- Data gathering (each returns a dict, never raises) ---

def _gather_calendar():
    """Check today's calendar events. Returns dict with events list."""
    try:
        service = tools.get_calendar_service()
        if not service:
            return {"ok": False, "error": "Calendar not configured"}
        events = tools.calendar_get_events("today")
        if events is None:
            return {"ok": False, "error": "Calendar not configured"}
        if isinstance(events, str):
            return {"ok": False, "error": events}
        return {"ok": True, "events": events}
    except Exception as e:
        return {"ok": False, "error": f"Error checking calendar: {e}"}


def _gather_email():
    """Check Gmail for unread emails across all accounts. Returns dict with count and top 5."""
    try:
        services = tools.get_all_gmail_services()
        if not services:
            return {"ok": False, "error": "Gmail not configured"}
        multi = len(services) > 1
        all_emails = []
        total_unread = 0
        for label, svc in services:
            result = tools.gmail_check(max_results=5, service=svc)
            if isinstance(result, list):
                for e in result:
                    entry = {"sender": e["sender"], "subject": e["subject"]}
                    if multi:
                        entry["account"] = label
                    all_emails.append(entry)
            # Get exact unread count per account via label metadata
            try:
                label_info = svc.users().labels().get(
                    userId="me", id="INBOX"
                ).execute()
                total_unread += label_info.get("messagesUnread", 0)
            except Exception:
                total_unread += len(result) if isinstance(result, list) else 0
        return {
            "ok": True,
            "count": total_unread,
            "emails": all_emails[:5],
        }
    except Exception as e:
        return {"ok": False, "error": f"Error checking email: {e}"}


def _gather_tasks():
    """Check tasks from ALL projects. Returns overdue and due-today lists."""
    try:
        now = memory.local_now()
        today_end = now.replace(hour=23, minute=59, second=59)
        overdue = []
        today = []
        upcoming = []

        if not os.path.exists(memory.PROJECTS_DIR):
            return {"ok": True, "overdue": [], "today": [], "upcoming": []}

        for project_name in sorted(os.listdir(memory.PROJECTS_DIR)):
            project_dir = os.path.join(memory.PROJECTS_DIR, project_name)
            if not os.path.isdir(project_dir):
                continue
            tasks_path = os.path.join(project_dir, "tasks.json")
            if not os.path.exists(tasks_path):
                continue
            try:
                with open(tasks_path, "r") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError):
                continue
            task_list = data.get("tasks", []) if isinstance(data, dict) else data if isinstance(data, list) else []
            for task in task_list:
                if not isinstance(task, dict):
                    continue
                if task.get("status") != "open":
                    continue
                desc = task.get("description", "")
                tid = task.get("id", "?")

                due = task.get("due_date")
                priority = task.get("priority", "normal")
                proj_tag = f"[{project_name}]" if project_name != memory.active_project else ""
                label = f"{proj_tag} #{tid} {desc}".strip()

                if not due:
                    continue
                try:
                    due_dt = datetime.fromisoformat(due)
                except (ValueError, TypeError):
                    continue
                if due_dt.tzinfo is None:
                    due_dt = due_dt.replace(tzinfo=now.tzinfo)

                due_str = due_dt.strftime("%b %d")
                if due_dt < now:
                    overdue.append({"label": label, "due": due_str, "priority": priority})
                elif due_dt <= today_end:
                    today.append({"label": label, "due": "today", "priority": priority})
                elif due_dt <= now + timedelta(days=7):
                    upcoming.append({"label": label, "due": due_str, "priority": priority})

        return {"ok": True, "overdue": overdue, "today": today, "upcoming": upcoming}
    except Exception as e:
        return {"ok": False, "error": f"Error checking tasks: {e}"}


def _gather_jobs():
    """Check job pipeline status."""
    try:
        jobs = memory.load_jobs()
        if not jobs:
            return {"ok": True, "total": 0, "unapplied": 0, "last_applied": None}

        # Filter out old-format entries that aren't dicts
        jobs = [j for j in jobs if isinstance(j, dict)]
        unapplied = [j for j in jobs if not j.get("status")]
        applied = [j for j in jobs if j.get("status") == "applied"]
        interviewing = [j for j in jobs if j.get("status") == "interviewing"]

        # Find most recent applied job
        last_applied = None
        if applied:
            # Sort by saved_at descending, pick the latest
            applied_sorted = sorted(applied, key=lambda j: j.get("saved_at", ""), reverse=True)
            last_applied = {
                "title": applied_sorted[0]["title"],
                "date": applied_sorted[0].get("saved_at", "unknown"),
            }

        return {
            "ok": True,
            "total": len(jobs),
            "unapplied": len(unapplied),
            "applied": len(applied),
            "interviewing": len(interviewing),
            "last_applied": last_applied,
        }
    except Exception as e:
        return {"ok": False, "error": f"Error checking jobs: {e}"}


def _gather_reminders():
    """Check reminders due in the next 24 hours."""
    try:
        now = memory.local_now()
        cutoff = now + timedelta(hours=24)
        pending = tasks.get_pending_reminders()
        upcoming = []
        for r in pending:
            try:
                remind_at = datetime.fromisoformat(r["remind_at"])
            except (ValueError, TypeError):
                continue
            if remind_at.tzinfo is None:
                remind_at = remind_at.replace(tzinfo=now.tzinfo)
            if remind_at <= cutoff:
                time_str = remind_at.strftime("%I:%M%p").lstrip("0").lower()
                if remind_at.date() == now.date():
                    time_label = f"today at {time_str}"
                else:
                    time_label = remind_at.strftime("%b %d") + f" at {time_str}"
                upcoming.append({"description": r["description"], "time": time_label})
        return {"ok": True, "reminders": upcoming}
    except Exception as e:
        return {"ok": False, "error": f"Error checking reminders: {e}"}


def _gather_watchlist():
    """Check watchlist topics and run quick digest via Haiku."""
    try:
        # Collect watchlist topics from ALL projects
        all_topics = []
        if os.path.exists(memory.PROJECTS_DIR):
            for project_name in sorted(os.listdir(memory.PROJECTS_DIR)):
                project_dir = os.path.join(memory.PROJECTS_DIR, project_name)
                if not os.path.isdir(project_dir):
                    continue
                wl_path = os.path.join(project_dir, "watchlist.json")
                if os.path.exists(wl_path):
                    try:
                        with open(wl_path, "r") as f:
                            topics = json.load(f)
                        if isinstance(topics, list):
                            all_topics.extend(topics)
                    except (json.JSONDecodeError, OSError):
                        pass

        if not all_topics:
            return {"ok": True, "has_topics": False, "summary": None, "cost": 0}

        # Deduplicate
        all_topics = list(dict.fromkeys(all_topics))

        # Search each topic (max 2 results each to keep it fast)
        search_results = []
        for topic in all_topics:
            try:
                results = tools.web_search(topic, max_results=2)
                if results:
                    search_results.append(f"## {topic}\n{results}")
                else:
                    search_results.append(f"## {topic}\nNo recent results.")
            except Exception:
                search_results.append(f"## {topic}\nSearch failed.")

        combined = "\n\n".join(search_results)

        # Summarize with Haiku — stable instruction as cached system prompt
        import models
        try:
            response = models.get_client().messages.create(
                model="claude-haiku-4-5",
                max_tokens=500,
                system=[{
                    "type": "text",
                    "text": (
                        "Summarize these web search results into 2-4 bullet points. "
                        "Focus on what's new or notable. Be very concise — one line per bullet."
                    ),
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=[{"role": "user", "content": combined}],
            )
            summary = response.content[0].text
            cost = models.track_usage(
                response.usage.input_tokens,
                response.usage.output_tokens,
                "claude-haiku-4-5",
                cache_creation_input_tokens=getattr(response.usage, 'cache_creation_input_tokens', 0) or 0,
                cache_read_input_tokens=getattr(response.usage, 'cache_read_input_tokens', 0) or 0,
            )
        except Exception:
            summary = "Could not summarize watchlist results."
            cost = 0

        return {"ok": True, "has_topics": True, "summary": summary, "cost": cost}
    except Exception as e:
        return {"ok": False, "error": f"Error checking watchlist: {e}"}


def _gather_scan():
    """Check most recent job scan results for the briefing."""
    try:
        last = job_scanner.load_scan_results()
        if not last:
            return {"ok": True, "has_results": False}

        # Only show if scan was within last 24 hours
        scan_time = last.get("scan_time", "")
        try:
            scan_dt = datetime.fromisoformat(scan_time)
            now_naive = memory.local_now().replace(tzinfo=None)
            if scan_dt.tzinfo:
                scan_dt = scan_dt.replace(tzinfo=None)
            if (now_naive - scan_dt) > timedelta(hours=24):
                return {"ok": True, "has_results": False}
        except (ValueError, TypeError):
            pass

        return {
            "ok": True,
            "has_results": True,
            "high": last.get("high", []),
            "medium": last.get("medium", []),
            "total_searched": last.get("total_searched", 0),
            "total_new": last.get("total_new", 0),
            "scan_time": scan_time,
        }
    except Exception as e:
        return {"ok": False, "error": f"Error checking scan results: {e}"}


# --- Formatting ---

def _format_sender(sender):
    """Extract a clean display name from an email sender string."""
    # "John Smith <john@example.com>" -> "John Smith"
    if "<" in sender:
        return sender.split("<")[0].strip().strip('"')
    return sender


def format_briefing_ansi(email_data, tasks_data, jobs_data, reminders_data, watchlist_data, cost, calendar_data=None, scan_data=None):
    """Format the briefing for terminal output with ANSI colors."""
    R = memory.RESET
    C = memory.CYAN
    D = memory.DIM
    RED = memory.RED
    YEL = memory.YELLOW
    BOLD = memory.BOLD
    GREEN = memory.GREEN

    now = memory.local_now()
    date_str = now.strftime("%a %b %d")
    lines = [f"\n{C}{'━' * 3} DAILY BRIEFING — {date_str} {'━' * 3}{R}"]

    # EMAIL
    lines.append(f"\n{C}📧 EMAIL{R}")
    if not email_data["ok"]:
        lines.append(f"  {D}{email_data['error']}{R}")
    elif email_data["count"] == 0:
        lines.append(f"  {D}No unread emails.{R}")
    else:
        lines.append(f"  {email_data['count']} unread")
        for e in email_data["emails"]:
            sender = _format_sender(e["sender"])
            acct_tag = f"{D}[{e['account']}]{R} " if e.get("account") else ""
            lines.append(f"  {BOLD}•{R} {acct_tag}{BOLD}{sender}{R} — {e['subject']}")

    # CALENDAR
    if calendar_data is not None:
        lines.append(f"\n{C}📅 CALENDAR{R}")
        if not calendar_data["ok"]:
            lines.append(f"  {D}{calendar_data['error']}{R}")
        elif not calendar_data["events"]:
            lines.append(f"  {D}No events today.{R}")
        else:
            for ev in calendar_data["events"]:
                if ev["all_day"]:
                    lines.append(f"  {C}ALL DAY{R} — {ev['title']}")
                else:
                    lines.append(f"  {C}{ev['start']}{R} — {ev['title']}")

    # TASKS
    lines.append(f"\n{C}✅ TASKS{R}")
    if not tasks_data["ok"]:
        lines.append(f"  {D}{tasks_data['error']}{R}")
    elif not tasks_data["overdue"] and not tasks_data["today"] and not tasks_data["upcoming"]:
        lines.append(f"  {D}Nothing due today or this week.{R}")
    else:
        for t in tasks_data["overdue"]:
            lines.append(f"  {RED}⚠ OVERDUE: {t['label']} (due: {t['due']}){R}")
        for t in tasks_data["today"]:
            lines.append(f"  {YEL}• {t['label']} (due: today){R}")
        for t in tasks_data["upcoming"]:
            lines.append(f"  {D}• {t['label']} (due: {t['due']}){R}")

    # JOBS
    lines.append(f"\n{C}💼 JOBS{R}")
    if not jobs_data["ok"]:
        lines.append(f"  {D}{jobs_data['error']}{R}")
    elif jobs_data["total"] == 0:
        lines.append(f"  {D}No saved jobs.{R}")
    else:
        parts = []
        if jobs_data["unapplied"]:
            parts.append(f"{jobs_data['unapplied']} saved job{'s' if jobs_data['unapplied'] != 1 else ''} not yet applied")
        if jobs_data.get("interviewing"):
            parts.append(f"{jobs_data['interviewing']} interviewing")
        if jobs_data.get("applied"):
            parts.append(f"{jobs_data['applied']} applied")
        if parts:
            lines.append(f"  • {', '.join(parts)}")
        if jobs_data.get("last_applied"):
            la = jobs_data["last_applied"]
            lines.append(f"  {D}Last application: {la['title']} ({la['date']}){R}")
        if not parts and not jobs_data.get("last_applied"):
            lines.append(f"  {D}{jobs_data['total']} saved job(s), all tracked.{R}")

    # JOB SCAN
    if scan_data is not None:
        lines.append(f"\n{C}🔍 JOB SCAN{R}")
        if not scan_data["ok"]:
            lines.append(f"  {D}{scan_data['error']}{R}")
        elif not scan_data["has_results"]:
            lines.append(f"  {D}No recent scan results.{R}")
        else:
            high = scan_data.get("high", [])
            medium = scan_data.get("medium", [])
            if high:
                lines.append(f"  {GREEN}{len(high)} strong match{'es' if len(high) != 1 else ''}:{R}")
                for job in high[:3]:
                    company = f" at {job['company']}" if job.get("company") else ""
                    lines.append(f"  {GREEN}★{R} {BOLD}{job['clean_title']}{R}{company}")
                if len(high) > 3:
                    lines.append(f"  {D}...and {len(high) - 3} more{R}")
            if medium:
                lines.append(f"  {D}{len(medium)} possible match{'es' if len(medium) != 1 else ''}{R}")
            if not high and not medium:
                total = scan_data.get("total_searched", 0)
                lines.append(f"  {D}{total} listings checked, no matches.{R}")

    # REMINDERS
    lines.append(f"\n{C}⏰ REMINDERS{R}")
    if not reminders_data["ok"]:
        lines.append(f"  {D}{reminders_data['error']}{R}")
    elif not reminders_data["reminders"]:
        lines.append(f"  {D}Nothing in the next 24 hours.{R}")
    else:
        for r in reminders_data["reminders"]:
            lines.append(f"  • {r['description']} ({r['time']})")

    # WATCHLIST
    lines.append(f"\n{C}📡 WATCHLIST{R}")
    if not watchlist_data["ok"]:
        lines.append(f"  {D}{watchlist_data['error']}{R}")
    elif not watchlist_data["has_topics"]:
        lines.append(f"  {D}No watchlist configured.{R}")
    elif watchlist_data["summary"]:
        for line in watchlist_data["summary"].strip().splitlines():
            # Indent each bullet
            cleaned = line.strip().lstrip("-•* ").strip()
            if cleaned:
                lines.append(f"  • {cleaned}")
    else:
        lines.append(f"  {D}No new results.{R}")

    lines.append(f"\n{C}{'━' * 34}{R}")
    lines.append(f"{D}  Briefing cost: ${cost:.4f} | session: ${_get_session_cost():.4f}{R}\n")

    return "\n".join(lines)


def format_briefing_discord(email_data, tasks_data, jobs_data, reminders_data, watchlist_data, cost, calendar_data=None, scan_data=None):
    """Format the briefing for Discord (markdown, no ANSI)."""
    now = memory.local_now()
    date_str = now.strftime("%a %b %d")
    lines = [f"**━━━ DAILY BRIEFING — {date_str} ━━━**"]

    # EMAIL
    lines.append(f"\n**📧 EMAIL**")
    if not email_data["ok"]:
        lines.append(f"  {email_data['error']}")
    elif email_data["count"] == 0:
        lines.append("  No unread emails.")
    else:
        lines.append(f"  {email_data['count']} unread")
        for e in email_data["emails"]:
            sender = _format_sender(e["sender"])
            acct_tag = f"[{e['account']}] " if e.get("account") else ""
            lines.append(f"  • {acct_tag}**{sender}** — {e['subject']}")

    # CALENDAR
    if calendar_data is not None:
        lines.append(f"\n**📅 CALENDAR**")
        if not calendar_data["ok"]:
            lines.append(f"  {calendar_data['error']}")
        elif not calendar_data["events"]:
            lines.append("  No events today.")
        else:
            for ev in calendar_data["events"]:
                if ev["all_day"]:
                    lines.append(f"  • `ALL DAY` — {ev['title']}")
                else:
                    lines.append(f"  • `{ev['start']}` — {ev['title']}")

    # TASKS
    lines.append(f"\n**✅ TASKS**")
    if not tasks_data["ok"]:
        lines.append(f"  {tasks_data['error']}")
    elif not tasks_data["overdue"] and not tasks_data["today"] and not tasks_data["upcoming"]:
        lines.append("  Nothing due today or this week.")
    else:
        for t in tasks_data["overdue"]:
            lines.append(f"  ⚠ **OVERDUE:** {t['label']} (due: {t['due']})")
        for t in tasks_data["today"]:
            lines.append(f"  • {t['label']} (due: today)")
        for t in tasks_data["upcoming"]:
            lines.append(f"  • {t['label']} (due: {t['due']})")

    # JOBS
    lines.append(f"\n**💼 JOBS**")
    if not jobs_data["ok"]:
        lines.append(f"  {jobs_data['error']}")
    elif jobs_data["total"] == 0:
        lines.append("  No saved jobs.")
    else:
        parts = []
        if jobs_data["unapplied"]:
            parts.append(f"{jobs_data['unapplied']} saved job{'s' if jobs_data['unapplied'] != 1 else ''} not yet applied")
        if jobs_data.get("interviewing"):
            parts.append(f"{jobs_data['interviewing']} interviewing")
        if jobs_data.get("applied"):
            parts.append(f"{jobs_data['applied']} applied")
        if parts:
            lines.append(f"  • {', '.join(parts)}")
        if jobs_data.get("last_applied"):
            la = jobs_data["last_applied"]
            lines.append(f"  Last application: {la['title']} ({la['date']})")
        if not parts and not jobs_data.get("last_applied"):
            lines.append(f"  {jobs_data['total']} saved job(s), all tracked.")

    # JOB SCAN
    if scan_data is not None:
        lines.append(f"\n**🔍 JOB SCAN**")
        if not scan_data["ok"]:
            lines.append(f"  {scan_data['error']}")
        elif not scan_data["has_results"]:
            lines.append("  No recent scan results.")
        else:
            high = scan_data.get("high", [])
            medium = scan_data.get("medium", [])
            if high:
                lines.append(f"  **{len(high)} strong match{'es' if len(high) != 1 else ''}:**")
                for job in high[:3]:
                    company = f" at {job['company']}" if job.get("company") else ""
                    lines.append(f"  ★ **{job['clean_title']}**{company}")
                if len(high) > 3:
                    lines.append(f"  *...and {len(high) - 3} more*")
            if medium:
                lines.append(f"  {len(medium)} possible match{'es' if len(medium) != 1 else ''}")
            if not high and not medium:
                total = scan_data.get("total_searched", 0)
                lines.append(f"  {total} listings checked, no matches.")

    # REMINDERS
    lines.append(f"\n**⏰ REMINDERS**")
    if not reminders_data["ok"]:
        lines.append(f"  {reminders_data['error']}")
    elif not reminders_data["reminders"]:
        lines.append("  Nothing in the next 24 hours.")
    else:
        for r in reminders_data["reminders"]:
            lines.append(f"  • {r['description']} ({r['time']})")

    # WATCHLIST
    lines.append(f"\n**📡 WATCHLIST**")
    if not watchlist_data["ok"]:
        lines.append(f"  {watchlist_data['error']}")
    elif not watchlist_data["has_topics"]:
        lines.append("  No watchlist configured.")
    elif watchlist_data["summary"]:
        for line in watchlist_data["summary"].strip().splitlines():
            cleaned = line.strip().lstrip("-•* ").strip()
            if cleaned:
                lines.append(f"  • {cleaned}")
    else:
        lines.append("  No new results.")

    lines.append(f"\n**{'━' * 34}**")
    lines.append(f"*Briefing cost: ${cost:.4f}*")

    return "\n".join(lines)


def _get_session_cost():
    """Get session cost without importing models at module level."""
    try:
        import models
        return models.session_cost
    except Exception:
        return 0.0


# --- Main entry points ---

def generate_briefing(progress_fn=None):
    """Gather all data and return (email, calendar, tasks, jobs, reminders, watchlist, scan, total_cost).

    progress_fn(msg): optional callback for status updates.
    """
    total_cost = 0.0

    if progress_fn:
        progress_fn("Checking email...")
    email_data = _gather_email()

    if progress_fn:
        progress_fn("Checking calendar...")
    calendar_data = _gather_calendar()

    if progress_fn:
        progress_fn("Checking tasks...")
    tasks_data = _gather_tasks()

    if progress_fn:
        progress_fn("Checking job pipeline...")
    jobs_data = _gather_jobs()

    if progress_fn:
        progress_fn("Checking job scan results...")
    scan_data = _gather_scan()

    if progress_fn:
        progress_fn("Checking reminders...")
    reminders_data = _gather_reminders()

    if progress_fn:
        progress_fn("Checking watchlist...")
    watchlist_data = _gather_watchlist()
    if watchlist_data.get("cost"):
        total_cost += watchlist_data["cost"]

    return email_data, calendar_data, tasks_data, jobs_data, reminders_data, watchlist_data, scan_data, total_cost


def run_briefing_terminal(progress_fn=None):
    """Run the full briefing and return ANSI-formatted text."""
    data = generate_briefing(progress_fn=progress_fn)
    email_data, calendar_data, tasks_data, jobs_data, reminders_data, watchlist_data, scan_data, cost = data
    return format_briefing_ansi(email_data, tasks_data, jobs_data, reminders_data, watchlist_data, cost, calendar_data=calendar_data, scan_data=scan_data)


def run_briefing_discord(progress_fn=None):
    """Run the full briefing and return Discord-formatted text."""
    data = generate_briefing(progress_fn=progress_fn)
    email_data, calendar_data, tasks_data, jobs_data, reminders_data, watchlist_data, scan_data, cost = data
    return format_briefing_discord(email_data, tasks_data, jobs_data, reminders_data, watchlist_data, cost, calendar_data=calendar_data, scan_data=scan_data)
