"""
Shared memory, project, and utility functions.

This is the base module with no internal dependencies.
All three interfaces (chat.py, discord_bot.py, gui.py) import from here.
"""

import json
import os
import re
import subprocess
import webbrowser

# ANSI color codes for terminal output
GREEN = "\033[32m"
CYAN = "\033[36m"
RED = "\033[31m"
YELLOW = "\033[33m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECTS_DIR = os.path.join(BASE_DIR, "projects")
JOB_SEARCH_PROJECT = "job-search"

# Gmail constants — readonly + compose (drafts only, NO gmail.send)
GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
]
GMAIL_CLIENT_SECRET = os.path.join(BASE_DIR, "gmail_client_secret.json")
GMAIL_CREDENTIALS = os.path.join(BASE_DIR, "gmail_credentials.json")

# Google Calendar constants — read + create (NO delete, NO modify)
CALENDAR_SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar",
]
CALENDAR_CREDENTIALS = os.path.join(BASE_DIR, "calendar_credentials.json")

# Default system prompt
SYSTEM_PROMPT = (
    "You are Steve's personal assistant. You know his background, his projects, "
    "and his priorities through stored memories.\n\n"
    "Be honest. If an idea is good, say so and explain why. If it's bad, say so "
    "and explain why. Don't hedge to be polite and don't praise to make him feel "
    "good. Steve respects directness and can handle being wrong \u2014 what he can't "
    "handle is wasted time from someone telling him what he wants to hear.\n\n"
    "Don't perform enthusiasm. Don't over-explain things he already understands. "
    "Don't ask unnecessary clarifying questions when the intent is obvious. Match "
    "the energy of the conversation \u2014 if he's brief, be brief. If he wants depth, "
    "go deep.\n\n"
    "When you don't know something, say so. When you're uncertain, say that too. "
    "Don't guess and present it as fact.\n\n"
    "You have tools available \u2014 web search, file operations, memory, email, code "
    "execution, job search. Use them when they'd help. Don't ask permission to use "
    "tools unless the action is irreversible or costly.\n\n"
    "Steve is a video editor with 13 years in animation, currently job searching "
    "and building an AI agent system. He's working on a sci-fi screenplay called "
    "First Light. He's smart, technically capable, and learning fast. Treat him "
    "accordingly."
)

# Challenge mode addendum (appended when challenge_mode is True)
CHALLENGE_ADDENDUM = (
    "\n\nCHALLENGE MODE IS ON. Actively look for flaws, gaps, and weak assumptions "
    "in Steve's reasoning. Play devil's advocate. Push back on ideas that seem "
    "under-examined. Don't be contrarian for its own sake \u2014 but if there's a hole, "
    "find it and call it out."
)


def _is_wsl():
    """Detect if running inside Windows Subsystem for Linux."""
    try:
        with open("/proc/version", "r") as f:
            return "microsoft" in f.read().lower()
    except OSError:
        return False

IS_WSL = _is_wsl()


def open_url(url):
    """Open a URL in the default browser, with WSL support."""
    if IS_WSL:
        subprocess.Popen(
            ["cmd.exe", "/c", "start", "", url],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        webbrowser.open(url)


# --- Mutable globals ---
active_project = "general"
challenge_mode = False


def get_project_dir():
    """Return the directory for the active project, creating it if needed."""
    d = os.path.join(PROJECTS_DIR, active_project)
    os.makedirs(d, exist_ok=True)
    return d


def get_conversations_dir():
    """Return the conversations directory for the active project."""
    d = os.path.join(get_project_dir(), "conversations")
    os.makedirs(d, exist_ok=True)
    return d


def get_workspace_dir():
    """Return the workspace directory for the active project."""
    d = os.path.join(get_project_dir(), "workspace")
    os.makedirs(d, exist_ok=True)
    return d


def get_memory_file():
    """Return the memory file path for the active project."""
    return os.path.join(get_project_dir(), "memory.json")


def get_watchlist_file():
    """Return the watchlist file path for the active project."""
    return os.path.join(get_project_dir(), "watchlist.json")


def get_tasks_file():
    """Return the tasks.json path for the active project."""
    return os.path.join(get_project_dir(), "tasks.json")


def get_reminders_file():
    """Return the global reminders.json path (not per-project)."""
    return os.path.join(BASE_DIR, "reminders.json")


def get_config_file():
    """Return the global config.json path."""
    return os.path.join(BASE_DIR, "config.json")


def load_config():
    """Load config from config.json, creating with defaults if needed."""
    path = get_config_file()
    defaults = {
        "briefing": {
            "enabled": True,
            "time": "08:00",
            "timezone": "America/New_York",
            "last_sent": None,
        },
        "email_notifications": {
            "enabled": True,
            "check_interval_minutes": 5,
            "batch_interval_minutes": 30,
            "last_checked": None,
            "priority_domains": [
                "netflix.com", "disney.com", "dreamworks.com",
                "illumination.com", "sony.com", "warnerbros.com",
                "paramount.com", "apple.com", "amazon.com",
                "blueskyanimation.com", "pixar.com", "dneg.com",
                "framestore.com",
            ],
            "priority_keywords": [
                "interview", "offer", "application", "schedule",
                "follow up", "hiring", "position", "opportunity",
                "editorial", "editor",
            ],
            "mute_domains": [
                "noreply@google.com", "marketing@", "newsletter@",
            ],
        },
        "job_scan": {
            "enabled": True,
            "queries": [
                "assistant editor animation",
                "video editor post production",
                "editorial animation studio",
            ],
            "auto_time": "07:00",
            "skip_weekends": True,
            "monday_time": "06:00",
            "last_auto_scan": None,
        },
    }
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                config = json.load(f)
            # Merge in any missing default keys
            for key, val in defaults.items():
                if key not in config:
                    config[key] = val
                elif isinstance(val, dict):
                    for k, v in val.items():
                        if k not in config[key]:
                            config[key][k] = v
            return config
        except (json.JSONDecodeError, OSError):
            pass
    return defaults


def save_config(config):
    """Save config to config.json."""
    path = get_config_file()
    with open(path, "w") as f:
        json.dump(config, f, indent=2)


def get_jobs_file():
    """Return the jobs.json path, always in the job-search project."""
    d = os.path.join(PROJECTS_DIR, JOB_SEARCH_PROJECT)
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "jobs.json")


def get_resume_path():
    """Return the path to the extracted resume markdown file."""
    return os.path.join(PROJECTS_DIR, JOB_SEARCH_PROJECT, "resume.md")


# --- Memory functions ---

def load_memories():
    """Load memories from the active project's memory file, falling back to root."""
    path = get_memory_file()
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    root_path = os.path.join(BASE_DIR, "memory.json")
    if os.path.exists(root_path):
        with open(root_path, "r") as f:
            return json.load(f)
    return []


def save_memories(mems):
    """Save memories to the active project's memory file."""
    path = get_memory_file()
    with open(path, "w") as f:
        json.dump(mems, f, indent=2)


def build_system_prompt(mems, creative_context=""):
    """Build the system prompt, including stored memories, challenge mode, and creative context."""
    base = SYSTEM_PROMPT
    if challenge_mode:
        base += CHALLENGE_ADDENDUM
    if mems:
        memory_block = "\n".join(f"- {m}" for m in mems)
        base += f"\n\nThings you've been asked to remember:\n{memory_block}"
    if creative_context:
        base += (
            "\n\nYou are working on the First Light sci-fi project. Here is the world bible "
            "reference material. Use this to write in-universe — maintain consistent characterization, "
            "locations, and tone. Route dialogue and scene work through your best creative writing.\n\n"
            + creative_context
        )
    return base


memories = load_memories()


# --- Project functions ---

def switch_project(name):
    """Switch to a project, creating it if needed."""
    global active_project, memories
    active_project = name
    get_conversations_dir()
    get_workspace_dir()
    memories = load_memories()


def list_projects():
    """List all project names."""
    if not os.path.exists(PROJECTS_DIR):
        return ["general"]
    projects = sorted([
        d for d in os.listdir(PROJECTS_DIR)
        if os.path.isdir(os.path.join(PROJECTS_DIR, d))
    ])
    return projects if projects else ["general"]


# --- Watchlist functions ---

def load_watchlist():
    """Load watchlist from the active project's watchlist.json."""
    path = get_watchlist_file()
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return []


def save_watchlist(topics):
    """Save watchlist to the active project's watchlist.json."""
    path = get_watchlist_file()
    with open(path, "w") as f:
        json.dump(topics, f, indent=2)


# --- Jobs I/O ---

def load_jobs():
    """Load saved jobs from the job-search project."""
    path = get_jobs_file()
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return []


def save_jobs(jobs):
    """Save jobs to the job-search project."""
    path = get_jobs_file()
    with open(path, "w") as f:
        json.dump(jobs, f, indent=2)


def get_job_folder(job):
    """Get or create a job's subfolder in the job-search workspace."""
    jobs_dir = os.path.join(PROJECTS_DIR, JOB_SEARCH_PROJECT, "workspace", "jobs")
    os.makedirs(jobs_dir, exist_ok=True)

    if job.get("folder"):
        folder_path = os.path.join(jobs_dir, job["folder"])
        os.makedirs(folder_path, exist_ok=True)
        return folder_path

    base = slugify(job["title"]) or "untitled"
    folder_name = base
    if os.path.exists(os.path.join(jobs_dir, folder_name)):
        i = 2
        while os.path.exists(os.path.join(jobs_dir, f"{folder_name}-{i}")):
            i += 1
        folder_name = f"{folder_name}-{i}"

    job["folder"] = folder_name
    folder_path = os.path.join(jobs_dir, folder_name)
    os.makedirs(folder_path, exist_ok=True)
    return folder_path


def init_job_folder(job):
    """Create a job's subfolder and write listing.json and notes.md."""
    from datetime import datetime
    folder = get_job_folder(job)

    listing_path = os.path.join(folder, "listing.json")
    with open(listing_path, "w") as f:
        json.dump({
            "title": job["title"],
            "url": job["url"],
            "description": job["body"],
            "saved_at": job.get("saved_at", datetime.now().strftime("%Y-%m-%d")),
            "status": job.get("status"),
        }, f, indent=2)

    notes_path = os.path.join(folder, "notes.md")
    if not os.path.exists(notes_path):
        with open(notes_path, "w") as f:
            f.write(f"# {job['title']}\n\n{job['url']}\n\n## Notes\n\n")

    return folder


# --- Conversation helpers ---

def list_conversations():
    """Return sorted list of conversation filenames, or empty list."""
    conversations_dir = get_conversations_dir()
    files = [f for f in sorted(os.listdir(conversations_dir)) if f.endswith(".txt")]
    return files


def slugify(text):
    """Convert text to a filename-safe slug."""
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_]+', '-', text)
    text = re.sub(r'-+', '-', text)
    return text.strip('-')[:60]
