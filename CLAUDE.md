# CLAUDE.md — First Contact Project Context

*Last updated: February 21, 2026*

---

## Project Overview

First Contact is a personal AI agent built from scratch with the Anthropic API. It connects to Gmail, Google Calendar, job boards, and the web through natural conversation. Four interfaces (terminal, web GUI, Discord, Telegram) share a single core. Everything runs locally. Security-first: draft-only email, sandboxed files, untrusted web isolation, human-in-the-loop for writes.

**Status:** Pre-ship. All 104 tests passing. Ready for GitHub.

---

## File Map

### Interfaces (thin I/O adapters)

| File | Description |
|------|-------------|
| `chat.py` | Terminal chatbot — primary interface. Streaming output, markdown stripping, session cost tracking, startup diagnostics. |
| `gui.py` | Web GUI via Gradio. Returns markdown strings from command handlers. |
| `discord_bot.py` | Discord bot (prefix: `!fc`). Background loops for reminders, email, briefing, scans. Async with typing indicators. |
| `telegram_bot.py` | Telegram bot. Same command set as Discord, adapted for Telegram's API. |

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
| `job_scanner.py` | Proactive job scanning — multi-platform DuckDuckGo search, Haiku fit assessment against user profile, dedup via seen_jobs.json, rate limiting (3 manual scans/day). |
| `daemon.py` | Background scheduler — daily briefings, email checks (30 min), job scans (12 hr), reminder checks (5 min). PID management, graceful SIGTERM/SIGINT, notification routing. Runs detached or foreground. |
| `onboarding.py` | 20-step interactive setup wizard. Covers profile, communication style, integrations (Discord, Telegram, Gmail, Calendar), notification preferences, and Haiku-driven personality calibration. Works across all interfaces. |
| `help_data.py` | Single source of truth for all help text. `HELP_CATEGORIES` dict with per-interface formatters (terminal ANSI box-drawing, Discord markdown, Telegram plain text, GUI Gradio markdown). Fuzzy prefix matching. |
| `creative.py` | Creative project tools — world bible PDF parsing via pdfplumber, character/location JSON lookup. Used for the First Light screenplay project. |
| `sync.py` | File sync system — reads `sync_sources.json` for source/destination mappings, glob-scans Windows paths, resolves version conflicts, copies latest file. |

### Tests

| File | Description |
|------|-------------|
| `tests/conftest.py` | Pytest fixtures — isolated temp dirs, test config, monkeypatched paths. |
| `tests/test_imports.py` | Smoke tests — all 13 core modules import without errors. |
| `tests/test_memory.py` | Memory system — config, profiles, memories, semantic search, cross-project, system prompt. |
| `tests/test_models.py` | Model routing — MODELS dict, pricing, short names, token estimation, usage tracking. |
| `tests/test_tools.py` | Tool system — TOOLS list, required fields, status text, file sandboxing. |
| `tests/test_tasks.py` | Tasks — add/roundtrip, natural date parsing. |
| `tests/test_onboarding.py` | Onboarding — calibration flow, step ordering, error handling. |
| `tests/test_help_data.py` | Help system — categories, fuzzy matching, all 4 interface formatters. |
| `tests/test_notes_status.py` | Notes, reminders, draft rate limits, daemon PID, config loading. |

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
│   │   └── workspace/
│   │       ├── cover_letters/
│   │       └── jobs/       # Per-listing dirs (listing.json, notes.md, cover-letter.md)
│   └── {project-name}/    # Each project gets its own dir
│       ├── memory.json     # Project-specific memories
│       ├── tasks.json
│       ├── conversations/
│       └── workspace/
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

**Projects:** `/project [name|list]`

**Watchlist:** `/watch <topic>`, `/watch list`, `/watch remove <topic>`, `/digest`

**System:** `/help [category]`, `/status`, `/tokens`, `/billing`, `/delegates`, `/setup`, `/update`, `/reset`

**Creative:** `/characters`, `/character <name>`, `/locations`, `/location <name>`

---

## Developer Environment

- **Platform:** Windows + WSL2 (Ubuntu)
- **Shell:** zsh with oh-my-zsh, zsh-autosuggestions, zsh-syntax-highlighting
- **GPU:** RTX 4090 (64GB RAM, primary), RTX 5070 Ti (32GB RAM, secondary)
- **Local AI:** LTX-2 + ComfyUI (video generation), Ollama + local models (GLM-5, Llama 3.2)
- **Subscription:** Claude Max
- **Browser opening:** wslview configured for WSL → Windows

## Communication Style

When working with the project owner:
- Be direct. No hedging, no sycophancy, no praise to make him feel good
- If an idea is bad, say so and explain why
- If something built is wrong, tell him
- Don't over-explain things he already understands
- Match his energy — if he's brief, be brief
- He asks for honest critique, not validation
- He likes understanding the *why* behind commands and syntax, not just copy-paste
- Cost-conscious on API usage — avoid unnecessary API calls
- He works nights. Late sessions are normal

## Interface Behavior Details

**Terminal (`chat.py`):**
- Prompt format: `You [model/project/challenge]: `
- `_TerminalStreamer` strips `**bold**`, `*italic*`, `` `code` ``, `# headers` from output while preserving raw response in conversation history; code blocks preserved
- Welcome-back message if >7 days since last session
- Startup shows memory count, active applications, daemon status, due reminders, open tasks
- Session cost per-turn and cumulative; summary on exit
- Graceful exit: `/quit`, `/exit`, `quit`, `exit`, Ctrl+C, EOF

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
- **Tests**: pytest with monkeypatched paths (isolated temp dirs). 104 tests across 8 test files.

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
