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


# --- Data gathering (each returns a dict, never raises) ---

def _gather_email():
    """Check Gmail for unread emails. Returns dict with count and top 5."""
    try:
        service = tools.get_gmail_service()
        if not service:
            return {"ok": False, "error": "Gmail not configured"}
        result = tools.gmail_check(max_results=5)
        if result is None:
            return {"ok": False, "error": "Gmail not configured"}
        if isinstance(result, str):
            return {"ok": False, "error": result}
        # Get total unread count (the list may be capped at 5)
        try:
            count_result = service.users().messages().list(
                userId="me", q="is:unread", labelIds=["INBOX"], maxResults=1
            ).execute()
            total_unread = count_result.get("resultSizeEstimate", len(result))
        except Exception:
            total_unread = len(result)
        return {
            "ok": True,
            "count": total_unread,
            "emails": [{"sender": e["sender"], "subject": e["subject"]} for e in result],
        }
    except Exception as e:
        return {"ok": False, "error": f"Error checking email: {e}"}


def _gather_tasks():
    """Check tasks from ALL projects. Returns overdue and due-today lists."""
    try:
        now = datetime.now()
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
            for task in data.get("tasks", []):
                if task.get("status") != "open":
                    continue
                desc = task["description"]
                tid = task["id"]
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
        now = datetime.now()
        cutoff = now + timedelta(hours=24)
        pending = tasks.get_pending_reminders()
        upcoming = []
        for r in pending:
            try:
                remind_at = datetime.fromisoformat(r["remind_at"])
            except (ValueError, TypeError):
                continue
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

        # Summarize with Haiku
        import models
        try:
            response = models.client.messages.create(
                model="claude-haiku-4-5",
                max_tokens=500,
                messages=[{"role": "user", "content":
                    "Summarize these web search results into 2-4 bullet points. "
                    "Focus on what's new or notable. Be very concise — one line per bullet.\n\n"
                    + combined}],
            )
            summary = response.content[0].text
            cost = models.track_usage(
                response.usage.input_tokens,
                response.usage.output_tokens,
                "claude-haiku-4-5",
            )
        except Exception:
            summary = "Could not summarize watchlist results."
            cost = 0

        return {"ok": True, "has_topics": True, "summary": summary, "cost": cost}
    except Exception as e:
        return {"ok": False, "error": f"Error checking watchlist: {e}"}


# --- Formatting ---

def _format_sender(sender):
    """Extract a clean display name from an email sender string."""
    # "John Smith <john@example.com>" -> "John Smith"
    if "<" in sender:
        return sender.split("<")[0].strip().strip('"')
    return sender


def format_briefing_ansi(email_data, tasks_data, jobs_data, reminders_data, watchlist_data, cost):
    """Format the briefing for terminal output with ANSI colors."""
    R = memory.RESET
    C = memory.CYAN
    D = memory.DIM
    RED = memory.RED
    YEL = memory.YELLOW
    BOLD = memory.BOLD

    now = datetime.now()
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
            lines.append(f"  {BOLD}•{R} {BOLD}{sender}{R} — {e['subject']}")

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


def format_briefing_discord(email_data, tasks_data, jobs_data, reminders_data, watchlist_data, cost):
    """Format the briefing for Discord (markdown, no ANSI)."""
    now = datetime.now()
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
            lines.append(f"  • **{sender}** — {e['subject']}")

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
    """Gather all data and return (email, tasks, jobs, reminders, watchlist, total_cost).

    progress_fn(msg): optional callback for status updates.
    """
    total_cost = 0.0

    if progress_fn:
        progress_fn("Checking email...")
    email_data = _gather_email()

    if progress_fn:
        progress_fn("Checking tasks...")
    tasks_data = _gather_tasks()

    if progress_fn:
        progress_fn("Checking job pipeline...")
    jobs_data = _gather_jobs()

    if progress_fn:
        progress_fn("Checking reminders...")
    reminders_data = _gather_reminders()

    if progress_fn:
        progress_fn("Checking watchlist...")
    watchlist_data = _gather_watchlist()
    if watchlist_data.get("cost"):
        total_cost += watchlist_data["cost"]

    return email_data, tasks_data, jobs_data, reminders_data, watchlist_data, total_cost


def run_briefing_terminal(progress_fn=None):
    """Run the full briefing and return ANSI-formatted text."""
    data = generate_briefing(progress_fn=progress_fn)
    email_data, tasks_data, jobs_data, reminders_data, watchlist_data, cost = data
    return format_briefing_ansi(email_data, tasks_data, jobs_data, reminders_data, watchlist_data, cost)


def run_briefing_discord(progress_fn=None):
    """Run the full briefing and return Discord-formatted text."""
    data = generate_briefing(progress_fn=progress_fn)
    email_data, tasks_data, jobs_data, reminders_data, watchlist_data, cost = data
    return format_briefing_discord(email_data, tasks_data, jobs_data, reminders_data, watchlist_data, cost)
