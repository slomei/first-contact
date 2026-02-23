# CLAUDE.md — First Contact Project Context

*Last updated: February 22, 2026*

---

## Project Overview

First Contact is a personal AI agent built from scratch with the Anthropic API. It connects to Gmail, Google Calendar, job boards, and the web through natural conversation. Five interfaces (terminal, web UI, Gradio GUI, Discord, Telegram) share a single core. Everything runs locally. Security-first: draft-only email, sandboxed files, untrusted web isolation, human-in-the-loop for writes.

**Status:** Pre-ship. All 150 tests passing. Ready for GitHub.

---

## File Map

### Interfaces (thin I/O adapters)

| File | Description |
|------|-------------|
| `chat.py` | Terminal chatbot — primary interface. Streaming output, markdown stripping, session cost tracking, startup diagnostics. |
| `web_ui/` | WebSocket-based web frontend (server.py + vanilla HTML/CSS/JS). Per-connection state, streaming responses, tool loop, token tracking. Designed as Tauri desktop app foundation. |
| `gui.py` | Web GUI via Gradio. Returns markdown strings from command handlers. |
| `discord_bot.py` | Discord bot (prefix: `!fc`). Background loops for reminders, email, briefing, scans. Async with typing indicators. |
| `telegram_bot.py` | Telegram bot. Same command set as Discord, adapted for Telegram's API. |
| `interfaces/` | Base adapter pattern for new interfaces. `InterfaceAdapter` ABC in `base_adapter.py`, example implementation, README. Existing interfaces predate this and work independently. |

### Shared Core

| File | Description |
|------|-------------|
| `memory.py` | Persistent memory (global + per-project), semantic search via sentence-transformers, system prompt builder, project switching, cross-project awareness, user profile, config I/O. |
| `models.py` | Model routing (Haiku/Sonnet/Opus), API calls, token tracking, pricing, context compression (Haiku-summarized at 20K tokens), specialist delegation (researcher/writer/coder/analyst). |
| `tools.py` | 18 tool definitions (`TOOLS` list) and `execute_tool()` dispatch. Gmail, Calendar, web search, file I/O, code execution, job search, notes, tasks, reminders, PDF generation. |
| `tasks.py` | Task system (add/edit/done/remove, priority levels, due dates) and reminder system (natural language date parsing via dateutil). Stored per-project in `tasks.json`, reminders global in `reminders.json`. |
| `documents.py` | PDF generation via reportlab. Cover letters with auto-fit-to-one-page (progressive margin/font reduction, Opus shortening as last resort). Generic PDF generation. Falls back to plain text if reportlab not installed. |
| `briefing.py` | Daily briefing aggregation — 7 data sources: email, calendar, tasks, jobs, reminders, watchlist, scan results. Formats for Discord, Telegram, and terminal. |
| `notifications.py` | Email classification (high/medium/low priority by sender domain + keywords), rate limiting (20/hour), seen-message dedup (7-day prune), audit logging, Discord/Telegram/email formatters. |
| `job_scanner.py` | Proactive job scanning — multi-platform DuckDuckGo search, Haiku fit assessment against user profile, dedup via seen_jobs.json, rate limiting (3 manual scans/day). Batch API for >=5 jobs (50% cost). |
| `batch_api.py` | Batch API wrapper — submit, poll, retrieve for Anthropic Messages Batches endpoint. Used by job_scanner for fit assessments at 50% cost. |
| `daemon.py` | Background scheduler — daily briefings, email checks (30 min), job scans (12 hr), reminder checks (5 min). PID management, graceful SIGTERM/SIGINT, notification routing. Runs detached or foreground. |
| `onboarding.py` | 20-step interactive setup wizard. Covers profile, communication style, integrations (Discord, Telegram, Gmail, Calendar), notification preferences, and Haiku-driven personality calibration. Works across all interfaces. |
| `help_data.py` | Single source of truth for all help text. `HELP_CATEGORIES` dict with per-interface formatters (terminal ANSI box-drawing, Discord markdown, Telegram plain text, GUI Gradio markdown). Fuzzy prefix matching. |
| `creative.py` | Creative project tools — world bible PDF parsing via pdfplumber, character/location JSON lookup. Used for the First Light screenplay project. |
| `skills_loader.py` | Extensible skills system — loads `.md` skill files from `skills/` directory, keyword matching, injects matched skill content into specialist system prompts during delegation. |
| `files.py` | Project file management — import, list, remove files. Validation, large-file detection, conversation injection formatting. Used by all interfaces and web UI drag-and-drop. |
| `sync.py` | File sync system — reads `sync_sources.json` for source/destination mappings, glob-scans Windows paths, resolves version conflicts, copies latest file. |

### Tests

| File | Description |
|------|-------------|
| `tests/conftest.py` | Pytest fixtures — isolated temp dirs, test config, monkeypatched paths. |
| `tests/test_imports.py` | Smoke tests — all 14 core modules import without errors. |
| `tests/test_memory.py` | Memory system — config, profiles, memories, semantic search, cross-project, system prompt. |
| `tests/test_models.py` | Model routing — MODELS dict, pricing, short names, token estimation, usage tracking. |
| `tests/test_tools.py` | Tool system — TOOLS list, required fields, status text, file sandboxing. |
| `tests/test_tasks.py` | Tasks — add/roundtrip, natural date parsing. |
| `tests/test_onboarding.py` | Onboarding — calibration flow, step ordering, error handling. |
| `tests/test_help_data.py` | Help system — categories, fuzzy matching, all 4 interface formatters. |
| `tests/test_notes_status.py` | Notes, reminders, draft rate limits, daemon PID, config loading. |
| `tests/test_skills.py` | Skills system — skill loading, keyword matching, specialist prompt injection. |
| `tests/test_files.py` | File management — extension validation, import/list/remove, large file detection, path resolution. |
| `tests/test_batch_api.py` | Batch API — module loads, functions exist. |

### Config & Data Files

| File | Description |
|------|-------------|
| `.env` / `.env.example` | API keys: `ANTHROPIC_API_KEY` (required), `DISCORD_BOT_TOKEN`, `DISCORD_USER_ID`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_USER_ID` (all optional). |
| `config.json` / `config.example.json` | Generated by onboarding. Briefing schedule, email notification prefs, job scan queries, user profile, daemon settings. |
| `memory.json` | Global persistent memory store (objects with `text`, `embedding`, `created`). |
| `reminders.json` | Global reminders (cross-project). |
| `sync_sources.json` | File sync source/destination mappings. |
| `requirements.txt` | Python dependencies. `sentence-transformers` is commented out (optional). |
| `setup.sh` | Setup script — creates venv, installs deps, copies config templates. |

### Directory Structure

```
first-contact/
├── conversations/          # Top-level conversation logs
├── workspace/              # Scratch files
├── logs/                   # draft_audit.log, notifications.log, scan.log, seen_emails.json
├── projects/
│   ├── general/            # Default project
│   │   ├── conversations/
│   │   ├── tasks.json
│   │   ├── files/              # Imported project files (persistent context)
│   │   └── workspace/
│   │       ├── cover_letters/
│   │       └── jobs/       # Per-listing dirs (listing.json, notes.md, cover-letter.md)
│   └── {project-name}/    # Each project gets its own dir
│       ├── memory.json     # Project-specific memories
│       ├── tasks.json
│       ├── files/              # Per-project imported files
│       ├── conversations/
│       └── workspace/
├── interfaces/
│   ├── __init__.py         # Exports InterfaceAdapter
│   ├── base_adapter.py     # Abstract base class for new interfaces
│   ├── example_adapter.py  # Commented reference implementation
│   └── README.md           # How to build a new interface
├── web_ui/
│   ├── server.py           # WebSocket server (thin adapter)
│   ├── index.html           # Entry point
│   ├── app.js              # Client logic (WebSocket, rendering)
│   ├── styles.css          # Styling (CSS custom properties)
│   └── README.md           # Architecture & Tauri integration guide
├── skills/                 # Specialist skill files (.md with YAML front matter)
├── tests/
└── venv/
```

---

## Architecture

### Model Routing

| Model | ID | Used For |
|-------|----|----------|
| Haiku | `claude-haiku-4-5` | Research, summaries, conversation titles, briefings, fit assessment, context compression |
| Sonnet | `claude-sonnet-4-6` | Routing decisions, coding, general conversation, director model |
| Opus | `claude-opus-4-6` | Cover letters, deep analysis, creative writing (always used for cover letters regardless of active model) |

### Specialist Delegation

The director (Sonnet) can route messages to specialist agents:
- **researcher** (Haiku) — web research and summarization
- **writer** (Opus) — creative writing, cover letters, polished prose
- **coder** (Sonnet) — code generation and debugging
- **analyst** (Sonnet) — problem analysis, finding flaws, critical thinking

### Extensible Skills

Specialists can be augmented with skills — `.md` files in the `skills/` directory with YAML front matter defining `name`, `description`, `specialist`, `model_preference`, and `trigger_keywords`. When a message is delegated, `skills_loader.match_skill()` finds the best keyword match and prepends the skill content to the specialist's system prompt. Ships with 5 built-in skills (cover_letter, research, code_review, email_draft, job_analysis). Users can add custom skills by dropping `.md` files into `skills/`.

### 18 Integrated Tools

`web_search`, `read_file`, `write_file`, `remember`, `forget`, `list_memories`, `save_note`, `run_python`, `job_search`, `check_email`, `read_email`, `search_email`, `create_task`, `create_reminder`, `web_fetch`, `generate_pdf`, `get_calendar_events`, `create_calendar_event`

### Memory System

- **Storage:** `memory.json` (global) + `projects/{name}/memory.json` (per-project)
- **Format:** Objects with `text`, `embedding` (384-dim vector or null), `created` timestamp
- **Semantic search:** `sentence-transformers` (`all-MiniLM-L6-v2`) for meaning-based retrieval. Top 15 injected into system prompt.
- **Fallback:** Without sentence-transformers, all memories loaded (Claude filters by relevance)
- **Cross-project:** Scans all project dirs and injects summaries into system prompt

### Context Compression

- Triggers at 20,000 estimated tokens
- Keeps first 3 + last 5 exchanges; Haiku summarizes removed middle sections
- Context indicator every 10 messages shows % used and compression count
- `models.session_compressions` counter displayed in `/status`

### Multi-Email Account Support

- Config stores `email_accounts` array with label + credentials file per account
- Email check/search operations iterate across all accounts
- Legacy single-account setup supported as fallback
- OAuth2 per account, separate credential files

### System Prompt Behaviors

The system prompt (`memory.py`) includes three behavioral directives built from actual usage patterns:

- **Calibrated honesty** — Evaluate work accurately. Praise when earned, critique when warranted. Never default to enthusiasm, sugarcoat bad news, or inflate quality to be supportive.
- **Act-don't-ask** — When the user asks to do something, do it immediately. Don't ask for confirmation, optional fields, or clarifying questions unless the request is truly ambiguous. Programmatic confirmation gates (calendar events, file overwrites) handle their own confirmation — the agent doesn't add a second layer.
- **Self-knowledge** — Dynamic section describing First Contact's own identity, capabilities, tool count, skill count, and architecture. Rebuilt each turn so the agent can accurately answer "what are you?" questions.

### Timezone Handling

- `memory.get_timezone()` reads `config.briefing.timezone`, defaults to `America/New_York`
- `memory.local_now()` returns timezone-aware datetime — all modules use this instead of bare `datetime.now()`
- System prompt includes dynamic date/time in the user's local timezone
- All user-facing timestamps (notes, tasks, reminders, briefings) use `local_now()`

### Security Architecture

1. Draft-only email — Gmail `compose` scope, not `send`
2. Calendar: create only — no delete, no modify
3. Web content isolation — untrusted markers, no tool execution from fetched content
4. File sandbox — `read_file` restricted to project directory, no dotfiles, no system paths
5. Credential lockdown — `.env` + `chmod 600` on tokens
6. Rate limits — 10 drafts/session, 10 fetches/session, 20 notifications/hour, 3 scans/day
7. Human-in-the-loop — confirmation required for calendar events, file overwrites
8. User-gated messaging — Discord/Telegram bots respond only to configured user ID
9. Anti-injection on drafts — external email content marked as untrusted data

---

## All Commands

**Chat:** `/opus`, `/sonnet`, `/haiku`, `/challenge on|off`, `/new`, `/load`, `/conversations`, `/delete`, `/clear`

**Memory & Notes:** `/remember [-p] <fact>`, `/forget <fact>`, `/memories`, `/memories search <q>`, `/note <text>`, `/notes`, `/notes search <q>`

**Email & Drafts:** `/email setup`, `/email check`, `/email read <#>`, `/email search <q>`, `/draft reply`, `/draft new <to> [subject]`, `/draft work <#>`, `/drafts`

**Calendar:** `/cal [today|tomorrow|week|<date>]`, `/cal add <desc>`, `/cal setup`

**Jobs:** `/work search <q>`, `/work save [#,#|all]`, `/work list`, `/work remove <#>`, `/work apply <#>`, `/work track <# status>`, `/work status`, `/resume [path]`, `/cover <#>`, `/cover new <company> <title>`

**Scanning:** `/scan`, `/scan results`, `/scan status`, `/scan query add|remove <q>`, `/scan queries`, `/scan on|off`

**Tasks & Reminders:** `/task add <desc> [--high|--low]`, `/task done <#>`, `/task remove <#>`, `/task edit <# desc>`, `/task note <# note>`, `/tasks [done|all]`, `/remind <desc> <time>`, `/remind cancel <#>`, `/reminders`

**Briefing & Notifications:** `/briefing`, `/briefing time HH:MM`, `/briefing on|off`, `/notify on|off`, `/notify domain add|remove <d>`, `/notify keyword add|remove <w>`, `/notify mute add|remove <p>`, `/notify log`

**Web & Files:** `/web <query>`, `/fetch <url>`, `/read <path>`, `/write <file>`, `/run`, `/pdf <title>`

**Project Files:** `/file <path>`, `/files`, `/file remove <name>`, `/file clear`

**Projects:** `/project [name|list]`

**Watchlist:** `/watch <topic>`, `/watch list`, `/watch remove <topic>`, `/digest`

**System:** `/help [category]`, `/status`, `/tokens`, `/billing`, `/delegates`, `/skills`, `/skills reload`, `/setup`, `/update`, `/reset`

**Creative:** `/characters`, `/character <name>`, `/locations`, `/location <name>`

---

## Developer Notes

- **Tested on:** Python 3.10+ on Linux (Ubuntu/WSL2) and macOS
- **GPU optional:** Semantic search works on CPU; auto-detects CUDA if available
- **Browser opening (WSL):** Uses `wslview` if configured

## Communication Style

The system prompt enforces these behaviors (see System Prompt Behaviors above):
- Be direct. No hedging, no sycophancy, no unearned praise
- If an idea is bad, say so and explain why
- If something is wrong, say so
- Don't over-explain things the user already understands
- Match the energy of the conversation — brief when they're brief, deep when they want depth
- Honest critique over validation
- Explain the *why* behind commands and syntax, not just copy-paste
- Cost-conscious on API usage — avoid unnecessary API calls

## Interface Behavior Details

**Terminal (`chat.py`):**
- Prompt format: `You [model/project/challenge]: `
- `_TerminalStreamer` strips `**bold**`, `*italic*`, `` `code` ``, `# headers` from output while preserving raw response in conversation history; code blocks preserved
- Welcome-back message if >7 days since last session
- Startup shows memory count, active applications, daemon status, due reminders, open tasks
- Session cost per-turn and cumulative; summary on exit
- Graceful exit: `/quit`, `/exit`, `quit`, `exit`, Ctrl+C, EOF

**Web UI (`web_ui/`):**
- WebSocket server on `ws://localhost:8765` (configurable port)
- Per-connection isolation — each browser tab gets its own conversation history, model, and token counters
- Vanilla HTML/CSS/JS frontend — no framework, no build step
- Streaming responses, tool status indicators, model switching, accent color picker
- Designed as foundation for eventual Tauri desktop app
- `confirm_fn=None` (auto-approve, same as gui.py/discord)

**Discord (`discord_bot.py`):**
- Background loop intervals: reminders (60s), email checks (5min), daily briefing (configurable), job scan (Mon-Fri)
- Notification priority: high = immediate DM, medium = batched every 30min, low = silent

**Onboarding:**
- Generates `Claude.md` (personal context), updated `config.json`, `setup_env.sh` (chmod 600)

---

## Coding Conventions

- **Python 3.10+**, no enforced type hints
- **Optional dependencies** are wrapped in try/except at import time with None sentinels and guards at usage sites. Never crash on a missing optional package.
- **Lazy imports** to avoid circular dependencies: `tools.py` imports `models` inside functions, `notifications.py` imports `tools` inside `check_new_emails()`.
- **Dict access on external data** uses `.get()` with defaults. Direct `dict["key"]` only for internal data with known structure.
- **File I/O**: Always `os.makedirs(exist_ok=True)` before writing. Check `os.path.exists()` before reading. JSON loads wrapped in try/except.
- **Errors** produce helpful messages, not tracebacks.
- **Interfaces are thin**: All business logic in shared core modules. Interface files handle only I/O adaptation.
- **Tests**: pytest with monkeypatched paths (isolated temp dirs). 150 tests across 11 test files.

---

## Known Stretch Goals

- **MCP (Model Context Protocol)** — expose tools as MCP servers
- **Provider abstraction** — support OpenAI, Gemini, local models alongside Anthropic
- **Tauri desktop app** — native desktop wrapper
- **Mobile app** — iOS/Android interface
- **Plugin system** — user-installable tool packages
- **Docker** — containerized deployment
- **LinkedIn monitoring** — job board integration
- **Voice input/output** — local Whisper on GPU
- **Portfolio tracking** — local CSV exports
- **GitHub portfolio cleanup** — sanitize agent code, publish as portfolio piece

---

*This file is read by Claude Code on startup. Keep it accurate and up to date.*
