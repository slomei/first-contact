# Architecture Deep Dive

*Detailed reference documentation for First Contact internals. For project overview, file map, and conventions, see [CLAUDE.md](../CLAUDE.md).*

---

## Provider Abstraction (Detailed)

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

---

## Search Provider Abstraction (Detailed)

`search_providers/` mirrors the LLM provider pattern. `SearchProvider` ABC defines `search(query, max_results) -> [{"title", "url", "snippet"}]`. Five concrete providers:

| Provider | Config key | API Key | Notes |
|----------|-----------|---------|-------|
| DuckDuckGo | `duckduckgo` | None (default) | Unofficial scraper (`ddgs`), may break |
| Brave | `brave` | `BRAVE_SEARCH_API_KEY` | Official API, free 2K queries/month |
| Tavily | `tavily` | `TAVILY_API_KEY` | Free 1,000 queries/month, built for AI agents |
| Google | `google` | `GOOGLE_SEARCH_API_KEY` + `GOOGLE_SEARCH_CX` | Best quality, 100 free/day |
| SerpAPI | `serpapi` | `SERPAPI_KEY` | Paid, starts $50/month |

**Configuration.** Set `"search_provider": "brave"` in `config.json` and add the API key to `.env`. Default is `duckduckgo` (zero config). The onboarding wizard offers search provider setup as an optional integration step.

`get_search_provider()` returns a cached provider instance. `tools.web_search()`, `tools.search_jobs()`, and `job_scanner.py` all use it — no direct DDGS imports outside the provider.

---

## MCP Server (Detailed)

`mcp_server.py` exposes First Contact's tools to external MCP clients (Claude Desktop, Cursor, etc.) over stdio transport. It reads directly from `tools.TOOLS` and `plugins.get_all_plugin_tools()` — no duplication, no divergence.

**Tool translation.** `get_mcp_tools()` maps Anthropic-style `input_schema` to MCP-style `inputSchema`, strips `cache_control` markers, and filters out blacklisted tools. Returns plain dicts that are testable without the MCP SDK installed.

**Blacklist.** `run_python` is blacklisted by default — auto-approve (no `confirm_fn`) would mean unsandboxed code execution. Configurable in `config.json` under `"mcp"."blacklist"`. Other tools that use `confirm_fn` for confirmation (calendar events) auto-approve via MCP — this is a documented trade-off.

**Async bridge.** `call_tool()` runs `tools.execute_tool()` via `asyncio.to_thread()` with `confirm_fn=None`. Code-level safety gates (path sandboxing, rate limits, OAuth scopes) still apply.

**Optional dependency.** `mcp>=1.0.0` is commented out in `requirements.txt`. `MCP_AVAILABLE` sentinel guards the server entry point. `get_mcp_tools()` and `call_tool()` work without the SDK for testing.

---

## Prompt Caching (Detailed)

The system prompt is split into two content blocks for Anthropic prompt caching:

- **Stable block** (`_build_stable_prompt()`) — Behavioral directives, identity, tool parameter guidance, challenge mode, custom prompt, resume reference, cross-project summary, integration status, user model tier 1 profile (preferences, high-confidence facts, goals). Marked with `cache_control: {"type": "ephemeral"}`. Changes only on explicit user action, not per-turn.
- **Dynamic block** (`_build_dynamic_prompt()`) — Date/time, memories (semantic or all), user model tier 2 profile (patterns, lower-confidence facts filtered by conversation context), creative context. Rebuilt every turn.

Tool definitions also use prompt caching: `get_cached_tools()` returns `TOOLS` with `cache_control` on the last tool. Tool schemas are kept minimal — behavioral guidance and parameter usage notes are in the stable system prompt block where they benefit from caching instead of being re-sent as uncached schema tokens.

`build_system_prompt_cached()` returns the two-block list. The older `build_system_prompt()` still exists for callers that need a single string.

---

## System Prompt Behaviors (Detailed)

The system prompt (`memory.py`) includes six behavioral directives built from actual usage patterns:

- **Calibrated honesty** — Evaluate work accurately. Praise when earned, critique when warranted. Never default to enthusiasm, sugarcoat bad news, or inflate quality to be supportive.
- **Act-don't-ask** — When the user asks to do something, do it immediately. Don't ask for confirmation, optional fields, or clarifying questions unless the request is truly ambiguous. Programmatic confirmation gates (calendar events, file overwrites) handle their own confirmation — the agent doesn't add a second layer.
- **Typo tolerance** — Never ask if something is a typo unless it affects a concrete output like a calendar event, email draft, file name, or cover letter. If the intent is interpretable, just act on it.
- **Memory restraint** — Never use `remember` or `forget` unless the user explicitly asks. No unsolicited memory reorganization, consolidation, or updates — not when reading files, not when learning new info mid-conversation. Profile learning is handled post-conversation by `user_model.py`.
- **Format preservation** — When a user attaches a file and asks to save it, preserve the original format. Use `save_attachment` to save binary files (PDF, DOCX, XLSX, images) in their original format. Don't offer to save a PDF as text/markdown or convert a spreadsheet to CSV.
- **Self-knowledge** — Dynamic section describing First Contact's own identity, capabilities, tool count, skill count, and architecture. Rebuilt each turn so the agent can accurately answer "what are you?" questions.
- **Tool parameter notes** — Consolidated guidance for tool usage (memory defaults, date/time parameter format, generate_pdf modes, calendar confirmation) in the stable block so the model has context without bloating tool schemas.
- **Search restraint** — Explicit "when NOT to search" rules: don't search when the answer is in conversation/memories, when the user asks about their own data (use the right tool instead), or when following up on an already-discussed topic.

---

## Multi-Email Account Support

- Config stores `email_accounts` array with label + credentials file per account
- Email check/search operations iterate across all accounts
- Legacy single-account setup supported as fallback
- OAuth2 per account, separate credential files

---

## Timezone Handling

- `memory.get_timezone()` reads `config.briefing.timezone`, defaults to `America/New_York`
- `memory.local_now()` returns timezone-aware datetime — all modules use this instead of bare `datetime.now()`
- System prompt includes dynamic date/time in the user's local timezone
- All user-facing timestamps (notes, tasks, reminders, briefings) use `local_now()`

---

## Structural Safety Model

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

## Interface Behavior Details

### Terminal (`chat.py`)

- Prompt format: `You [model/project/challenge]: `
- `_TerminalStreamer` strips `**bold**`, `*italic*`, `` `code` ``, `# headers` from output while preserving raw response in conversation history; code blocks preserved
- Welcome-back message if >7 days since last session
- Startup shows memory count, active applications, daemon status, due reminders, open tasks
- Session cost per-turn and cumulative; summary on exit
- Graceful exit: `/quit`, `/exit`, `quit`, `exit`, Ctrl+C, EOF

### Web UI (`web_ui/`)

- WebSocket server on `ws://localhost:8765` (configurable port)
- Per-connection isolation — each browser tab gets its own conversation history, model, project, and token counters
- Vanilla HTML/CSS/JS frontend — no framework, no build step
- Streaming responses, tool activity indicators, model switching, project switching (`set_project` message), accent color picker. Model selector dropdown and per-message badges are provider-aware — populated dynamically from the server via a `models` message on connect, displaying actual model IDs (e.g. `gpt-4o` not `sonnet`) from the active provider
- Two distinct drop zones: **chat input area** (`.input-wrapper`) queues files as temporary attachment chips sent with the next message (never persisted); **sidebar drop zone** (`#dropZone`) saves files to the project's `files/` directory (persistent). Paperclip button also queues to chips. Chips show below the input row with × remove buttons. Both zones use `preventDefault`/`stopPropagation` to prevent the browser from opening files in a new tab
- **Server-synced sidebar file list:** The `#fileList` sidebar is populated from the server via `{"type": "file_list"}` messages, showing files from both `files/` (uploads) and `workspace/` (tool-written). `send_file_list(ws, conn)` is called on connect, after `handle_file_upload`, after `file_delete`, and after any file-writing tool completes (`write_file`, `save_note`, `generate_pdf`, `create_docx`, `create_xlsx`). Tool detection uses a `used_tools` set populated by `on_tool_start`, checked against `FILE_WRITE_TOOLS` after the turn. Workspace files get a "ws" badge in the sidebar. Sidebar × button sends `{"type": "file_delete"}` to the server, which removes the file from disk (`files.remove_file()` for uploads, `os.remove()` with `basename` path sanitization for workspace files) and re-sends the file list. Files persist across page reloads
- **File preview modal:** Clicking a file name in the sidebar sends `{"type": "file_preview"}` to the server, which returns `file_preview_result` with name, dir, size, `preview_type` (`text`/`pdf`/`image`/`null`), and preview content. Client shows a modal overlay with filename, size, and type-specific preview: text files get first 30 lines in a monospace `<pre>`, PDFs render in a browser-native `<iframe>` via blob URL, images show as `<img>` thumbnails via data URL, other files show metadata only. Modal has Open (triggers `file_download` for browser download) and Delete buttons. Click outside to dismiss. `showFilePreview()` in index.html, no-op in app.js
- Status and error messages (`addStatusMessage` in index.html, `showStatus` in app.js) render as small centered italic text (`.status-msg` class), not chat bubbles. Keeps system feedback visually distinct from conversation
- `/prompt [text|clear]` command — view, set, or clear custom system prompt instructions
- Context compression at 20K tokens (same threshold as terminal, via shared `models.compress_conversation()`)
- Conversation auto-save on new chat and disconnect (via shared `models.save_conversation()`)
- Prompt caching via `build_system_prompt_cached()` and `get_cached_tools()`
- Specific Anthropic API error handling (rate limit, auth, context overflow, connection)
- Designed as foundation for eventual Tauri desktop app
- Suggested workflows shown on first connection after onboarding (same `suggestions_shown` config flag as terminal)
- **`memory.active_project` sync:** All handlers that touch project-scoped files (`handle_message`, `handle_file_upload`, `file_preview`, `file_download`, `file_delete`, `send_file_list`) set `memory.active_project = conn.active_project` before calling into shared core modules. This is required because `memory.active_project` is a module-level global and `handle_message` runs concurrently via `asyncio.create_task()`
- Confirmation flow: `make_web_confirm_fn()` sends `{"type": "confirm"}` over WebSocket, client shows Approve/Deny buttons, user response sent back as `{"type": "confirm_response"}`. Server-side uses `threading.Event` to block the executor thread (60s timeout). `handle_message` runs via `asyncio.create_task()` so the dispatch loop continues processing `confirm_response` frames during tool execution

### Discord (`discord_bot.py`)

- Background loop intervals: reminders (60s), email checks (5min), daily briefing (configurable), job scan (Mon-Fri)
- Notification priority: high = immediate DM, medium = batched every 30min, low = silent
- Confirmation flow: `make_discord_confirm_fn()` sends a bold prompt to the DM channel, blocks the worker thread on `threading.Event` (60s timeout). `on_message` intercepts yes/y/no/n replies via `state._pending_confirm` before command routing. Discord.py processes events concurrently so callbacks fire while tool execution is awaiting

### Telegram (`telegram_bot.py`)

- Confirmation flow: `make_telegram_confirm_fn()` sends `InlineKeyboardMarkup` with Confirm/Cancel buttons, blocks worker thread on `threading.Event` (60s timeout). `CallbackQueryHandler` (registered before `MessageHandler`) handles button presses. Text yes/no fallback via `_pending_confirms` interception in `handle_message`. Requires `concurrent_updates=True` on the Application builder so callback queries are processed while the message handler awaits tool execution

### Onboarding

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
