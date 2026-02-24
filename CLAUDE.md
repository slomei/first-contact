# CLAUDE.md — First Contact Project Context

*Last updated: February 23, 2026*

---

## Project Overview

First Contact is a personal AI agent built from scratch with the Anthropic API. It connects to Gmail, Google Calendar, job boards, and the web through natural conversation. Four interfaces (terminal, web UI, Discord, Telegram) share a single core. Everything runs locally. Security-first: draft-only email, sandboxed files, untrusted web isolation, human-in-the-loop for writes.

**Status:** Shipped. All 449 tests passing. Live on GitHub.

---

## File Map

### Interfaces (thin I/O adapters)

| File | Description |
|------|-------------|
| `chat.py` | Terminal chatbot — primary interface. Streaming output, markdown stripping, session cost tracking, startup diagnostics, `/attach` for temporary file injection. |
| `web_ui/` | WebSocket-based web frontend (server.py + vanilla HTML/CSS/JS). Per-connection state, streaming responses, tool loop, token tracking, context compression, conversation persistence, `/prompt` command, project switching (`set_project`), chat-input temporary attachments (drag-drop + paperclip queue as chips, sent with next message), sidebar persistent file upload, binary file upload support (PDF/DOCX/XLSX). Designed as Tauri desktop app foundation. |
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
| `tools.py` | 27 core tool definitions (`TOOLS` list) and `execute_tool()` dispatch. Gmail, Calendar, web search, file I/O, code execution, job search, notes, tasks, reminders, PDF generation, DOCX/XLSX creation. Unknown tool names fall through to plugins. `get_cached_tools()` merges core + plugin tools with `cache_control` on the last tool. `_rebuild_cached_tools()` refreshes after plugin reload. |
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
| `files.py` | Project file management — import, list, remove files. Validation, large-file detection, conversation injection formatting. `extract_file_for_chat()` for temporary attachment injection, `write_binary_file_contents()` for binary uploads. Image support: `is_image_file()`, `encode_image_for_api()` for multimodal content blocks (PNG, JPG, JPEG, GIF, WebP). Used by all interfaces and web UI drag-and-drop. Binary documents (PDF, DOCX, XLSX) routed through `parsers.py`. |
| `parsers.py` | Binary document text extraction — PDF (pdfplumber), DOCX (python-docx), XLSX (openpyxl). Optional deps with clear error messages. Used by `files.py` and `tools.py` read_file. |
| `plugin_generator.py` | Plugin template generator — scaffolds new plugins with correct directory structure, metadata (`plugin.json`), stub tools, and documentation. CLI via argparse, also importable. Validates names, prevents overwrites. |
| `plugins/` | Plugin system — `__init__.py` loader discovers `.py` files and packages (directories with `__init__.py`), validates required attributes (`PLUGIN_NAME`, `TOOLS`, `execute`), routes tool calls. `example_plugin.py` reference implementation (dice roller). `DIRECTORY.md` community plugin registry. `README.md` for plugin authors. |
| `search_providers/` | Search provider abstraction — `__init__.py` (ABC, registry, factory), `duckduckgo_provider.py` (default, no key), `brave_provider.py` (free tier, recommended), `google_provider.py` (best quality), `serpapi_provider.py` (paid). Config: `"search_provider"` in config.json. |
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
| `tests/test_search_providers.py` | Search providers — ABC compliance, registry/factory, config selection, all 4 provider request/response format, missing key errors. |
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
│   ├── app.js              # Client logic (WebSocket, rendering)
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

### Provider Abstraction

`models.get_client()` returns an Anthropic-compatible client regardless of active provider. For Anthropic, this is the raw SDK client (zero overhead). For OpenAI/Gemini, it's an `AnthropicCompatClient` wrapper that translates requests and normalizes responses. All callers (conversation.py, briefing.py, job_scanner.py, etc.) work unchanged.

**Tier system.** Models are addressed by tier (`fast`, `standard`, `quality`) rather than hardcoded IDs. The `/opus`, `/sonnet`, `/haiku` commands always exist — they map to the active provider's equivalent models.

| Tier | Anthropic | OpenAI | Gemini |
|------|-----------|--------|--------|
| `fast` | claude-haiku-4-5 | gpt-4o-mini | gemini-2.0-flash-lite |
| `standard` | claude-sonnet-4-6 | gpt-4o | gemini-2.0-flash |
| `quality` | claude-opus-4-6 | o3 | gemini-2.5-pro |

**Feature degradation.** Prompt caching and batch API are Anthropic-only. `cache_control` is silently stripped for other providers (multipliers set to 0). Batch API falls back to sequential. Tool use and streaming are translated for all providers.

**Configuration.** Set `"provider": "openai"` (or `"gemini"`) in `config.json`. Override individual tiers with `"model_tiers": {"fast": "custom-model"}`. Module-level defaults are Anthropic values at import time; `_init_model_data()` refreshes from the active provider on first `get_client()` call.

**Adding a new provider:** Subclass `providers.Provider`, implement `get_client()` / `get_tiers()` / `get_pricing()` / `get_features()`, call `register_provider()` at module level.

### Search Provider Abstraction

`search_providers/` mirrors the LLM provider pattern. `SearchProvider` ABC defines `search(query, max_results) -> [{"title", "url", "snippet"}]`. Four concrete providers:

| Provider | Config key | API Key | Notes |
|----------|-----------|---------|-------|
| DuckDuckGo | `duckduckgo` | None (default) | Unofficial scraper (`ddgs`), may break |
| Brave | `brave` | `BRAVE_SEARCH_API_KEY` | Official API, free 2K queries/month |
| Google | `google` | `GOOGLE_SEARCH_API_KEY` + `GOOGLE_SEARCH_CX` | Best quality, 100 free/day |
| SerpAPI | `serpapi` | `SERPAPI_KEY` | Paid, starts $50/month |

**Configuration.** Set `"search_provider": "brave"` in `config.json` and add the API key to `.env`. Default is `duckduckgo` (zero config). The onboarding wizard offers search provider setup as an optional integration step.

`get_search_provider()` returns a cached provider instance. `tools.web_search()`, `tools.search_jobs()`, and `job_scanner.py` all use it — no direct DDGS imports outside the provider.

### MCP Server

`mcp_server.py` exposes First Contact's tools to external MCP clients (Claude Desktop, Cursor, etc.) over stdio transport. It reads directly from `tools.TOOLS` and `plugins.get_all_plugin_tools()` — no duplication, no divergence.

**Tool translation.** `get_mcp_tools()` maps Anthropic-style `input_schema` to MCP-style `inputSchema`, strips `cache_control` markers, and filters out blacklisted tools. Returns plain dicts that are testable without the MCP SDK installed.

**Blacklist.** `run_python` is blacklisted by default — auto-approve (no `confirm_fn`) would mean unsandboxed code execution. Configurable in `config.json` under `"mcp"."blacklist"`. Other tools that use `confirm_fn` for confirmation (calendar events) auto-approve via MCP — this is a documented trade-off.

**Async bridge.** `call_tool()` runs `tools.execute_tool()` via `asyncio.to_thread()` with `confirm_fn=None`. Code-level safety gates (path sandboxing, rate limits, OAuth scopes) still apply.

**Optional dependency.** `mcp>=1.0.0` is commented out in `requirements.txt`. `MCP_AVAILABLE` sentinel guards the server entry point. `get_mcp_tools()` and `call_tool()` work without the SDK for testing.

### Model Routing

| Model | ID (Anthropic default) | Used For |
|-------|----|----------|
| Haiku | `claude-haiku-4-5` | Research, summaries, conversation titles, briefings, fit assessment, context compression, user model extraction |
| Sonnet | `claude-sonnet-4-6` | Routing decisions, coding, general conversation, director model, user model pattern detection |
| Opus | `claude-opus-4-6` | Cover letters, deep analysis, creative writing (always used for cover letters regardless of active model) |

### Specialist Delegation

The director (Sonnet) can route messages to specialist agents:
- **researcher** (Haiku) — web research and summarization
- **writer** (Opus) — creative writing, cover letters, polished prose
- **coder** (Sonnet) — code generation and debugging
- **analyst** (Sonnet) — problem analysis, finding flaws, critical thinking

### Extensible Skills

Specialists can be augmented with skills — `.md` files in the `skills/` directory with YAML front matter defining `name`, `description`, `specialist`, `model_preference`, `default`, and `trigger_keywords`. When a message is delegated, `skills_loader.get_default_skill()` loads the base instructions for that specialist, then `match_skill()` finds the best keyword match and layers it on top. Ships with 9 built-in skills: 4 base specialist skills (researcher, writer, coder, analyst) + 5 task skills (cover_letter, research, code_review, email_draft, job_analysis). Users can customize specialist behavior by editing base skill files or add new skills by dropping `.md` files into `skills/`.

### 27 Integrated Tools

`web_search`, `read_file`, `write_file`, `remember`, `forget`, `list_memories`, `save_note`, `run_python`, `job_search`, `check_email`, `read_email`, `search_email`, `create_task`, `create_reminder`, `list_tasks`, `complete_task`, `edit_task`, `remove_task`, `add_task_note`, `list_reminders`, `cancel_reminder`, `web_fetch`, `generate_pdf`, `create_docx`, `create_xlsx`, `get_calendar_events`, `create_calendar_event`

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

### Prompt Caching

The system prompt is split into two content blocks for Anthropic prompt caching:

- **Stable block** (`_build_stable_prompt()`) — Behavioral directives, identity, tool parameter guidance, challenge mode, custom prompt, resume reference, cross-project summary, integration status, user model tier 1 profile (preferences, high-confidence facts, goals). Marked with `cache_control: {"type": "ephemeral"}`. Changes only on explicit user action, not per-turn.
- **Dynamic block** (`_build_dynamic_prompt()`) — Date/time, memories (semantic or all), user model tier 2 profile (patterns, lower-confidence facts filtered by conversation context), creative context. Rebuilt every turn.

Tool definitions also use prompt caching: `get_cached_tools()` returns `TOOLS` with `cache_control` on the last tool. Tool schemas are kept minimal — behavioral guidance and parameter usage notes are in the stable system prompt block where they benefit from caching instead of being re-sent as uncached schema tokens.

`build_system_prompt_cached()` returns the two-block list. The older `build_system_prompt()` still exists for callers that need a single string.

### System Prompt Behaviors

The system prompt (`memory.py`) includes four behavioral directives built from actual usage patterns:

- **Calibrated honesty** — Evaluate work accurately. Praise when earned, critique when warranted. Never default to enthusiasm, sugarcoat bad news, or inflate quality to be supportive.
- **Act-don't-ask** — When the user asks to do something, do it immediately. Don't ask for confirmation, optional fields, or clarifying questions unless the request is truly ambiguous. Programmatic confirmation gates (calendar events, file overwrites) handle their own confirmation — the agent doesn't add a second layer.
- **Typo tolerance** — Never ask if something is a typo unless it affects a concrete output like a calendar event, email draft, file name, or cover letter. If the intent is interpretable, just act on it.
- **Self-knowledge** — Dynamic section describing First Contact's own identity, capabilities, tool count, skill count, and architecture. Rebuilt each turn so the agent can accurately answer "what are you?" questions.
- **Tool parameter notes** — Consolidated guidance for tool usage (memory defaults, date/time parameter format, generate_pdf modes, calendar confirmation) in the stable block so the model has context without bloating tool schemas.
- **Search restraint** — Explicit "when NOT to search" rules: don't search when the answer is in conversation/memories, when the user asks about their own data (use the right tool instead), or when following up on an already-discussed topic.

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
7. Human-in-the-loop — confirmation required for calendar events and code execution on all interfaces (terminal `input()`, web UI WebSocket confirm dialog, Discord yes/no DM, Telegram inline keyboard). `tools.clean_confirm_prompt()` strips terminal `[y/N]:` suffixes for non-terminal interfaces
8. User-gated messaging — Discord/Telegram bots respond only to configured user ID
9. Anti-injection on drafts — external email content marked as untrusted data

### Structural Safety Model

First Contact's security is built on a core assumption: safety that depends on an AI model choosing to follow instructions will eventually fail. The four principles below enforce safety in code, not in prompts.

**Principle 1: No Tool, No Action.** The agent's capabilities are explicitly defined by the tool registry. If a tool doesn't exist for an action, the agent cannot take it. New tools must go through the registry (`tools.py` `TOOLS` list or `plugins/__init__.py`). `get_cached_tools()` presents only registered tools to the model.

**Principle 2: Code Gates, Not Prompt Gates.** Any action affecting the outside world passes through structural enforcement the model cannot override:
- `conversation.py` — confirmation flows via `confirm_fn` callback, blocks on `threading.Event`
- `tools.py` — rate limits (10 drafts/session, 10 fetches/session, 20 notifs/hr, 3 scans/day), `read_file` path sandboxing (rejects paths outside project dir, blocks dotfiles/system paths)
- Gmail — OAuth scope restricted to compose (not send)
- Calendar — OAuth scope narrowed to events (not full access)
- `plugins/__init__.py` — plugins receive `copy.deepcopy()` of config and history

**Principle 3: External Data Is Never Trusted.** Content from web searches, emails, files, and URLs enters through structured tool outputs, never injected into the instruction context. Web results, email content, and file reads all return as tool results that the model processes as data. Plugins receive copied (not referenced) conversation history.

**Principle 4: The Prompt Is the Weakest Layer.** Behavioral directives (`_STABLE_PROMPT_TEMPLATE` in `memory.py`) shape communication style — calibrated honesty, act-don't-ask, self-knowledge, typo tolerance. They are explicitly NOT safety mechanisms. When a prompt directive and a code gate conflict, code wins.

**For contributors:** New tools must be added to the `TOOLS` list in `tools.py` (Principle 1). New actions that touch external systems must include a `confirm_fn` check in their execution path (Principle 2). External data must enter via tool results, never raw prompt injection (Principle 3).

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

## Developer Notes

- **Tested on:** Python 3.10+ on Linux (Ubuntu/WSL2) and macOS
- **GPU optional:** Semantic search works on CPU; auto-detects CUDA if available
- **Browser opening (WSL):** Uses `wslview` if configured
- **Commercial-potential work** (Tauri desktop app, Flutter mobile app, hosted service) belongs in separate private repos, never in this public repo.

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
- Per-connection isolation — each browser tab gets its own conversation history, model, project, and token counters
- Vanilla HTML/CSS/JS frontend — no framework, no build step
- Streaming responses, tool activity indicators, model switching, project switching (`set_project` message), accent color picker. Model selector dropdown and per-message badges are provider-aware — populated dynamically from the server via a `models` message on connect, displaying actual model IDs (e.g. `gpt-4o` not `sonnet`) from the active provider
- Two distinct drop zones: **chat input area** (`.input-wrapper`) queues files as temporary attachment chips sent with the next message (never persisted); **sidebar drop zone** (`#dropZone`) saves files to the project's `files/` directory (persistent). Paperclip button also queues to chips. Chips show below the input row with × remove buttons. Both zones use `preventDefault`/`stopPropagation` to prevent the browser from opening files in a new tab
- `/prompt [text|clear]` command — view, set, or clear custom system prompt instructions
- Context compression at 20K tokens (same threshold as terminal, via shared `models.compress_conversation()`)
- Conversation auto-save on new chat and disconnect (via shared `models.save_conversation()`)
- Prompt caching via `build_system_prompt_cached()` and `get_cached_tools()`
- Specific Anthropic API error handling (rate limit, auth, context overflow, connection)
- Designed as foundation for eventual Tauri desktop app
- Suggested workflows shown on first connection after onboarding (same `suggestions_shown` config flag as terminal)
- Confirmation flow: `make_web_confirm_fn()` sends `{"type": "confirm"}` over WebSocket, client shows Approve/Deny buttons, user response sent back as `{"type": "confirm_response"}`. Server-side uses `threading.Event` to block the executor thread (60s timeout). `handle_message` runs via `asyncio.create_task()` so the dispatch loop continues processing `confirm_response` frames during tool execution

**Discord (`discord_bot.py`):**
- Background loop intervals: reminders (60s), email checks (5min), daily briefing (configurable), job scan (Mon-Fri)
- Notification priority: high = immediate DM, medium = batched every 30min, low = silent
- Confirmation flow: `make_discord_confirm_fn()` sends a bold prompt to the DM channel, blocks the worker thread on `threading.Event` (60s timeout). `on_message` intercepts yes/y/no/n replies via `state._pending_confirm` before command routing. Discord.py processes events concurrently so callbacks fire while tool execution is awaiting

**Telegram (`telegram_bot.py`):**
- Confirmation flow: `make_telegram_confirm_fn()` sends `InlineKeyboardMarkup` with Confirm/Cancel buttons, blocks worker thread on `threading.Event` (60s timeout). `CallbackQueryHandler` (registered before `MessageHandler`) handles button presses. Text yes/no fallback via `_pending_confirms` interception in `handle_message`. Requires `concurrent_updates=True` on the Application builder so callback queries are processed while the message handler awaits tool execution

**Onboarding:**
- Generates `Claude.md` (personal context), updated `config.json`, `setup_env.sh` (chmod 600)

### Interface Parity

All four interfaces share these features via the shared core:

| Feature | Terminal | Web UI | Discord | Telegram |
|---------|----------|--------|---------|----------|
| Conversation loop (`conversation.run_conversation_turn()`) | ✅ | ✅ | ✅ | ✅ |
| Prompt caching (`build_system_prompt_cached()` + `get_cached_tools()`) | ✅ | ✅ | ✅ | ✅ |
| Context compression (20K token threshold) | ✅ | ✅ | ✅ | ✅ |
| Human-in-the-loop confirmations | ✅ | ✅ | ✅ | ✅ |
| Suggested workflows (post-onboarding) | ✅ | ✅ | ✅ | ✅ |
| Model switching (Haiku/Sonnet/Opus) | ✅ | ✅ | ✅ | ✅ |
| Project switching | ✅ | ✅ | ✅ | ✅ |
| Token/cost tracking (incl. cache tokens) | ✅ | ✅ | ✅ | ✅ |
| Conversation persistence | ✅ | ✅ | ✅ | ✅ |

---

## Coding Conventions

- **Python 3.10+**, no enforced type hints
- **Optional dependencies** are wrapped in try/except at import time with None sentinels and guards at usage sites. Never crash on a missing optional package.
- **Lazy imports** to avoid circular dependencies: `tools.py` imports `models` inside functions, `notifications.py` imports `tools` inside `check_new_emails()`.
- **Dict access on external data** uses `.get()` with defaults. Direct `dict["key"]` only for internal data with known structure.
- **File I/O**: Always `os.makedirs(exist_ok=True)` before writing. Check `os.path.exists()` before reading. JSON loads wrapped in try/except.
- **Errors** produce helpful messages, not tracebacks.
- **Interfaces are thin**: All business logic in shared core modules. Interface files handle only I/O adaptation.
- **Tests**: pytest with monkeypatched paths (isolated temp dirs). 449 tests across 26 test files.

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

- **MCP (Model Context Protocol)** — ~~expose tools as MCP servers~~ **Shipped.** `mcp_server.py` — stdio transport, tool translation, configurable blacklist, async bridge
- **Provider abstraction** — ~~support OpenAI, Gemini, local models alongside Anthropic~~ **Shipped.** `providers/` directory with ABC, registry, Anthropic/OpenAI/Gemini implementations, tier system
- **Tauri desktop app** — native desktop wrapper
- **Mobile app** — iOS/Android interface
- **Plugin system** — ~~user-installable tool packages~~ **Shipped.** `plugins/` directory with auto-discovery, sandboxed execution, example plugin, template generator (`plugin_generator.py`), community directory
- **Docker** — containerized deployment
- **LinkedIn monitoring** — job board integration
- **Voice input/output** — local Whisper on GPU
- **Portfolio tracking** — local CSV exports
- **GitHub portfolio cleanup** — sanitize agent code, publish as portfolio piece

---

*This file is read by Claude Code on startup. Keep it accurate and up to date.*
