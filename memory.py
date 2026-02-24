"""
Shared memory, project, and utility functions.

This is the base module with no internal dependencies.
All interfaces (chat.py, web_ui, discord_bot.py, telegram_bot.py) import from here.
"""

import json
import os
import re
import shutil
import subprocess
import webbrowser
from datetime import datetime
from zoneinfo import ZoneInfo

# --- Optional semantic search ---
SEMANTIC_AVAILABLE = False
_semantic_device = None
_embedding_model = None

try:
    import io, sys, logging, warnings
    # Suppress HuggingFace/transformers progress bars, load reports, and warnings
    logging.getLogger("transformers").setLevel(logging.ERROR)
    logging.getLogger("sentence_transformers").setLevel(logging.ERROR)
    warnings.filterwarnings("ignore", message=".*unauthenticated.*")
    _stderr_backup = sys.stderr
    sys.stderr = io.StringIO()
    try:
        from sentence_transformers import SentenceTransformer
        import torch
        _semantic_device = "cuda" if torch.cuda.is_available() else "cpu"
        _embedding_model = SentenceTransformer("all-MiniLM-L6-v2", device=_semantic_device)
        SEMANTIC_AVAILABLE = True
    finally:
        sys.stderr = _stderr_backup
except ImportError:
    pass

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

# Google Calendar constants — read + create events only
# Events scope only — read + create. NOT full calendar access.
# NOTE: Existing users must re-authenticate (`/cal setup`) after this scope change.
CALENDAR_SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
]
CALENDAR_CREDENTIALS = os.path.join(BASE_DIR, "calendar_credentials.json")


def get_timezone():
    """Return the user's timezone from config, defaulting to America/New_York."""
    try:
        config = load_config()
        tz_name = config.get("briefing", {}).get("timezone", "America/New_York")
        return ZoneInfo(tz_name)
    except Exception:
        return ZoneInfo("America/New_York")


def local_now():
    """Return the current datetime in the user's local timezone.

    Every module should use this instead of datetime.now() for user-facing
    timestamps, schedule checks, and date display. Only use bare datetime.now()
    for internal duration tracking where timezone doesn't matter.
    """
    return datetime.now(get_timezone())


# Default system prompt templates — {name} is substituted at build time
# _STABLE_PROMPT_TEMPLATE contains everything except the dynamic date/time prefix.
# _SYSTEM_PROMPT_TEMPLATE adds it back for callers that need a single string.
_STABLE_PROMPT_TEMPLATE = (
    "Calibrate your honesty. When something is genuinely good, say so and explain "
    "why it's good. When something is bad or mediocre, say so and explain why. "
    "Never default to praise, encouragement, or enthusiasm \u2014 earn it by actually "
    "evaluating the work. Never sugarcoat bad news to spare feelings. Never inflate "
    "quality to be supportive. The user deserves accurate feedback, not comfort. "
    "If you're unsure whether something is good, say you're unsure and explain "
    "your reasoning.\n\n"
    "You are {name}'s personal assistant. You know {name_pos} background, "
    "{name_pos} projects, and {name_pos} priorities through stored memories.\n\n"
    "CRITICAL RULE \u2014 ACT, DON'T ASK: When {name} asks you to do something, do it "
    "immediately. Call the tool right now. Do not ask for confirmation. Do not ask "
    "clarifying questions unless the request is truly ambiguous (i.e., you cannot "
    "construct a valid tool call without more info). Do not ask about optional "
    "fields the user didn't mention \u2014 if they wanted a description, duration, or "
    "other details, they would have said so. Use sensible defaults and act. "
    "Examples of what NOT to do: 'Want me to go ahead?', 'Shall I proceed?', "
    "'Should I add a description?', 'What duration?', 'Good to go?'. "
    "If a task has a programmatic confirmation gate (calendar events, file "
    "overwrites), that gate will show the details and ask \u2014 you do not add "
    "your own confirmation step on top of it.\n\n"
    "Never ask if something is a typo unless it affects a concrete output like "
    "a calendar event, email draft, file name, or cover letter. If you can "
    "interpret the intent, just act on it.\n\n"
    "Be honest. If an idea is good, say so and explain why. If it's bad, say so "
    "and explain why. Don't hedge to be polite and don't praise to make {name_obj} feel "
    "good. {name} respects directness and can handle being wrong \u2014 what {name_subj} can't "
    "handle is wasted time from someone telling {name_obj} what {name_subj} wants to hear.\n\n"
    "Don't perform enthusiasm. Don't over-explain things {name_subj} already understands. "
    "Don't ask unnecessary clarifying questions when the intent is obvious. Match "
    "the energy of the conversation \u2014 if {name_subj}'s brief, be brief. If {name_subj} wants depth, "
    "go deep.\n\n"
    "When you don't know something, say so. When you're uncertain, say that too. "
    "Don't guess and present it as fact.\n\n"
    "You have {tool_count} tools available including {tool_list}. Use them proactively: "
    "web_search for current events or unknown facts, read_file when files are referenced, "
    "save_note to capture ideas or research, remember for personal details, "
    "web_fetch when URLs are shared or search results need detail, "
    "create_task/create_reminder for action items, list_tasks to see what's open, "
    "complete_task/remove_task/edit_task/add_task_note to manage them, "
    "list_reminders/cancel_reminder for reminder management. "
    "Do NOT web_search when: (1) the answer is already in the conversation or stored memories "
    "\u2014 use what you know, (2) the user asks about their own data \u2014 use check_email, "
    "get_calendar_events, or list_memories instead, (3) the user is following up on a topic "
    "already discussed \u2014 continue from context, don't re-search.\n\n"
    "Tool parameter notes: remember defaults to global memory; set project_specific=true "
    "for project-only. forget requires an exact match to a stored memory. search_email "
    "query uses Gmail syntax (from:, subject:, has:attachment). All date/time parameters "
    "(due_date, remind_at, start_date, start_datetime, etc.) accept natural language. "
    "generate_pdf type cover_letter needs either job_id (from saved jobs) or "
    "company + job_title + job_description; type document needs title + body. "
    "create_calendar_event requires user confirmation. "
    "list_tasks defaults to open tasks in the current project; set all_projects=true "
    "to see tasks across all projects. Task and reminder management tools take numeric IDs "
    "from list_tasks/list_reminders output.\n\n"
    "You are First Contact, a personal AI agent built from scratch with the "
    "Anthropic API. You are not a chatbot \u2014 you are an agent with integrated "
    "tools that run locally on the user's machine. You support 4 interfaces: "
    "terminal, web UI, Discord, and Telegram. You use smart model routing \u2014 "
    "Haiku for research, Sonnet for conversation, Opus for deep analysis and "
    "creative writing. You have an extensible skills system with {skill_count} "
    "available skill{skill_s}, persistent memory with semantic search, and a "
    "background daemon for scheduled tasks. You were built security-first: "
    "draft-only email, sandboxed file access, human-in-the-loop for destructive "
    "operations. You are open source under MIT license at "
    "github.com/slomei/first-contact.\n\n"
    "{bio_line}"
)

_SYSTEM_PROMPT_TEMPLATE = "{today_line}\n\n" + _STABLE_PROMPT_TEMPLATE

# Challenge mode addendum template
_CHALLENGE_ADDENDUM_TEMPLATE = (
    "\n\nCHALLENGE MODE IS ON. Actively look for flaws, gaps, and weak assumptions "
    "in {name}'s reasoning. Play devil's advocate. Push back on ideas that seem "
    "under-examined. Don't be contrarian for its own sake \u2014 but if there's a hole, "
    "find it and call it out."
)


def _get_prompt_vars():
    """Get shared format variables for system prompt templates."""
    profile = get_user_profile()
    name = profile.get("first_name") or profile.get("name", "the user")

    # Build a bio line from available profile info
    bio_parts = []
    if profile.get("experience_summary"):
        bio_parts.append(profile["experience_summary"])
    elif profile.get("title"):
        bio_parts.append(f"{name} is a {profile['title']}.")
    bio_line = " ".join(bio_parts) if bio_parts else ""

    # Dynamic tool count and names (lazy import to avoid circular dep)
    try:
        import tools
        tool_names = [t["name"] for t in tools.TOOLS]
        tool_count = len(tool_names)
        tool_list = ", ".join(tool_names)
    except (ImportError, AttributeError):
        tool_count = 18
        tool_list = "web search, email, calendar, file operations, memory, code execution, job search"

    # Dynamic skill count (lazy import)
    try:
        import skills_loader
        skill_count = len(skills_loader.list_skills())
    except (ImportError, AttributeError):
        skill_count = 0

    return {
        "name": name,
        "name_pos": name + "'s" if name != "the user" else "their",
        "name_subj": name.lower() if name != "the user" else "they",
        "name_obj": name.lower() if name != "the user" else "them",
        "bio_line": bio_line,
        "tool_count": tool_count,
        "tool_list": tool_list,
        "skill_count": skill_count,
        "skill_s": "s" if skill_count != 1 else "",
    }


def _build_base_prompt():
    """Build the system prompt with the user's name from config."""
    fmt = _get_prompt_vars()
    fmt["today_line"] = local_now().strftime("Today is %A, %B %d, %Y. Current time: %-I:%M %p.")
    return _SYSTEM_PROMPT_TEMPLATE.format(**fmt)


def _build_challenge_addendum():
    """Build the challenge mode addendum with the user's name."""
    profile = get_user_profile()
    name = profile.get("first_name") or profile.get("name", "the user")
    return _CHALLENGE_ADDENDUM_TEMPLATE.format(name=name)


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


def open_file(filepath):
    """Open a file in the default application, with WSL support."""
    if IS_WSL:
        try:
            win_path = subprocess.check_output(
                ["wslpath", "-w", filepath], text=True
            ).strip()
            subprocess.Popen(
                ["cmd.exe", "/c", "start", "", win_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass
    else:
        import platform
        if platform.system() == "Darwin":
            subprocess.Popen(["open", filepath])
        else:
            subprocess.Popen(["xdg-open", filepath])


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


def get_files_dir():
    """Return the files directory for the active project."""
    d = os.path.join(get_project_dir(), "files")
    os.makedirs(d, exist_ok=True)
    return d


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
            "priority_domains": [],
            "priority_keywords": [
                "interview", "offer", "application", "schedule",
                "follow up", "hiring", "position", "opportunity",
            ],
            "mute_domains": [
                "noreply@google.com", "marketing@", "newsletter@",
            ],
        },
        "job_scan": {
            "enabled": True,
            "queries": [],
            "auto_time": "07:00",
            "skip_weekends": True,
            "monday_time": "06:00",
            "last_auto_scan": None,
        },
        "daemon": {
            "enabled": True,
            "briefing_time": "07:00",
            "email_check_interval_minutes": 30,
            "scan_interval_hours": 12,
            "reminder_check_interval_minutes": 5,
            "heartbeat_interval_minutes": 30,
            "notify_channel": "discord",
        },
        "custom_prompt": "",
        "email_accounts": [],
        "notification_channels": [],
        "discord_prefix": "!fc",
        "user_profile": {
            "name": "Your Name",
            "first_name": "You",
            "email": "you@example.com",
            "phone": "",
            "website": "",
            "location": "",
            "title": "Your Title",
            "experience_summary": "",
            "tools": [],
            "credits": [],
            "target_roles": [],
        },
    }
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                config = json.load(f)
            if not isinstance(config, dict):
                return defaults
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


def get_user_profile():
    """Return the user_profile dict from config."""
    return load_config().get("user_profile", {})


def get_custom_prompt():
    """Return the custom system prompt text, or empty string."""
    return load_config().get("custom_prompt", "")


def set_custom_prompt(text):
    """Set or clear the custom system prompt text."""
    cfg = load_config()
    cfg["custom_prompt"] = text
    save_config(cfg)


def get_jobs_file():
    """Return the jobs.json path, always in the job-search project."""
    d = os.path.join(PROJECTS_DIR, JOB_SEARCH_PROJECT)
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "jobs.json")


def get_resume_path():
    """Return the path to the extracted resume markdown file."""
    return os.path.join(PROJECTS_DIR, JOB_SEARCH_PROJECT, "resume.md")


# --- Semantic search internals ---

_global_memory_cache = {}   # text -> {"embedding": list|None, "created": str|None}
_project_memory_cache = {}


def _embed(text):
    """Generate 384-dim embedding vector."""
    return _embedding_model.encode(text, convert_to_numpy=True).tolist()


def _cosine_similarity(a, b):
    """Cosine similarity between two float lists."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _load_memory_file(path):
    """Load memory file, handling old and new formats.

    Old format: ["fact1", "fact2"]
    New format: {"memories": [{"text": "...", "embedding": [...], "created": "..."}]}

    Returns (texts: list[str], cache: dict).
    """
    if not os.path.exists(path):
        return [], {}
    try:
        with open(path, "r") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return [], {}

    if isinstance(data, list):
        # Old format — migrate: return texts with empty cache entries
        cache = {}
        for text in data:
            cache[text] = {"embedding": None, "created": None}
        return data, cache

    # New format
    texts = []
    cache = {}
    for entry in data.get("memories", []):
        text = entry.get("text", "")
        texts.append(text)
        cache[text] = {
            "embedding": entry.get("embedding"),
            "created": entry.get("created"),
        }
    return texts, cache


def _save_memory_file(path, texts, cache):
    """Save in new dict format, generating embeddings for new entries if available."""
    entries = []
    for text in texts:
        meta = cache.get(text, {})
        embedding = meta.get("embedding")
        created = meta.get("created")

        # Generate embedding for new entries if semantic is available
        if embedding is None and SEMANTIC_AVAILABLE:
            embedding = _embed(text)
            # Update cache in place
            if text in cache:
                cache[text]["embedding"] = embedding

        if created is None:
            created = local_now().strftime("%Y-%m-%d %H:%M")
            if text in cache:
                cache[text]["created"] = created

        entries.append({
            "text": text,
            "embedding": embedding,
            "created": created,
        })

    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
    with open(path, "w") as f:
        json.dump({"memories": entries}, f, indent=2)


# --- Memory functions ---

def load_memories():
    """Load memories from the active project's memory file only."""
    global _project_memory_cache
    path = get_memory_file()
    texts, cache = _load_memory_file(path)
    _project_memory_cache = cache
    return texts


def save_memories(mems):
    """Save memories to the active project's memory file."""
    global _project_memory_cache
    # Drop removed entries from cache
    _project_memory_cache = {k: v for k, v in _project_memory_cache.items() if k in mems}
    # Add new entries
    for m in mems:
        if m not in _project_memory_cache:
            _project_memory_cache[m] = {"embedding": None, "created": None}
    path = get_memory_file()
    _save_memory_file(path, mems, _project_memory_cache)


def load_global_memories():
    """Load memories from root memory.json (global layer)."""
    global _global_memory_cache
    path = os.path.join(BASE_DIR, "memory.json")
    texts, cache = _load_memory_file(path)
    _global_memory_cache = cache
    return texts


def save_global_memories(mems):
    """Save memories to root memory.json (global layer)."""
    global _global_memory_cache
    # Drop removed entries from cache
    _global_memory_cache = {k: v for k, v in _global_memory_cache.items() if k in mems}
    # Add new entries
    for m in mems:
        if m not in _global_memory_cache:
            _global_memory_cache[m] = {"embedding": None, "created": None}
    path = os.path.join(BASE_DIR, "memory.json")
    _save_memory_file(path, mems, _global_memory_cache)


def load_all_memories():
    """Load and deduplicate global + project memories.

    Returns (combined, global_list, project_list).
    """
    global_mems = load_global_memories()
    project_mems = load_memories()
    combined = list(dict.fromkeys(global_mems + project_mems))
    return combined, global_mems, project_mems


def retrieve_relevant_memories(query, top_k=10):
    """Return the most relevant memories for a query.

    When semantic search is unavailable or memory count <= top_k, returns all.
    """
    combined, _, _ = load_all_memories()
    if not SEMANTIC_AVAILABLE or len(combined) <= top_k:
        return combined

    query_embedding = _embed(query)
    merged_cache = {**_global_memory_cache, **_project_memory_cache}

    scored = []
    for text in combined:
        meta = merged_cache.get(text, {})
        emb = meta.get("embedding")
        if emb is None:
            continue
        score = _cosine_similarity(query_embedding, emb)
        scored.append((text, score))

    scored.sort(key=lambda x: x[1], reverse=True)
    return [text for text, _ in scored[:top_k]]


def retrieve_relevant_memories_scored(query, top_k=5):
    """Return the most relevant memories with similarity scores.

    Returns list of (text, similarity_score) tuples.
    """
    combined, _, _ = load_all_memories()
    if not SEMANTIC_AVAILABLE:
        return [(text, 0.0) for text in combined[:top_k]]

    if len(combined) <= top_k:
        # Still score them for display
        query_embedding = _embed(query)
        merged_cache = {**_global_memory_cache, **_project_memory_cache}
        results = []
        for text in combined:
            meta = merged_cache.get(text, {})
            emb = meta.get("embedding")
            if emb is not None:
                score = _cosine_similarity(query_embedding, emb)
            else:
                score = 0.0
            results.append((text, score))
        results.sort(key=lambda x: x[1], reverse=True)
        return results

    query_embedding = _embed(query)
    merged_cache = {**_global_memory_cache, **_project_memory_cache}

    scored = []
    for text in combined:
        meta = merged_cache.get(text, {})
        emb = meta.get("embedding")
        if emb is None:
            continue
        score = _cosine_similarity(query_embedding, emb)
        scored.append((text, score))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]


def get_semantic_status():
    """Return a status string describing the memory search mode."""
    if SEMANTIC_AVAILABLE:
        device = "GPU" if _semantic_device == "cuda" else "CPU"
        return f"Memory: semantic search ({device})"
    return "Memory: basic (install sentence-transformers for smart retrieval)"


def get_cross_project_summary():
    """Scan all project dirs (skipping active) and return a summary string."""
    if not os.path.exists(PROJECTS_DIR):
        return ""
    lines = []
    for project_name in sorted(os.listdir(PROJECTS_DIR)):
        if project_name == active_project:
            continue
        project_dir = os.path.join(PROJECTS_DIR, project_name)
        if not os.path.isdir(project_dir):
            continue

        parts = [f"- {project_name}:"]

        # Open task count
        tasks_path = os.path.join(project_dir, "tasks.json")
        if os.path.exists(tasks_path):
            try:
                with open(tasks_path, "r") as f:
                    task_data = json.load(f)
                task_list = task_data.get("tasks", []) if isinstance(task_data, dict) else task_data if isinstance(task_data, list) else []
                open_count = sum(1 for t in task_list if isinstance(t, dict) and t.get("status") == "open")
                if open_count:
                    parts.append(f"{open_count} open task{'s' if open_count != 1 else ''}")
            except (json.JSONDecodeError, OSError):
                pass

        # Conversation count
        conv_dir = os.path.join(project_dir, "conversations")
        if os.path.isdir(conv_dir):
            conv_count = len([f for f in os.listdir(conv_dir) if f.endswith(".txt")])
            if conv_count:
                parts.append(f"{conv_count} conversation{'s' if conv_count != 1 else ''}")

        # Saved jobs count (job-search only)
        if project_name == JOB_SEARCH_PROJECT:
            jobs_path = os.path.join(project_dir, "jobs.json")
            if os.path.exists(jobs_path):
                try:
                    with open(jobs_path, "r") as f:
                        jobs_data = json.load(f)
                    jobs_count = len(jobs_data) if isinstance(jobs_data, list) else 0
                    if jobs_count:
                        parts.append(f"{jobs_count} saved job{'s' if jobs_count != 1 else ''}")
                except (json.JSONDecodeError, OSError):
                    pass

        if len(parts) > 1:
            lines.append(" ".join(parts))
    return "\n".join(lines)


def get_detailed_project_summaries():
    """Return richer summaries for the general project view."""
    if not os.path.exists(PROJECTS_DIR):
        return ""
    lines = []
    for project_name in sorted(os.listdir(PROJECTS_DIR)):
        if project_name == active_project:
            continue
        project_dir = os.path.join(PROJECTS_DIR, project_name)
        if not os.path.isdir(project_dir):
            continue

        parts = [f"**{project_name}**"]

        # Last 3 conversation titles
        conv_dir = os.path.join(project_dir, "conversations")
        if os.path.isdir(conv_dir):
            conv_files = sorted(
                [f for f in os.listdir(conv_dir) if f.endswith(".txt")],
                reverse=True,
            )[:3]
            if conv_files:
                titles = [os.path.splitext(f)[0].replace("-", " ").title() for f in conv_files]
                parts.append("Recent: " + ", ".join(titles))

        # Open task count with next due date
        tasks_path = os.path.join(project_dir, "tasks.json")
        if os.path.exists(tasks_path):
            try:
                with open(tasks_path, "r") as f:
                    task_data = json.load(f)
                task_list = task_data.get("tasks", []) if isinstance(task_data, dict) else task_data if isinstance(task_data, list) else []
                open_tasks = [t for t in task_list if isinstance(t, dict) and t.get("status") == "open"]
                if open_tasks:
                    due_dates = []
                    for t in open_tasks:
                        if t.get("due_date"):
                            due_dates.append(t["due_date"])
                    due_str = f" (next due: {min(due_dates)})" if due_dates else ""
                    parts.append(f"{len(open_tasks)} open task{'s' if len(open_tasks) != 1 else ''}{due_str}")
            except (json.JSONDecodeError, OSError):
                pass

        # Saved jobs count (job-search only)
        if project_name == JOB_SEARCH_PROJECT:
            jobs_path = os.path.join(project_dir, "jobs.json")
            if os.path.exists(jobs_path):
                try:
                    with open(jobs_path, "r") as f:
                        jobs_data = json.load(f)
                    jobs_count = len(jobs_data) if isinstance(jobs_data, list) else 0
                    if jobs_count:
                        parts.append(f"{jobs_count} saved job{'s' if jobs_count != 1 else ''}")
                except (json.JSONDecodeError, OSError):
                    pass

        if len(parts) > 1:
            lines.append("  ".join(parts))
    return "\n".join(lines)


def _build_stable_prompt():
    """Build the cacheable (session-stable) portion of the system prompt.

    Includes behavioral instructions, identity, challenge mode, custom prompt,
    resume reference, cross-project summary, and integration status.
    These change only on explicit user action, not per-turn.
    """
    base = _STABLE_PROMPT_TEMPLATE.format(**_get_prompt_vars())

    if challenge_mode:
        base += _build_challenge_addendum()

    custom = get_custom_prompt()
    if custom:
        base += f"\n\nCustom instructions from the user:\n{custom}"

    # Resume reference
    resume_path = get_resume_path()
    if os.path.exists(resume_path):
        base += (
            "\n\nResume is available at: "
            f"{resume_path} — use read_file to access it when needed for "
            "cover letters, applications, or professional context."
        )

    # Cross-project summary
    if active_project == "general":
        detailed = get_detailed_project_summaries()
        if detailed:
            base += f"\n\nOther projects:\n{detailed}"
    else:
        summary = get_cross_project_summary()
        if summary:
            base += f"\n\nOther projects:\n{summary}"

    # Integration status (reads cached status from startup — no re-check)
    import service_registry
    connected = []
    if service_registry.is_available("gmail"):
        connected.append("Gmail")
    if service_registry.is_available("calendar"):
        connected.append("Google Calendar")
    if connected:
        base += f"\n\nConnected integrations: {', '.join(connected)}"

    # User model — stable tier (cached): preferences, high-confidence facts, goals
    try:
        import user_model
        profile_text = user_model.format_stable_profile()
        if profile_text:
            base += f"\n\n{profile_text}"
    except Exception:
        pass

    return base


def _build_dynamic_prompt(mems, creative_context="", query=None):
    """Build the per-turn dynamic portion of the system prompt.

    Includes date/time, memories (semantic or all), and creative context.
    """
    parts = []

    # Date/time
    today_line = local_now().strftime("Today is %A, %B %d, %Y. Current time: %-I:%M %p.")
    parts.append(today_line)

    # Memories
    if query and SEMANTIC_AVAILABLE:
        relevant = retrieve_relevant_memories(query, top_k=15)
        global_set = set(load_global_memories())
        relevant_global = [m for m in relevant if m in global_set]
        relevant_project = [m for m in relevant if m not in global_set]

        if relevant_global:
            block = "\n".join(f"- {m}" for m in relevant_global)
            parts.append(f"Core facts (most relevant):\n{block}")
        if relevant_project:
            project_block = "\n".join(f"- {m}" for m in relevant_project)
            parts.append(f"Project memories ({active_project}, most relevant):\n{project_block}")
    else:
        global_mems = load_global_memories()
        if global_mems:
            block = "\n".join(f"- {m}" for m in global_mems)
            parts.append(f"Core facts (always available):\n{block}")

        if mems:
            project_block = "\n".join(f"- {m}" for m in mems)
            parts.append(f"Project memories ({active_project}):\n{project_block}")

    # User model — contextual tier (per-turn): lower-confidence facts, patterns filtered by query
    if query:
        try:
            import user_model
            contextual_text = user_model.format_contextual_profile(query)
            if contextual_text:
                parts.append(contextual_text)
        except Exception:
            pass

    if creative_context:
        parts.append(
            "You are working on the First Light sci-fi project. Here is the world bible "
            "reference material. Use this to write in-universe — maintain consistent characterization, "
            "locations, and tone. Route dialogue and scene work through your best creative writing.\n\n"
            + creative_context
        )

    return "\n\n".join(parts)


def build_system_prompt(mems, creative_context="", query=None):
    """Build the system prompt with global memories, project memories, resume ref, and cross-project summary."""
    base = _build_base_prompt()
    if challenge_mode:
        base += _build_challenge_addendum()

    custom = get_custom_prompt()
    if custom:
        base += f"\n\nCustom instructions from the user:\n{custom}"

    if query and SEMANTIC_AVAILABLE:
        # Semantic retrieval: get the most relevant memories
        relevant = retrieve_relevant_memories(query, top_k=15)
        # Split back into global/project for labeled display
        global_set = set(load_global_memories())
        relevant_global = [m for m in relevant if m in global_set]
        relevant_project = [m for m in relevant if m not in global_set]

        if relevant_global:
            block = "\n".join(f"- {m}" for m in relevant_global)
            base += f"\n\nCore facts (most relevant):\n{block}"
        if relevant_project:
            project_block = "\n".join(f"- {m}" for m in relevant_project)
            base += f"\n\nProject memories ({active_project}, most relevant):\n{project_block}"
    else:
        # Fallback: load all memories (original behavior)
        global_mems = load_global_memories()
        if global_mems:
            block = "\n".join(f"- {m}" for m in global_mems)
            base += f"\n\nCore facts (always available):\n{block}"

        if mems:
            project_block = "\n".join(f"- {m}" for m in mems)
            base += f"\n\nProject memories ({active_project}):\n{project_block}"

    # Resume reference
    resume_path = get_resume_path()
    if os.path.exists(resume_path):
        base += (
            "\n\nResume is available at: "
            f"{resume_path} — use read_file to access it when needed for "
            "cover letters, applications, or professional context."
        )

    # Cross-project summary
    if active_project == "general":
        detailed = get_detailed_project_summaries()
        if detailed:
            base += f"\n\nOther projects:\n{detailed}"
    else:
        summary = get_cross_project_summary()
        if summary:
            base += f"\n\nOther projects:\n{summary}"

    # Integration status (reads cached status from startup — no re-check)
    import service_registry
    connected = []
    if service_registry.is_available("gmail"):
        connected.append("Gmail")
    if service_registry.is_available("calendar"):
        connected.append("Google Calendar")
    if connected:
        base += f"\n\nConnected integrations: {', '.join(connected)}"

    if creative_context:
        base += (
            "\n\nYou are working on the First Light sci-fi project. Here is the world bible "
            "reference material. Use this to write in-universe — maintain consistent characterization, "
            "locations, and tone. Route dialogue and scene work through your best creative writing.\n\n"
            + creative_context
        )
    return base


def build_system_prompt_cached(mems, creative_context="", query=None):
    """Build system prompt as content blocks with cache_control for prompt caching.

    Returns two blocks: a stable block (cached) and a dynamic block (per-turn).
    The stable block contains behavioral instructions, identity, and session config.
    The dynamic block contains date/time, memories, and creative context.
    """
    stable_text = _build_stable_prompt()
    dynamic_text = _build_dynamic_prompt(mems, creative_context=creative_context, query=query)
    return [
        {"type": "text", "text": stable_text, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": dynamic_text},
    ]


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
        try:
            with open(path, "r") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return []
        return data if isinstance(data, list) else []
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
        try:
            with open(path, "r") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return []
        return data if isinstance(data, list) else []
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

    base = slugify(job.get("title", "")) or "untitled"
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
            "saved_at": job.get("saved_at", local_now().strftime("%Y-%m-%d")),
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


def reset_all_data(include_config=False):
    """Delete all user data and return the app to a clean first-launch state.

    Removes projects/, conversations/, logs/, memory.json, reminders.json,
    and Claude.md. Optionally removes config.json to re-trigger onboarding.

    Never touches: .env, gmail_client_secret.json, gmail_credentials.json,
    calendar_credentials.json, config.example.json, .env.example, source code,
    venv/, .git/
    """
    # Directories to wipe
    dirs_to_remove = [
        PROJECTS_DIR,
        os.path.join(BASE_DIR, "conversations"),
        os.path.join(BASE_DIR, "logs"),
    ]
    for d in dirs_to_remove:
        if os.path.isdir(d):
            shutil.rmtree(d)

    # Individual files to remove
    files_to_remove = [
        os.path.join(BASE_DIR, "memory.json"),
        os.path.join(BASE_DIR, "reminders.json"),
        os.path.join(BASE_DIR, "user_profile.json"),
        os.path.join(BASE_DIR, "Claude.md"),
    ]
    if include_config:
        files_to_remove.append(os.path.join(BASE_DIR, "config.json"))

    for f in files_to_remove:
        try:
            os.remove(f)
        except FileNotFoundError:
            pass
