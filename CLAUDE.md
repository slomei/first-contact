# CLAUDE.md — First Contact Project Context

*Last updated: March 9, 2026*

*Detailed interface behavior, provider tables, prompt caching internals, and safety model: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)*

---

## Project Overview

First Contact is a personal AI agent built from scratch with the Anthropic API. It connects to Gmail, Google Calendar, job boards, and the web through natural conversation. Four interfaces (terminal, web UI, Discord, Telegram) share a single core. Everything runs locally. Security-first: draft-only email, sandboxed files, untrusted web isolation, human-in-the-loop for writes.

**Status:** Shipped. All 467 tests passing. Live on GitHub.

---

## File Map

### Interfaces (thin I/O adapters)

| File | Description |
|------|-------------|
| `chat.py` | Terminal chatbot — primary interface. Streaming output, markdown stripping, session cost tracking, startup diagnostics, `/attach` for temporary file injection. |
| `web_ui/` | WebSocket-based web frontend (server.py + vanilla HTML/CSS/JS). Per-connection state, streaming responses, tool loop, token tracking, context compression, conversation persistence, `/prompt` command, project switching (`set_project`), chat-input temporary attachments (drag-drop + paperclip queue as chips, sent with next message), sidebar persistent file upload and delete, binary file upload support (PDF/DOCX/XLSX), server-synced sidebar file list (shows both `files/` and `workspace/` contents). Designed as Tauri desktop app foundation. |
| `discord_bot.py` | Discord bot (prefix: `!fc`). Background loops for reminders, email, briefing, scans. Async with typing indicators. File attachment handling (temporary chat injection). |
| `telegram_bot.py` | Telegram bot. Same command set as Discord, adapted for Telegram's API. Document attachment handling (temporary chat injection). |
| `interfaces/` | Interface adapter pattern. `InterfaceAdapter` ABC in `base_adapter.py`, adapters for all 4 interfaces (terminal, discord, telegram, web), example implementation, README. |

### Shared Core

| File | Description |
|------|-------------|
| `conversation.py` | Shared conversation turn loop used by all 4 interfaces. `run_conversation_turn()` handles the API call -> tool use -> loop pattern with callbacks for streaming, tool status, and confirmation. `extract_last_user_query()` for semantic retrieval. Always uses prompt caching. |
| `memory.py` | Persistent memory (global + per-project), semantic search via sentence-transformers, system prompt builder (stable/dynamic split for prompt caching), project switching, cross-project awareness, user profile, config I/O. |
| `models.py` | Model routing (Haiku/Sonnet/Opus), API calls, token tracking, pricing, context compression (fast-tier summarized at 20K tokens), specialist delegation (researcher/writer/coder/analyst). Provider dispatch via `_get_provider()` — all model IDs use tier lookups (`fast`/`standard`/`quality`). |
| `providers/` | Provider abstraction — `__init__.py` (ABC, registry, factory), `compat.py` (Anthropic-compatible wrapper types), `anthropic_provider.py` (zero-overhead pass-through), `openai_provider.py` (OpenAI SDK wrapper), `gemini_provider.py` (Google GenAI wrapper). |
| `tools.py` | 28 core tool definitions (`TOOLS` list) and `execute_tool()` dispatch. Gmail, Calendar, web search, file I/O, code execution, job search, notes, tasks, reminders, PDF generation, DOCX/XLSX creation, attachment saving. Unknown tool names fall through to plugins; plugin execution errors surface the error type to the user (never silently swallowed). `get_cached_tools()` merges core + plugin tools with `cache_control` on the last tool. `_rebuild_cached_tools()` refreshes after plugin reload, logs to stderr on failure. |
| `tasks.py` | Task system (add/edit/done/remove, priority levels, due dates) and reminder system (natural language date parsing via dateutil). Stored per-project in `tasks.json`, reminders global in `reminders.json`. |
| `documents.py` | PDF generation via reportlab, Word document (.docx) creation via python-docx, and spreadsheet (.xlsx) creation via openpyxl. Cover letters with auto-fit-to-one-page (progressive margin/font reduction, Opus shortening as last resort). Generic PDF generation. Falls back to plain text/CSV if optional deps not installed. |
| `briefing.py` | Daily briefing aggregation — 7 data sources: email, calendar, tasks, jobs, reminders, watchlist, scan results. Formats for Discord, Telegram, and terminal. |
| `notifications.py` | Email classification (high/medium/low priority by sender domain + keywords), rate limiting (20/hour), seen-message dedup (7-day prune), audit logging, Discord/Telegram/email formatters. |
| `insights.py` | Proactive insights engine — cross-references tasks, email, calendar, jobs, reminders via Sonnet to surface actionable connections. 6 data-gathering functions, minimum-source gate (≥2), NO_INSIGHTS parsing. Daemon-only (every 6 hours). |
| `user_model.py` | Persistent user model — learns facts, preferences, patterns, goals from conversations. Post-conversation extraction (Haiku, fire-and-forget background thread), daemon pattern detection (Sonnet, 24hr). Stored in `user_profile.json`. Two-tier prompt injection: tier 1 (preferences, high-confidence facts, goals) in stable/cached block, tier 2 (patterns, lower-confidence facts) filtered by keyword relevance in dynamic block. `/profile` command on all interfaces. |
| `job_scanner.py` | Proactive job scanning — multi-platform search via search provider abstraction, Haiku fit assessment against user profile, dedup via seen_jobs.json, rate limiting (3 manual scans/day). Batch API for >=5 jobs (50% cost). |
| `batch_api.py` | Batch API wrapper — submit, poll, retrieve for Anthropic Messages Batches endpoint. Used by job_scanner for fit assessments at 50% cost. |
| `daemon.py` | Single entry point for all services. Spawns and supervises web_ui, discord, and telegram as subprocesses (auto-restart on crash). Also runs scheduled tasks: daily briefings, email checks (30 min), job scans (12 hr), reminder checks (5 min), insights analysis (6 hr), user model pattern detection (24 hr). PID management, graceful SIGTERM/SIGINT, notification routing. Hot reload via watchdog (opt-in, `--hot-reload` or `config.hot_reload`). Configurable via `auto_start_*` keys. |
| `onboarding.py` | 21-step interactive setup wizard. Covers profile, communication style, integrations (Discord, Telegram, Gmail, Calendar, search provider), notification preferences, and Haiku-driven personality calibration. Works across all interfaces. `get_suggested_workflows()` returns config-aware suggestions for post-onboarding guidance. |
| `help_data.py` | Single source of truth for all help text. `HELP_CATEGORIES` dict with per-interface formatters (terminal ANSI box-drawing, Discord markdown, Telegram plain text). Fuzzy prefix matching. |
| `creative.py` | Creative project tools — world bible PDF parsing via pdfplumber, character/location JSON lookup. Used for the First Light screenplay project. |
| `skills_loader.py` | Extensible skills system — loads `.md` skill files from `skills/` directory, keyword matching, default base skills per specialist, injects matched skill content into specialist system prompts during delegation. |
| `files.py` | Project file management — import, list, remove files. Validation, large-file detection, conversation injection formatting. `extract_file_for_chat()` for temporary attachment injection, `write_binary_file_contents()` for binary uploads. Image support: `is_image_file()`, `encode_image_for_api()` for multimodal content blocks (PNG, JPG, JPEG, GIF, WebP). Binary attachment preservation: `_temp_attachments` dict, `store_temp_attachment()`, `save_temp_attachment()`, `cleanup_temp_attachments()` — keeps original binary files available for `save_attachment` tool during the session. Used by all interfaces and web UI drag-and-drop. Binary documents (PDF, DOCX, XLSX) routed through `parsers.py`. |
| `parsers.py` | Binary document text extraction — PDF (pdfplumber), DOCX (python-docx), XLSX (openpyxl). Optional deps with clear error messages. Used by `files.py` and `tools.py` read_file. |
| `plugin_generator.py` | Plugin template generator — scaffolds new plugins with correct directory structure, metadata (`plugin.json`), stub tools, and documentation. CLI via argparse, also importable. Validates names, prevents overwrites. |
| `plugins/` | Plugin system — `__init__.py` loader discovers `.py` files and packages (directories with `__init__.py`), validates required attributes (`PLUGIN_NAME`, `TOOLS`, `execute`), routes tool calls. `example_plugin.py` reference implementation (dice roller). `DIRECTORY.md` community plugin registry. `README.md` for plugin authors. |
| `search_providers/` | Search provider abstraction — `__init__.py` (ABC, registry, factory), `duckduckgo_provider.py` (default, no key), `brave_provider.py` (free tier, recommended), `tavily_provider.py` (free, built for AI), `google_provider.py` (best quality), `serpapi_provider.py` (paid). Config: `"search_provider"` in config.json. |
| `service_registry.py` | Centralized integration status — registers check functions for 6 built-in services (Discord, Telegram, Gmail, Calendar, web search, job search), caches status (unconfigured/configured/healthy/error), `check_all()` / `is_available()` API. |
| `mcp_server.py` | MCP (Model Context Protocol) server over stdio transport. Exposes core + plugin tools to external clients (Claude Desktop, Cursor). Tool translation (`input_schema` → `inputSchema`), configurable blacklist, async bridge to `execute_tool()`. Optional dep (`mcp` package). |
| `sync.py` | File sync system — reads `sync_sources.json` for source/destination mappings, glob-scans Windows paths, resolves version conflicts, copies latest file. |

### Tests

| File | Description |
|------|-------------|
| `tests/conftest.py` | Pytest fixtures — isolated temp dirs, test config, monkeypatched paths. |
| `tests/test_imports.py` | Smoke tests — all core modules (including providers) import without errors. |
| `tests/test_conversation.py` | Conversation turn loop — non-streaming, streaming, tool loops, multi-turn, max turns, caching, cost calculation, confirm passthrough, KeyboardInterrupt handling. |
| `tests/test_memory.py` | Memory system — config, profiles, memories, semantic search, cross-project, system prompt, custom prompt, cached prompt blocks. |
| `tests/test_models.py` | Model routing — MODELS dict, pricing, short names, token estimation, usage tracking, cache tokens, batch discount. |
| `tests/test_tools.py` | Tool system — TOOLS list, required fields, status text, file sandboxing, description conciseness, cached tools. |
| `tests/test_tasks.py` | Tasks — add/roundtrip, natural date parsing. |
| `tests/test_onboarding.py` | Onboarding — calibration flow, step ordering, error handling, suggested workflows. |
| `tests/test_help_data.py` | Help system — categories, fuzzy matching, all 3 interface formatters. |
| `tests/test_notes_status.py` | Notes, reminders, draft rate limits, daemon PID, config loading, conversation clearing. |
| `tests/test_skills.py` | Skills system — skill loading, keyword matching, default skills, specialist prompt injection. |
| `tests/test_files.py` | File management — extension validation, import/list/remove, large file detection, path resolution, binary document parsing (PDF/DOCX/XLSX), image file detection and encoding. |
| `tests/test_daemon_caching.py` | Daemon caching — prompt caching in job scanner, briefing watchlist, digest; track_usage cache token accounting. |
| `tests/test_batch_api.py` | Batch API — module loads, functions exist. |
| `tests/test_adapters.py` | Interface adapters — subclass validation, interface names, formatting support, confirm defaults. |
| `tests/test_service_registry.py` | Service registry — built-in registration, status checks for all 6 services, is_available, custom registration, error handling. |
| `tests/test_plugins.py` | Plugin system — discovery, invalid plugin handling, tool merging, execution routing, read-only sandboxing, reload. |
| `tests/test_providers.py` | Provider abstraction — ABC compliance, registry, compat types, OpenAI translation, tier system, config overrides, feature flags, cache multipliers. |
| `tests/test_task_tools.py` | Task/reminder tools — list/complete/edit/remove/note tasks, list/cancel reminders, daemon-agent data parity. |
| `tests/test_hot_reload.py` | Hot reload — file filtering, excluded dirs, debounce, file-to-subprocess mapping, daemon self-change detection. |
| `tests/test_mcp_server.py` | MCP server — config merging, tool listing/blacklist, call routing, error handling, async bridge. |
| `tests/test_plugin_generator.py` | Plugin generator — name validation, directory scaffolding, tool count, overwrite protection, importability, metadata. |
| `tests/test_search_providers.py` | Search providers — ABC compliance, registry/factory, config selection, all 5 provider request/response format, missing key errors. |
| `tests/test_insights.py` | Insights engine — source gathering, minimum-source gate, model tier, system prompt, response parsing (NO_INSIGHTS + insight text), error handling. |
| `tests/test_documents.py` | Document creation — DOCX (paragraphs, headings, fallback), XLSX (data rows, headers, column widths, fallback), tool dispatch for both. |
| `tests/test_chat_attachments.py` | Chat attachments — web UI extension validation, server-side binary/text extraction, Discord/Telegram injection format, terminal `/attach` command, temp file cleanup, image attachment multimodal format, Telegram photo handler, read_file image support. |
| `tests/test_user_model.py` | User model — storage (add/remove/clear/roundtrip), extraction (parse response, NOTHING_NEW, skip short, config disable), format (category grouping, empty), pattern detection (returns tuple, config disable), dedup/prune (merge duplicates, enforce cap), relevance scoring (keyword overlap, empty inputs), tiered injection (stable tier 1, contextual tier 2, high-confidence always included, selective config toggle). |

### Config & Data Files

| File | Description |
|------|-------------|
| `.env` / `.env.example` | API keys: `ANTHROPIC_API_KEY` (required), `DISCORD_BOT_TOKEN`, `DISCORD_USER_ID`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_USER_ID`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `BRAVE_SEARCH_API_KEY`, `GOOGLE_SEARCH_API_KEY`, `GOOGLE_SEARCH_CX`, `SERPAPI_KEY` (all optional). |
| `config.json` / `config.example.json` | Generated by onboarding. Provider selection (`"provider"`), model tier overrides (`"model_tiers"`), search provider (`"search_provider"`), MCP config (`"mcp"`), briefing schedule, email notification prefs, job scan queries, user profile, daemon settings (including `auto_start_web_ui`, `auto_start_discord`, `auto_start_telegram`), rate limits, custom prompt, user model settings (`"user_model"`). |
| `memory.json` | Global persistent memory store (objects with `text`, `embedding`, `created`). |
| `reminders.json` | Global reminders (cross-project). |
| `user_profile.json` | Persistent user model — learned facts, preferences, patterns, goals with confidence scores. Global (not project-scoped). |
| `sync_sources.json` | File sync source/destination mappings. |
| `requirements.txt` | Python runtime dependencies. `sentence-transformers`, `watchdog`, and `mcp` are commented out (optional). |
| `requirements-dev.txt` | Test dependencies (pytest, pytest-mock). Install with `pip install -r requirements-dev.txt`. |
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
├── docs/                   # Detailed architecture documentation
├── interfaces/
│   ├── __init__.py         # Exports InterfaceAdapter
│   ├── base_adapter.py     # Abstract base class for all interfaces
│   ├── terminal_adapter.py # Terminal (chat.py) adapter
│   ├── discord_adapter.py  # Discord adapter
│   ├── telegram_adapter.py # Telegram adapter
│   ├── web_adapter.py      # Web UI adapter
│   ├── example_adapter.py  # Commented reference implementation
│   └── README.md           # How to build a new interface
├── web_ui/
│   ├── server.py           # WebSocket server (thin adapter)
│   ├── index.html           # Entry point
│   ├── app.js              # Client logic (WebSocket, rendering, confirmation dialogs)
│   ├── styles.css          # Styling (CSS custom properties)
│   └── README.md           # Architecture & Tauri integration guide
├── skills/                 # Specialist skill files (.md with YAML front matter)
├── providers/              # LLM provider abstraction layer
│   ├── __init__.py         # Provider ABC, registry, factory
│   ├── compat.py           # Anthropic-compatible wrapper types
│   ├── anthropic_provider.py  # Anthropic (zero-overhead pass-through)
│   ├── openai_provider.py  # OpenAI SDK wrapper
│   └── gemini_provider.py  # Google GenAI SDK wrapper
├── search_providers/       # Search provider abstraction layer
│   ├── __init__.py         # SearchProvider ABC, registry, factory
│   ├── duckduckgo_provider.py  # DuckDuckGo (default, no key)
│   ├── brave_provider.py   # Brave Search (free tier)
│   ├── tavily_provider.py  # Tavily (free, built for AI)
│   ├── google_provider.py  # Google Custom Search (best quality)
│   └── serpapi_provider.py # SerpAPI (paid)
├── plugins/                # User-installable tool packages (.py files or packages)
│   ├── __init__.py         # Plugin loader (discovers .py files and packages)
│   ├── example_plugin.py   # Reference implementation (dice roller)
│   ├── DIRECTORY.md        # Community plugin registry
│   └── README.md           # How to write a plugin
├── tests/
└── venv/
```

---

## Architecture

### Model Routing

| Model | ID (Anthropic default) | Used For |
|-------|----|----------|
| Haiku | `claude-haiku-4-5` | Research, summaries, conversation titles, briefings, fit assessment, context compression, user model extraction |
| Sonnet | `claude-sonnet-4-6` | Routing decisions, coding, general conversation, director model, user model pattern detection |
| Opus | `claude-opus-4-6` | Cover letters, deep analysis, creative writing (always used for cover letters regardless of active model) |

Models addressed by tier (`fast`/`standard`/`quality`) via provider abstraction. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for tier tables and provider details.

### Specialist Delegation

The director (Sonnet) can route messages to specialist agents:
- **researcher** (Haiku) — web research and summarization
- **writer** (Opus) — creative writing, cover letters, polished prose
- **coder** (Sonnet) — code generation and debugging
- **analyst** (Sonnet) — problem analysis, finding flaws, critical thinking

### Extensible Skills

Specialists can be augmented with skills — `.md` files in the `skills/` directory with YAML front matter defining `name`, `description`, `specialist`, `model_preference`, `default`, and `trigger_keywords`. Ships with 9 built-in skills: 4 base specialist skills + 5 task skills. Users can customize specialist behavior by editing base skill files or add new skills by dropping `.md` files into `skills/`.

### 28 Integrated Tools

`web_search`, `read_file`, `write_file`, `remember`, `forget`, `list_memories`, `save_note`, `run_python`, `job_search`, `check_email`, `read_email`, `search_email`, `create_task`, `create_reminder`, `list_tasks`, `complete_task`, `edit_task`, `remove_task`, `add_task_note`, `list_reminders`, `cancel_reminder`, `web_fetch`, `generate_pdf`, `create_docx`, `create_xlsx`, `get_calendar_events`, `create_calendar_event`, `save_attachment`

### Memory System

- **Storage:** `memory.json` (global) + `projects/{name}/memory.json` (per-project)
- **Semantic search:** `sentence-transformers` (`all-MiniLM-L6-v2`), top 15 injected into system prompt. Fallback: all memories loaded without embeddings.
- **Cross-project:** Scans all project dirs and injects summaries into system prompt

### Context Compression

- Triggers at 20,000 estimated tokens
- Keeps first 3 + last 5 exchanges; Haiku summarizes removed middle sections

### Prompt Caching

Two-block system prompt for Anthropic prompt caching: stable block (behavioral directives, identity, cached) + dynamic block (date/time, memories, rebuilt every turn). Tool schemas also cached via `get_cached_tools()`. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for details.

---

## Security Architecture

1. Draft-only email — Gmail `compose` scope, not `send`
2. Calendar: create only — no delete, no modify
3. Web content isolation — untrusted markers, no tool execution from fetched content
4. File sandbox — `read_file` restricted to project directory, no dotfiles, no system paths
5. Credential lockdown — `.env` + `chmod 600` on tokens
6. Rate limits — 10 drafts/session, 10 fetches/session, 20 notifications/hour, 3 scans/day
7. Human-in-the-loop — confirmation required for calendar events and code execution on all interfaces
8. User-gated messaging — Discord/Telegram bots respond only to configured user ID
9. Anti-injection on drafts — external email content marked as untrusted data

**Structural safety model:** Safety enforced in code, not prompts. No Tool = No Action (tool registry gates capabilities). Code Gates > Prompt Gates (confirm_fn, rate limits, OAuth scopes, path sandboxing). External Data Never Trusted (tool results, not instruction injection). Prompt Is Weakest Layer (behavioral directives are NOT safety mechanisms). See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for full principles.

**For contributors:** New tools must be added to the `TOOLS` list in `tools.py`. New actions touching external systems must include a `confirm_fn` check. External data must enter via tool results, never raw prompt injection.

---

## All Commands

**Chat:** `/opus`, `/sonnet`, `/haiku`, `/challenge on|off`, `/prompt [text|clear]`, `/new`, `/load`, `/conversations`, `/conversations clear`, `/delete`, `/clear`, `/attach <path>`

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

**System:** `/help [category]`, `/status`, `/tokens`, `/billing`, `/delegates`, `/skills`, `/skills reload`, `/plugins`, `/plugins reload`, `/profile`, `/profile clear`, `/profile remove <entry>`, `/setup`, `/update`, `/reset`

**Creative:** `/characters`, `/character <name>`, `/locations`, `/location <name>`

---

## Coding Conventions

- **Python 3.10+**, no enforced type hints
- **Optional dependencies** are wrapped in try/except at import time with None sentinels and guards at usage sites. Never crash on a missing optional package.
- **Lazy imports** to avoid circular dependencies: `tools.py` imports `models` inside functions, `notifications.py` imports `tools` inside `check_new_emails()`.
- **Dict access on external data** uses `.get()` with defaults. Direct `dict["key"]` only for internal data with known structure.
- **File I/O**: Always `os.makedirs(exist_ok=True)` before writing. Check `os.path.exists()` before reading. JSON loads wrapped in try/except.
- **Errors** produce helpful messages, not tracebacks. Tool execution errors always surface to the user with the error type (e.g. `ValueError`) — never silently swallowed. File extraction failures in attachments report which file failed. Plugin load failures log to stderr.
- **Interfaces are thin**: All business logic in shared core modules. Interface files handle only I/O adaptation.
- **Tests**: pytest with monkeypatched paths (isolated temp dirs). 467 tests across 26 test files.

---

## Developer Notes

- **Tested on:** Python 3.10+ on Linux (Ubuntu/WSL2) and macOS
- **GPU optional:** Semantic search works on CPU; auto-detects CUDA if available
- **Browser opening (WSL):** Uses `wslview` if configured
- **Commercial-potential work** (Tauri desktop app, Flutter mobile app, hosted service) belongs in separate private repos, never in this public repo.

## Communication Style

The system prompt enforces these behaviors (see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for detailed descriptions):
- Be direct. No hedging, no sycophancy, no unearned praise
- If an idea is bad, say so and explain why
- If something is wrong, say so
- Don't over-explain things the user already understands
- Match the energy of the conversation — brief when they're brief, deep when they want depth
- Honest critique over validation
- Explain the *why* behind commands and syntax, not just copy-paste
- Cost-conscious on API usage — avoid unnecessary API calls

---

## Known Data Disconnects

The daemon reads/writes several data files that the conversational agent cannot yet access through tools:

- **`scan_results.json`** — daemon writes scan results, agent can't query scan history
- **`seen_jobs.json`** — daemon manages dismissed jobs, agent unaware of dedup state
- **`logs/notifications.log`** — daemon writes notification events, agent can't see notification history
- **`logs/seen_emails.json`** — daemon tracks notified emails, agent doesn't know which were already flagged
- **Briefing output** — ephemeral, generated and sent but not stored to disk for later retrieval

---

## Known Stretch Goals

- **MCP (Model Context Protocol)** — ~~expose tools as MCP servers~~ **Shipped.** `mcp_server.py`
- **Provider abstraction** — ~~support OpenAI, Gemini, local models alongside Anthropic~~ **Shipped.** `providers/`
- **Tauri desktop app** — native desktop wrapper
- **Mobile app** — iOS/Android interface
- **Plugin system** — ~~user-installable tool packages~~ **Shipped.** `plugins/`
- **Docker** — containerized deployment
- **LinkedIn monitoring** — job board integration
- **Voice input/output** — local Whisper on GPU
- **Portfolio tracking** — local CSV exports
- **GitHub portfolio cleanup** — sanitize agent code, publish as portfolio piece

---

*This file is read by Claude Code on startup. Keep it accurate and up to date. Detailed docs in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).*
