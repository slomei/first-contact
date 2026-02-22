"""
Shared help categories and per-interface formatters.

Single source of truth for all help text across terminal, Discord,
Telegram, and GUI interfaces.
"""

HELP_CATEGORIES = {
    "chat": {
        "desc": "Conversation and model controls",
        "commands": [
            ("/opus, /sonnet, /haiku", "Switch Claude model"),
            ("/challenge on|off", "Toggle devil's advocate mode"),
            ("/new", "Save conversation and start fresh"),
            ("/load", "Load a previous conversation"),
            ("/conversations", "List saved conversations"),
            ("/delete", "Delete a saved conversation"),
            ("/clear", "Clear the screen"),
        ],
        "tip": "Claude picks the best model automatically. Use these to override.",
    },
    "memory": {
        "desc": "Persistent facts and notes",
        "commands": [
            ("/remember <fact>", "Save a fact to global memory"),
            ("/remember -p <fact>", "Save a fact to project memory"),
            ("/forget <fact>", "Remove a fact from memory"),
            ("/memories", "List all stored memories"),
            ("/memories search <q>", "Semantic search across memories"),
            ("/note <text>", "Save a timestamped note"),
            ("/notes", "List recent notes (last 7 days)"),
            ("/notes search <q>", "Search notes by keyword"),
        ],
        "tip": "Global memories persist across all projects. Use -p for project-only facts.",
    },
    "email": {
        "desc": "Gmail integration and drafting",
        "commands": [
            ("/email check", "Show recent unread emails"),
            ("/email read <#>", "Read full email by number"),
            ("/email search <q>", "Search emails by keyword"),
            ("/draft reply", "Draft a reply to the last-read email"),
            ("/draft new <to> [subj]", "Compose a new email draft"),
            ("/draft work <#>", "Draft a job application email"),
            ("/drafts", "List drafts created this session"),
            ("/email setup", "Authenticate with Gmail (OAuth2)"),
        ],
        "tip": "Drafts are created in Gmail — the agent never sends email directly.",
    },
    "calendar": {
        "desc": "Google Calendar events",
        "commands": [
            ("/cal", "Show today's events"),
            ("/cal tomorrow", "Tomorrow's events"),
            ("/cal week", "Next 7 days"),
            ("/cal <date>", "Events for a specific date"),
            ("/cal add <desc>", "Create event (with confirmation)"),
            ("/cal setup", "Authenticate with Google Calendar"),
        ],
        "tip": "Use natural language for dates: 'next friday', 'march 5th'.",
    },
    "jobs": {
        "desc": "Job search, tracking, and applications",
        "commands": [
            ("/work search <q>", "Search for job listings"),
            ("/work save [#,#|all]", "Save results by number or all"),
            ("/work list", "Show saved listings"),
            ("/work remove <#>", "Remove a saved listing"),
            ("/work apply <#>", "Open listing + generate cover letter"),
            ("/work track <#> <status>", "Set status (applied, interviewing, etc.)"),
            ("/work status", "Show jobs grouped by status"),
            ("/resume", "Show loaded resume status"),
            ("/resume <path>", "Load a resume file"),
            ("/cover <#>", "Generate cover letter for saved job"),
            ("/cover new <co> <title>", "Cover letter for unlisted job"),
        ],
        "tip": "Load your resume first (/resume path/to/resume.pdf) for better cover letters.",
    },
    "scanning": {
        "desc": "Automated job scanning",
        "commands": [
            ("/scan", "Run a job scan now"),
            ("/scan results", "Show last scan results"),
            ("/scan status", "Show scan config and rate limits"),
            ("/scan query add <q>", "Add a search query"),
            ("/scan query remove <q>", "Remove a search query"),
            ("/scan queries", "List configured queries"),
            ("/scan on|off", "Enable/disable auto-scanning"),
        ],
        "tip": "Configure queries once, then let the daemon scan automatically.",
    },
    "tasks": {
        "desc": "Tasks and reminders",
        "commands": [
            ("/task add <desc>", "Add a task (--high/--low, natural dates)"),
            ("/tasks", "Show open tasks sorted by urgency"),
            ("/tasks all", "Show all tasks including done"),
            ("/task done <#>", "Mark a task as done"),
            ("/task remove <#>", "Remove a task"),
            ("/task edit <#> <desc>", "Edit task description"),
            ("/task note <#> <note>", "Add a note to a task"),
            ("/tasks done", "Show completed tasks"),
            ("/remind <desc> <time>", "Set a reminder"),
            ("/reminders", "Show pending reminders"),
            ("/remind cancel <#>", "Cancel a reminder"),
        ],
        "tip": "Natural dates work: 'tomorrow 3pm', 'next monday', 'in 2 hours'.",
    },
    "web": {
        "desc": "Web search and file tools",
        "commands": [
            ("/web <query>", "Search the web"),
            ("/fetch <url>", "Fetch a web page"),
            ("/read <path>", "Load a file into conversation"),
            ("/write <file>", "Save last response to workspace"),
            ("/run", "Run code from Claude's last response"),
            ("/pdf <title>", "Save last response as formatted PDF"),
        ],
        "tip": "Claude also searches the web autonomously when it would help.",
    },
    "skills": {
        "desc": "Extensible specialist skills",
        "commands": [
            ("/skills", "List all loaded skills"),
            ("/skills reload", "Re-scan skills/ directory"),
        ],
        "tip": "Drop .md files with YAML front matter into skills/ to create custom skills.",
    },
    "system": {
        "desc": "Status, briefing, notifications, projects",
        "commands": [
            ("/status", "Agent status overview"),
            ("/briefing", "Run daily briefing"),
            ("/briefing time HH:MM", "Set auto-briefing time"),
            ("/briefing on|off", "Enable/disable auto-briefing"),
            ("/notify on|off", "Enable/disable email notifications"),
            ("/notify mute add|remove <p>", "Manage mute patterns"),
            ("/notify log", "Show recent notification log"),
            ("/notify domain add|remove <d>", "Priority domain filter"),
            ("/notify keyword add|remove <w>", "Priority keyword filter"),
            ("/project", "Create a new project"),
            ("/project <name>", "Switch to a project"),
            ("/project list", "List all projects"),
            ("/watch <topic>", "Add a topic to the watchlist"),
            ("/watch list", "Show watched topics"),
            ("/digest", "Generate a digest from watched topics"),
            ("/tokens", "Context size and compression status"),
            ("/delegates", "Show specialist agents"),
            ("/billing", "Show billing link"),
            ("/update", "Sync all data"),
            ("/setup", "Run onboarding wizard"),
            ("/reset", "Wipe all data and start fresh"),
            ("/characters", "List creative characters"),
            ("/character <name>", "Show character details"),
            ("/locations", "List creative locations"),
            ("/location <name>", "Show location details"),
        ],
        "tip": "Use /status for a quick overview of everything active.",
    },
}


def fuzzy_match_category(query):
    """Prefix-match a category name. Returns (key, data) or None."""
    query = query.lower().strip()
    if query in HELP_CATEGORIES:
        return query, HELP_CATEGORIES[query]
    matches = [k for k in HELP_CATEGORIES if k.startswith(query)]
    if len(matches) == 1:
        return matches[0], HELP_CATEGORIES[matches[0]]
    return None


# ---------------------------------------------------------------------------
# Terminal formatters (ANSI box-drawing)
# ---------------------------------------------------------------------------

def format_terminal_overview(colors):
    """Format the help overview with ANSI box-drawing.

    colors: dict with keys CYAN, BOLD, DIM, RESET.
    """
    C = colors.get("CYAN", "")
    B = colors.get("BOLD", "")
    D = colors.get("DIM", "")
    R = colors.get("RESET", "")

    max_name = max(len(k) for k in HELP_CATEGORIES)
    width = max(max_name + 4 + max(len(v["desc"]) for v in HELP_CATEGORIES.values()), 40)
    width = min(width, 60)

    lines = []
    lines.append(f"\n{C}\u250c{'\u2500' * (width + 2)}\u2510{R}")
    lines.append(f"{C}\u2502{R} {B}HELP{R}{' ' * (width - 4)} {C}\u2502{R}")
    lines.append(f"{C}\u251c{'\u2500' * (width + 2)}\u2524{R}")
    for name, cat in HELP_CATEGORIES.items():
        line = f"  /help {name:<{max_name}}  {cat['desc']}"
        pad = width + 1 - len(line)
        lines.append(
            f"{C}\u2502{R}{D}  /help {R}{name:<{max_name}}{D}  {cat['desc']}{R}"
            f"{' ' * max(pad, 0)} {C}\u2502{R}"
        )
    lines.append(f"{C}\u251c{'\u2500' * (width + 2)}\u2524{R}")
    footer = "  Type /help <category> for details"
    fpad = width + 1 - len(footer)
    lines.append(f"{C}\u2502{R}{D}{footer}{R}{' ' * max(fpad, 0)} {C}\u2502{R}")
    lines.append(f"{C}\u2514{'\u2500' * (width + 2)}\u2518{R}\n")
    return "\n".join(lines)


def format_terminal_category(name, colors):
    """Format a single category with ANSI box-drawing.

    Returns formatted string, or None if category not found.
    """
    result = fuzzy_match_category(name)
    if not result:
        return None
    key, cat = result

    C = colors.get("CYAN", "")
    B = colors.get("BOLD", "")
    D = colors.get("DIM", "")
    R = colors.get("RESET", "")

    max_cmd = max(len(c[0]) for c in cat["commands"])
    width = max(
        max_cmd + 4 + max(len(c[1]) for c in cat["commands"]),
        len(cat.get("tip", "")) + 4,
        len(key) + 3,
    )
    width = min(width, 72)

    lines = []
    lines.append(f"\n{C}\u250c{'\u2500' * (width + 2)}\u2510{R}")
    lines.append(f"{C}\u2502{R} {B}{key.upper()}{R}{' ' * (width - len(key))} {C}\u2502{R}")
    lines.append(f"{C}\u251c{'\u2500' * (width + 2)}\u2524{R}")
    for cmd, desc in cat["commands"]:
        visible = f"  {cmd:<{max_cmd}}  {desc}"
        pad = width + 1 - len(visible)
        line = f"  {cmd:<{max_cmd}}  {D}{desc}{R}"
        lines.append(f"{C}\u2502{R}{line}{' ' * max(pad, 0)} {C}\u2502{R}")
    if cat.get("tip"):
        lines.append(f"{C}\u251c{'\u2500' * (width + 2)}\u2524{R}")
        tip_line = f"  {cat['tip']}"
        tip_pad = width + 1 - len(tip_line)
        lines.append(f"{C}\u2502{R}{D}{tip_line}{R}{' ' * max(tip_pad, 0)} {C}\u2502{R}")
    lines.append(f"{C}\u2514{'\u2500' * (width + 2)}\u2518{R}\n")
    return "\n".join(lines)


def format_terminal_error(query, colors):
    """Format a 'category not found' error for terminal."""
    R = colors.get("RED", "")
    D = colors.get("DIM", "")
    RS = colors.get("RESET", "")
    return (
        f"{R}Unknown category: {query}{RS}\n"
        f"{D}Available: {', '.join(HELP_CATEGORIES.keys())}{RS}"
    )


# ---------------------------------------------------------------------------
# Discord formatters (markdown with ! prefix)
# ---------------------------------------------------------------------------

def _reprefix(cmd_str, prefix):
    """Replace / prefix with given prefix in a command string."""
    # Handle comma-separated commands like "/opus, /sonnet, /haiku"
    parts = cmd_str.split(", ")
    return ", ".join(
        prefix + p.lstrip("/") if p.startswith("/") else p
        for p in parts
    )


def format_discord_overview():
    """Format the help overview for Discord with markdown."""
    lines = [
        "**Available command categories:**",
        "",
    ]
    for name, cat in HELP_CATEGORIES.items():
        lines.append(f"`!help {name}` \u2014 {cat['desc']}")
    lines.append("")
    lines.append("*Type `!help <category>` for detailed commands.*")
    return "\n".join(lines)


def format_discord_category(name):
    """Format a single category for Discord. Returns string or None."""
    result = fuzzy_match_category(name)
    if not result:
        return None
    key, cat = result

    lines = [f"**{key.upper()}** \u2014 {cat['desc']}", ""]
    for cmd, desc in cat["commands"]:
        dc = _reprefix(cmd, "!")
        lines.append(f"`{dc}` \u2014 {desc}")
    if cat.get("tip"):
        lines.append(f"\n*{cat['tip']}*")
    return "\n".join(lines)


def format_discord_error(query):
    """Format a 'category not found' error for Discord."""
    return (
        f"*Unknown category: {query}*\n"
        f"Available: {', '.join(f'`{k}`' for k in HELP_CATEGORIES)}"
    )


# ---------------------------------------------------------------------------
# Telegram formatters (plain text with / prefix)
# ---------------------------------------------------------------------------

def format_telegram_overview():
    """Format the help overview for Telegram."""
    lines = [
        "Available command categories:",
        "",
    ]
    for name, cat in HELP_CATEGORIES.items():
        lines.append(f"/help {name} \u2014 {cat['desc']}")
    lines.append("")
    lines.append("Type /help <category> for detailed commands.")
    return "\n".join(lines)


def format_telegram_category(name):
    """Format a single category for Telegram. Returns string or None."""
    result = fuzzy_match_category(name)
    if not result:
        return None
    key, cat = result

    lines = [f"{key.upper()} \u2014 {cat['desc']}", ""]
    for cmd, desc in cat["commands"]:
        lines.append(f"{cmd} \u2014 {desc}")
    if cat.get("tip"):
        lines.append(f"\n{cat['tip']}")
    return "\n".join(lines)


def format_telegram_error(query):
    """Format a 'category not found' error for Telegram."""
    return (
        f"Unknown category: {query}\n"
        f"Available: {', '.join(HELP_CATEGORIES.keys())}"
    )


# ---------------------------------------------------------------------------
# GUI formatters (Gradio markdown)
# ---------------------------------------------------------------------------

def format_gui_overview():
    """Format the help overview as Gradio markdown."""
    lines = [
        "### Available Commands",
        "",
        "| Category | Description |",
        "|----------|-------------|",
    ]
    for name, cat in HELP_CATEGORIES.items():
        lines.append(f"| `/help {name}` | {cat['desc']} |")
    lines.append("")
    lines.append("Type `/help <category>` for detailed commands.")
    return "\n".join(lines)


def format_gui_category(name):
    """Format a single category as Gradio markdown. Returns string or None."""
    result = fuzzy_match_category(name)
    if not result:
        return None
    key, cat = result

    lines = [
        f"### {key.upper()} \u2014 {cat['desc']}",
        "",
        "| Command | Description |",
        "|---------|-------------|",
    ]
    for cmd, desc in cat["commands"]:
        lines.append(f"| `{cmd}` | {desc} |")
    if cat.get("tip"):
        lines.append(f"\n*{cat['tip']}*")
    return "\n".join(lines)


def format_gui_error(query):
    """Format a 'category not found' error for GUI."""
    return (
        f"Unknown category: `{query}`\n\n"
        f"Available: {', '.join(f'`{k}`' for k in HELP_CATEGORIES)}"
    )
