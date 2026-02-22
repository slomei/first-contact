"""
Task and reminder management.

Imports memory (base module). No circular dependencies.
"""

import json
import os
import re
from datetime import datetime, timedelta

try:
    from dateutil import parser as dateutil_parser
except ImportError:
    dateutil_parser = None

import memory


# --- Date parsing ---

_WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
    "mon": 0, "tue": 1, "tues": 1, "wed": 2, "thu": 3, "thur": 3,
    "thurs": 3, "fri": 4, "sat": 5, "sun": 6,
}

_TIME_OF_DAY = {
    "morning": 9, "afternoon": 14, "evening": 18, "night": 20,
}


def _next_weekday(weekday_num):
    """Return the next occurrence of a weekday (0=Monday) at 9am."""
    now = datetime.now()
    days_ahead = weekday_num - now.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    target = now + timedelta(days=days_ahead)
    return target.replace(hour=9, minute=0, second=0, microsecond=0)


def _apply_time_of_day(dt, label):
    """Set the time on a datetime from a time-of-day label."""
    hour = _TIME_OF_DAY.get(label.lower(), 9)
    return dt.replace(hour=hour, minute=0, second=0, microsecond=0)


def parse_natural_date(text):
    """Parse a natural language date/time string into a datetime, or None."""
    if not text:
        return None
    text = text.strip().lower()

    now = datetime.now()

    # "tomorrow" / "tomorrow morning" etc.
    if text == "tomorrow":
        return (now + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
    if text.startswith("tomorrow "):
        rest = text[9:].strip()
        if rest in _TIME_OF_DAY:
            return _apply_time_of_day(now + timedelta(days=1), rest)

    # "tonight"
    if text == "tonight":
        return now.replace(hour=20, minute=0, second=0, microsecond=0)

    # "end of day"
    if text in ("end of day", "eod"):
        return now.replace(hour=17, minute=0, second=0, microsecond=0)

    # "this weekend"
    if text == "this weekend":
        days_to_sat = 5 - now.weekday()
        if days_to_sat <= 0:
            days_to_sat += 7
        return (now + timedelta(days=days_to_sat)).replace(hour=10, minute=0, second=0, microsecond=0)

    # "next week"
    if text == "next week":
        days_to_mon = 0 - now.weekday()
        if days_to_mon <= 0:
            days_to_mon += 7
        return (now + timedelta(days=days_to_mon)).replace(hour=9, minute=0, second=0, microsecond=0)

    # "in N days/hours/minutes/weeks"
    m = re.match(r"in\s+(\d+)\s+(day|days|hour|hours|minute|minutes|min|mins|week|weeks)", text)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        if unit.startswith("day"):
            return now + timedelta(days=n)
        elif unit.startswith("hour"):
            return now + timedelta(hours=n)
        elif unit.startswith("min"):
            return now + timedelta(minutes=n)
        elif unit.startswith("week"):
            return now + timedelta(weeks=n)

    # Weekday names: "thursday", "thursday morning", "next thursday"
    for name, num in _WEEKDAYS.items():
        if text == name or text == f"next {name}":
            return _next_weekday(num)
        for tod_label in _TIME_OF_DAY:
            if text == f"{name} {tod_label}" or text == f"next {name} {tod_label}":
                return _apply_time_of_day(_next_weekday(num), tod_label)

    # Fallback: dateutil fuzzy parsing
    if dateutil_parser is None:
        return None
    try:
        parsed = dateutil_parser.parse(text, fuzzy=True)
        # If the parsed date is in the past and has no explicit year, bump to next year
        if parsed < now and str(now.year) not in text:
            parsed = parsed.replace(year=parsed.year + 1)
        return parsed
    except (ValueError, OverflowError):
        pass

    return None


# --- Task I/O ---

def _extract_tasks_list(data):
    """Extract a list of task dicts from tasks.json data (handles old bare-list format)."""
    if isinstance(data, dict):
        tasks = data.get("tasks", [])
    elif isinstance(data, list):
        tasks = data
    else:
        return []
    return [t for t in tasks if isinstance(t, dict)]


def load_tasks():
    """Load tasks from the active project's tasks.json."""
    path = memory.get_tasks_file()
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return {"next_id": 1, "tasks": []}
        if not isinstance(data, dict):
            data = {"next_id": 1, "tasks": []}
        data["tasks"] = _extract_tasks_list(data)
        return data
    return {"next_id": 1, "tasks": []}


def save_tasks(data):
    """Save tasks to the active project's tasks.json."""
    path = memory.get_tasks_file()
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


# --- Task CRUD ---

def add_task(description, due_date=None, priority="normal"):
    """Add a task and return the task dict."""
    data = load_tasks()
    task = {
        "id": data["next_id"],
        "description": description,
        "created_at": datetime.now().isoformat(),
        "due_date": due_date.isoformat() if isinstance(due_date, datetime) else due_date,
        "status": "open",
        "priority": priority,
        "notes": None,
    }
    data["next_id"] += 1
    data["tasks"].append(task)
    save_tasks(data)
    return task


def complete_task(task_id):
    """Mark a task as done. Returns the task or None."""
    data = load_tasks()
    for task in data["tasks"]:
        if task["id"] == task_id:
            task["status"] = "done"
            save_tasks(data)
            return task
    return None


def remove_task(task_id):
    """Remove a task entirely. Returns the removed task or None."""
    data = load_tasks()
    for i, task in enumerate(data["tasks"]):
        if task["id"] == task_id:
            removed = data["tasks"].pop(i)
            save_tasks(data)
            return removed
    return None


def edit_task(task_id, new_description):
    """Edit a task's description. Returns the task or None."""
    data = load_tasks()
    for task in data["tasks"]:
        if task["id"] == task_id:
            task["description"] = new_description
            save_tasks(data)
            return task
    return None


def add_note(task_id, note_text):
    """Add or append a note to a task. Returns the task or None."""
    data = load_tasks()
    for task in data["tasks"]:
        if task["id"] == task_id:
            if task["notes"]:
                task["notes"] += f"\n{note_text}"
            else:
                task["notes"] = note_text
            save_tasks(data)
            return task
    return None


def _sort_group(task):
    """Return a sort group key for an open task based on due date urgency."""
    if not task.get("due_date"):
        return "no_deadline"
    try:
        due = datetime.fromisoformat(task["due_date"])
    except (ValueError, TypeError):
        return "no_deadline"
    now = datetime.now()
    today_end = now.replace(hour=23, minute=59, second=59)
    week_end = now + timedelta(days=(6 - now.weekday()))
    week_end = week_end.replace(hour=23, minute=59, second=59)

    if due < now:
        return "overdue"
    elif due <= today_end:
        return "today"
    elif due <= week_end:
        return "this_week"
    else:
        return "upcoming"


def get_open_tasks():
    """Return open tasks sorted by urgency group, then due date."""
    data = load_tasks()
    open_tasks = [t for t in data["tasks"] if t["status"] == "open"]
    group_order = {"overdue": 0, "today": 1, "this_week": 2, "upcoming": 3, "no_deadline": 4}
    for t in open_tasks:
        t["_sort_group"] = _sort_group(t)
    open_tasks.sort(key=lambda t: (
        group_order.get(t["_sort_group"], 5),
        t.get("due_date") or "9999",
    ))
    return open_tasks


def get_done_tasks():
    """Return completed tasks."""
    data = load_tasks()
    return [t for t in data["tasks"] if t["status"] == "done"]


def get_all_tasks():
    """Return all tasks (open first, then done)."""
    data = load_tasks()
    open_tasks = [t for t in data["tasks"] if t["status"] == "open"]
    done_tasks = [t for t in data["tasks"] if t["status"] == "done"]
    for t in open_tasks:
        t["_sort_group"] = _sort_group(t)
    group_order = {"overdue": 0, "today": 1, "this_week": 2, "upcoming": 3, "no_deadline": 4}
    open_tasks.sort(key=lambda t: (
        group_order.get(t["_sort_group"], 5),
        t.get("due_date") or "9999",
    ))
    return open_tasks + done_tasks


# --- Reminder I/O ---

def load_reminders():
    """Load reminders from the global reminders.json."""
    default = {"next_id": 1, "last_daily_notify": None, "reminders": []}
    path = memory.get_reminders_file()
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return default
        if not isinstance(data, dict):
            return default
        if not isinstance(data.get("reminders"), list):
            data["reminders"] = []
        return data
    return default


def save_reminders(data):
    """Save reminders to the global reminders.json."""
    path = memory.get_reminders_file()
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


# --- Reminder CRUD ---

def add_reminder(description, remind_at_str, from_task_id=None):
    """Add a reminder. Returns the reminder dict, or None if date parsing fails."""
    remind_at = parse_natural_date(remind_at_str)
    if not remind_at:
        return None
    data = load_reminders()
    reminder = {
        "id": data["next_id"],
        "description": description,
        "remind_at": remind_at.isoformat(),
        "triggered": False,
        "created_from_task_id": from_task_id,
        "project": memory.active_project,
    }
    data["next_id"] += 1
    data["reminders"].append(reminder)
    save_reminders(data)
    return reminder


def cancel_reminder(reminder_id):
    """Cancel (remove) a reminder. Returns the reminder or None."""
    data = load_reminders()
    for i, r in enumerate(data["reminders"]):
        if r["id"] == reminder_id:
            removed = data["reminders"].pop(i)
            save_reminders(data)
            return removed
    return None


def get_pending_reminders():
    """Return untriggered reminders sorted by time."""
    data = load_reminders()
    pending = [r for r in data["reminders"] if not r["triggered"]]
    pending.sort(key=lambda r: r.get("remind_at", ""))
    return pending


def check_due_reminders():
    """Check for reminders that are now due. Marks them triggered and saves.

    Returns a list of newly-triggered reminders.
    """
    data = load_reminders()
    now = datetime.now()
    triggered = []
    for r in data["reminders"]:
        if r["triggered"]:
            continue
        try:
            remind_at = datetime.fromisoformat(r["remind_at"])
        except (ValueError, TypeError):
            continue
        if remind_at <= now:
            r["triggered"] = True
            triggered.append(r)
    if triggered:
        save_reminders(data)
    return triggered


def get_daily_summary():
    """Scan all projects' tasks.json files and build a daily summary.

    Returns (summary_text, should_send). should_send is False if already sent today.
    """
    data = load_reminders()
    today_str = datetime.now().strftime("%Y-%m-%d")
    if data.get("last_daily_notify") == today_str:
        return "", False

    now = datetime.now()
    today_end = now.replace(hour=23, minute=59, second=59)
    all_overdue = []
    all_today = []
    total_open = 0

    # Scan every project folder for tasks.json
    if os.path.exists(memory.PROJECTS_DIR):
        for project_name in sorted(os.listdir(memory.PROJECTS_DIR)):
            project_dir = os.path.join(memory.PROJECTS_DIR, project_name)
            if not os.path.isdir(project_dir):
                continue
            tasks_path = os.path.join(project_dir, "tasks.json")
            if not os.path.exists(tasks_path):
                continue
            try:
                with open(tasks_path, "r") as f:
                    proj_data = json.load(f)
            except (json.JSONDecodeError, OSError):
                continue
            for task in _extract_tasks_list(proj_data):
                if task.get("status") != "open":
                    continue
                total_open += 1
                if not task.get("due_date"):
                    continue
                try:
                    due = datetime.fromisoformat(task["due_date"])
                except (ValueError, TypeError):
                    continue
                label = f"[{project_name}] #{task['id']} {task['description']}"
                if due < now:
                    all_overdue.append(label)
                elif due <= today_end:
                    all_today.append(label)

    if not total_open and not all_overdue and not all_today:
        return "", False

    lines = [f"**Daily Task Summary** — {today_str}"]
    lines.append(f"{total_open} open task(s) across all projects.")
    if all_overdue:
        lines.append(f"\n**Overdue ({len(all_overdue)}):**")
        for item in all_overdue:
            lines.append(f"  - {item}")
    if all_today:
        lines.append(f"\n**Due today ({len(all_today)}):**")
        for item in all_today:
            lines.append(f"  - {item}")
    if not all_overdue and not all_today:
        lines.append("No tasks overdue or due today.")

    # Mark as sent
    data["last_daily_notify"] = today_str
    save_reminders(data)

    return "\n".join(lines), True


# --- Formatting ---

def format_task_line(task):
    """Format a single task for terminal display with ANSI colors."""
    tid = task["id"]
    desc = task["description"]
    priority = task.get("priority", "normal")
    status = task.get("status", "open")
    due = task.get("due_date")
    notes = task.get("notes")

    # Status prefix
    if status == "done":
        prefix = f"{memory.DIM}[done]{memory.RESET} "
    else:
        prefix = ""

    # Priority marker
    if priority == "high":
        priority_tag = f" {memory.BOLD}[HIGH]{memory.RESET}"
    elif priority == "low":
        priority_tag = f" {memory.DIM}[low]{memory.RESET}"
    else:
        priority_tag = ""

    # Due date with color
    due_tag = ""
    if due and status != "done":
        try:
            due_dt = datetime.fromisoformat(due)
            due_str = due_dt.strftime("%b %d %I:%M%p").replace(" 0", " ").lower()
            group = _sort_group(task) if "_sort_group" in task else _sort_group(task)
            if group == "overdue":
                due_tag = f" {memory.RED}(overdue: {due_str}){memory.RESET}"
            elif group == "today":
                due_tag = f" {memory.YELLOW}(today {due_str}){memory.RESET}"
            else:
                due_tag = f" {memory.DIM}(due {due_str}){memory.RESET}"
        except (ValueError, TypeError):
            pass

    # Build line
    if status == "done":
        line = f"  {memory.DIM}#{tid} {desc}{priority_tag}{memory.RESET}"
    else:
        line = f"  {prefix}#{tid} {desc}{priority_tag}{due_tag}"

    if notes:
        note_preview = notes.splitlines()[0]
        if len(note_preview) > 60:
            note_preview = note_preview[:57] + "..."
        line += f"\n       {memory.DIM}note: {note_preview}{memory.RESET}"

    return line


def format_reminder_line(reminder):
    """Format a single reminder for terminal display."""
    rid = reminder["id"]
    desc = reminder["description"]
    remind_at = reminder.get("remind_at", "")
    project = reminder.get("project", "general")

    time_str = ""
    if remind_at:
        try:
            dt = datetime.fromisoformat(remind_at)
            time_str = dt.strftime("%b %d %I:%M%p").replace(" 0", " ").lower()
        except (ValueError, TypeError):
            time_str = remind_at

    project_tag = f" {memory.DIM}[{project}]{memory.RESET}" if project != memory.active_project else ""
    return f"  #{rid} {desc} — {memory.CYAN}{time_str}{memory.RESET}{project_tag}"
