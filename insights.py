"""
Proactive insights engine — cross-references data from multiple sources
to surface actionable connections the user would miss.

Runs periodically via the daemon (default every 6 hours). If nothing
is worth surfacing, stays silent (returns None).

Imports memory (base module). Lazy-imports models, tools, tasks,
job_scanner, service_registry inside functions to avoid circular deps.
"""

import logging
import os
from datetime import datetime, timedelta

import memory

log = logging.getLogger("insights")


# --- System prompt for insight synthesis ---

_INSIGHTS_SYSTEM_PROMPT = """You are analyzing recent activity data for a personal AI agent's user. Your job is to identify 0-3 actionable insights worth proactively surfacing.

Rules:
- Only surface insights that connect dots across multiple data sources or highlight something time-sensitive the user might miss
- If nothing is genuinely worth surfacing, return exactly: NO_INSIGHTS
- Be conversational and specific, not robotic or generic
- Each insight should suggest a concrete next action
- Do NOT repeat information the user has already seen in their daily briefing
- Keep the total response under 200 words
- Format as a single message, not a list. Natural language, like a helpful colleague pinging you."""


# --- Data gathering (each returns a dict, never raises) ---

def _gather_tasks():
    """Get open tasks from all projects."""
    import tasks as task_mod
    try:
        open_tasks = task_mod.get_all_project_tasks(filter_status="open")
        return {"ok": True, "tasks": open_tasks}
    except Exception as e:
        log.debug("Failed to gather tasks: %s", e)
        return {"ok": False, "error": str(e)}


def _gather_reminders():
    """Get pending reminders."""
    import tasks as task_mod
    try:
        pending = task_mod.get_pending_reminders()
        return {"ok": True, "reminders": pending}
    except Exception as e:
        log.debug("Failed to gather reminders: %s", e)
        return {"ok": False, "error": str(e)}


def _gather_email():
    """Get recent unread emails across all accounts."""
    import service_registry
    if not service_registry.is_available("gmail"):
        return {"ok": False, "error": "Gmail not configured"}
    import tools
    try:
        emails = tools.gmail_check_all(max_results=10)
        if emails is None:
            return {"ok": False, "error": "No Gmail services"}
        return {"ok": True, "emails": emails}
    except Exception as e:
        log.debug("Failed to gather email: %s", e)
        return {"ok": False, "error": str(e)}


def _gather_calendar():
    """Get today's and tomorrow's calendar events."""
    import service_registry
    if not service_registry.is_available("calendar"):
        return {"ok": False, "error": "Calendar not configured"}
    import tools
    try:
        today_events = tools.calendar_get_events("today")
        tomorrow_events = tools.calendar_get_events("tomorrow")
        events = []
        if isinstance(today_events, list):
            events.extend(today_events)
        if isinstance(tomorrow_events, list):
            events.extend(tomorrow_events)
        return {"ok": True, "events": events}
    except Exception as e:
        log.debug("Failed to gather calendar: %s", e)
        return {"ok": False, "error": str(e)}


def _gather_jobs():
    """Get saved jobs and recent scan results (local files only)."""
    import job_scanner
    try:
        saved_jobs = memory.load_jobs() or []
        scan_results = job_scanner.load_scan_results()
        return {
            "ok": True,
            "saved_jobs": saved_jobs,
            "scan_results": scan_results,
        }
    except Exception as e:
        log.debug("Failed to gather jobs: %s", e)
        return {"ok": False, "error": str(e)}


def _gather_profile():
    """Get the user profile from config."""
    try:
        profile = memory.get_user_profile()
        return {"ok": True, "profile": profile}
    except Exception as e:
        log.debug("Failed to gather profile: %s", e)
        return {"ok": False, "error": str(e)}


# --- Aggregation ---

def _gather_all_sources():
    """Gather all data sources. Returns (context_dict, source_count).

    source_count only counts sources with actual data (ok=True AND
    non-empty payload). Profile does NOT count toward the minimum.
    """
    context = {
        "tasks": _gather_tasks(),
        "reminders": _gather_reminders(),
        "email": _gather_email(),
        "calendar": _gather_calendar(),
        "jobs": _gather_jobs(),
        "profile": _gather_profile(),
    }

    # Count sources with actual data (profile excluded from count)
    count = 0
    for key, data in context.items():
        if key == "profile":
            continue
        if not data.get("ok"):
            continue
        # Check for non-empty payload
        if key == "tasks" and data.get("tasks"):
            count += 1
        elif key == "reminders" and data.get("reminders"):
            count += 1
        elif key == "email" and data.get("emails"):
            count += 1
        elif key == "calendar" and data.get("events"):
            count += 1
        elif key == "jobs" and (data.get("saved_jobs") or data.get("scan_results")):
            count += 1

    return context, count


# --- Formatting ---

def _format_context_for_model(context):
    """Convert gathered context into structured text for the model."""
    sections = []

    # Tasks
    task_data = context.get("tasks", {})
    if task_data.get("ok") and task_data.get("tasks"):
        lines = ["## Open Tasks"]
        for t in task_data["tasks"]:
            project = t.get("project", "")
            desc = t.get("description", "")
            due = t.get("due_date", "")
            priority = t.get("priority", "normal")
            tag = f"[{project}] " if project else ""
            due_str = f" (due: {due})" if due else ""
            pri_str = f" [{priority}]" if priority != "normal" else ""
            lines.append(f"- {tag}{desc}{due_str}{pri_str}")
        sections.append("\n".join(lines))

    # Reminders
    rem_data = context.get("reminders", {})
    if rem_data.get("ok") and rem_data.get("reminders"):
        lines = ["## Pending Reminders"]
        for r in rem_data["reminders"]:
            desc = r.get("description", "")
            remind_at = r.get("remind_at", "")
            lines.append(f"- {desc} (at: {remind_at})")
        sections.append("\n".join(lines))

    # Email
    email_data = context.get("email", {})
    if email_data.get("ok") and email_data.get("emails"):
        lines = ["## Recent Emails"]
        for e in email_data["emails"]:
            sender = e.get("sender", "")
            subject = e.get("subject", "")
            snippet = e.get("snippet", "")
            lines.append(f"- From: {sender} | Subject: {subject}")
            if snippet:
                lines.append(f"  Snippet: {snippet[:100]}")
        sections.append("\n".join(lines))

    # Calendar
    cal_data = context.get("calendar", {})
    if cal_data.get("ok") and cal_data.get("events"):
        lines = ["## Calendar Events (Today + Tomorrow)"]
        for ev in cal_data["events"]:
            title = ev.get("title", "")
            start = ev.get("start", "")
            all_day = ev.get("all_day", False)
            time_str = "ALL DAY" if all_day else start
            lines.append(f"- {time_str}: {title}")
        sections.append("\n".join(lines))

    # Jobs
    job_data = context.get("jobs", {})
    if job_data.get("ok"):
        lines = []
        saved = job_data.get("saved_jobs", [])
        if saved:
            lines.append("## Saved Jobs")
            for j in saved[:10]:  # Cap at 10 to keep context manageable
                if isinstance(j, dict):
                    title = j.get("title", "")
                    company = j.get("company", "")
                    status = j.get("status", "unsaved")
                    lines.append(f"- {title} at {company} (status: {status})")
        scan = job_data.get("scan_results")
        if scan and isinstance(scan, dict):
            high = scan.get("high", [])
            if high:
                lines.append("## Recent Scan — Strong Matches")
                for j in high[:5]:
                    title = j.get("clean_title", j.get("title", ""))
                    company = j.get("company", "")
                    lines.append(f"- {title} at {company}")
        if lines:
            sections.append("\n".join(lines))

    # Profile (for context, not counted as a source)
    prof_data = context.get("profile", {})
    if prof_data.get("ok") and prof_data.get("profile"):
        p = prof_data["profile"]
        lines = ["## User Profile"]
        if p.get("name"):
            lines.append(f"- Name: {p['name']}")
        if p.get("title"):
            lines.append(f"- Title: {p['title']}")
        if p.get("target_roles"):
            lines.append(f"- Target roles: {', '.join(p['target_roles'])}")
        if len(lines) > 1:
            sections.append("\n".join(lines))

    now = memory.local_now()
    header = f"Current date/time: {now.strftime('%A, %B %d, %Y %I:%M %p')}\n"
    return header + "\n\n".join(sections)


# --- Main entry point ---

def generate_insights():
    """Cross-reference data sources and return actionable insights.

    Returns (text, cost) where text is a formatted insight message,
    or (None, cost) if nothing worth surfacing.
    """
    context, count = _gather_all_sources()

    # Need at least 2 data sources to cross-reference
    if count < 2:
        return (None, 0)

    formatted = _format_context_for_model(context)

    import models
    try:
        model = models.get_tier("standard")
        response = models.get_client().messages.create(
            model=model,
            max_tokens=500,
            system=_INSIGHTS_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": formatted}],
        )
        cost = models.track_usage(
            response.usage.input_tokens,
            response.usage.output_tokens,
            model,
        )

        response_text = response.content[0].text.strip()
        if response_text == "NO_INSIGHTS":
            return (None, cost)

        return (f"**Insights**\n\n{response_text}", cost)
    except Exception as e:
        log.error("Insight generation failed: %s", e)
        return (None, 0)
