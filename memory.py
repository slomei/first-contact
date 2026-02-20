"""
Shared memory, project, persona, and utility functions.

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
DIM = "\033[2m"
RESET = "\033[0m"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECTS_DIR = os.path.join(BASE_DIR, "projects")
PERSONAS_FILE = os.path.join(BASE_DIR, "personas.json")
JOB_SEARCH_PROJECT = "job-search"

# Gmail constants
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
GMAIL_CLIENT_SECRET = os.path.join(BASE_DIR, "gmail_client_secret.json")
GMAIL_CREDENTIALS = os.path.join(BASE_DIR, "gmail_credentials.json")

# Built-in personas
BUILTIN_PERSONAS = {
    "default": (
        "You are a blunt, witty collaborator. You give honest, direct answers "
        "without sugarcoating. You're not rude for the sake of it\u2014you're just "
        "efficient and real. If something is a bad idea, you say so. If someone's "
        "on the right track, you tell them that too, briefly. You have a dry sense "
        "of humor and zero patience for fluff."
    ),
    "writer": (
        "You are a screenplay collaborator. You focus on dialogue, structure, "
        "pacing, and character voice. You give feedback like a seasoned writer's "
        "room partner\u2014direct, constructive, and always in service of the story. "
        "You think in terms of scenes, beats, and subtext."
    ),
    "coder": (
        "You are a coding partner. You explain concepts clearly, write clean "
        "and well-structured code, and think through edge cases. You prefer "
        "practical solutions over clever ones. When reviewing code, you focus "
        "on correctness, readability, and maintainability."
    ),
    "critic": (
        "You are a brutally honest critic. You don't sugarcoat anything. You "
        "find weaknesses, logical gaps, and mediocrity. Your feedback is harsh "
        "but always specific and actionable. You have high standards and zero "
        "tolerance for hand-waving or half-baked ideas."
    ),
}

# Default models for built-in personas
BUILTIN_PERSONA_MODELS = {
    "default": "claude-sonnet-4-6",
    "writer":  "claude-opus-4-6",
    "coder":   "claude-opus-4-6",
    "critic":  "claude-sonnet-4-6",
}


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
active_persona = "default"


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


def get_jobs_file():
    """Return the jobs.json path, always in the job-search project."""
    d = os.path.join(PROJECTS_DIR, JOB_SEARCH_PROJECT)
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "jobs.json")


def get_resume_path():
    """Return the path to the extracted resume markdown file."""
    return os.path.join(PROJECTS_DIR, JOB_SEARCH_PROJECT, "resume.md")


# --- Persona functions ---

def load_personas():
    """Load custom personas from the JSON file.

    Supports both old format (string values) and new format (dict with
    'description' and optional 'model' keys).
    """
    if os.path.exists(PERSONAS_FILE):
        with open(PERSONAS_FILE, "r") as f:
            data = json.load(f)
        migrated = {}
        for k, v in data.items():
            if isinstance(v, str):
                migrated[k] = {"description": v}
            else:
                migrated[k] = v
        return migrated
    return {}


def save_personas(personas):
    """Save custom personas to the JSON file."""
    with open(PERSONAS_FILE, "w") as f:
        json.dump(personas, f, indent=2)


custom_personas = load_personas()


def get_persona_model(name):
    """Get the default model for a persona.

    Checks for a user override in custom_personas first, then falls back
    to the built-in default, then to sonnet.
    """
    if name in custom_personas and "model" in custom_personas[name]:
        return custom_personas[name]["model"]
    return BUILTIN_PERSONA_MODELS.get(name, "claude-sonnet-4-6")


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


def build_system_prompt(mems):
    """Build the system prompt, including any stored memories."""
    if active_persona in BUILTIN_PERSONAS:
        personality = BUILTIN_PERSONAS[active_persona]
    elif active_persona in custom_personas and "description" in custom_personas[active_persona]:
        personality = custom_personas[active_persona]["description"]
    else:
        personality = BUILTIN_PERSONAS["default"]

    tools_paragraph = (
        "You have tools available: web search, file read/write, memory, and "
        "Python code execution. Use them autonomously when appropriate. Search "
        "the web when asked about current events or when you're unsure about "
        "something factual. Read files when the user references them. Save facts "
        "to memory when the user shares personal preferences or important details. "
        "Run Python code when the user asks you to execute, test, or demonstrate "
        "code. Don't ask permission\u2014just use the tools."
    )

    specialist_paragraph = (
        "You also have specialist agents that handle tasks on your behalf. "
        "When a specialist has been consulted, their output will appear in the "
        "conversation as [Specialist result from <name>]. Synthesize their output "
        "into a coherent response for the user \u2014 you may present it as-is if it's "
        "already well-formatted, or add context, framing, and polish as needed."
    )

    base = personality + "\n\n" + tools_paragraph + "\n\n" + specialist_paragraph
    if mems:
        memory_block = "\n".join(f"- {m}" for m in mems)
        base += f"\n\nThings the user has asked you to remember:\n{memory_block}"
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
