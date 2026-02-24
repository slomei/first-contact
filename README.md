# First Contact

A personal AI agent built from scratch with the Anthropic API. Not a chatbot — an agent that actually does things.

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Anthropic API](https://img.shields.io/badge/Anthropic-Claude-blueviolet.svg)](https://www.anthropic.com/)

<video src="https://github.com/user-attachments/assets/abc5fe1d-5ae5-4878-8715-ff036865b6d5" width="100%" controls></video>

**[Watch the demo on Vimeo](https://vimeo.com/1167090219)**

---

## What Is This?

First Contact is a personal AI agent that connects to your email, calendar, job boards, and the web — then helps you manage all of it through natural conversation. Four interfaces (terminal, web UI, Discord, Telegram) share a single core. It runs locally, stores everything on your machine, and never sends an email without your explicit approval. Built security-first: draft-only email, credential lockdown, untrusted web content isolation, human-in-the-loop for every write operation.

## Features

**Four interfaces, one agent.** Talk to First Contact through the terminal, a standalone web UI, Discord, or Telegram. All four share the same brain, memory, and tools.

**Multi-provider support.** Supports Anthropic (default), OpenAI, and Google Gemini. Set `"provider": "openai"` in `config.json` to switch. Model tiers (fast/standard/quality) map to each provider's equivalent models. Anthropic-specific optimizations (prompt caching, batch API) work when available and degrade gracefully for other providers.

**Search providers.** First Contact searches the web out of the box with DuckDuckGo (no API key needed). For better results, swap to Brave Search (free, 2,000 queries/month), Google Custom Search (best quality, 100 free/day), or SerpAPI (paid). Change one config key and add your API key — that's it.

**Smart model routing.** Every request is routed to the right model for the job. The fast tier handles research and summaries. The standard tier handles conversation and code. The quality tier handles cover letters, deep analysis, and creative writing. A director model evaluates each message and can delegate to specialist agents (researcher, writer, coder, analyst) when the task calls for it.

**Extensible skills system.** Specialists can be augmented with skills — markdown files with YAML front matter that get injected into specialist system prompts when keyword-matched. Ships with 5 built-in skills (cover letters, research, code review, email drafting, job analysis). Drop a `.md` file into `skills/` to create your own.

**Plugin system.** Add new tools without modifying core code. Drop a Python file into `plugins/` with a tool definition and handler function, and it's auto-discovered on startup. Plugins receive read-only copies of config and conversation history. Ships with an example dice-roller plugin. See `plugins/README.md` for the full spec.

**Plugin ecosystem.** Create plugins with the built-in template generator: `python plugin_generator.py my_plugin`. Scaffolds a complete plugin with metadata, stub tools, and documentation. Browse community plugins in the [plugin directory](plugins/DIRECTORY.md). Plugins run with full process access — review source code before installing third-party plugins.

**MCP server.** Expose First Contact's tools to external AI clients via the [Model Context Protocol](https://modelcontextprotocol.io/). Claude Desktop, Cursor, and any MCP-compatible client can discover and call all 27 core tools (plus plugins) directly — email, calendar, web search, tasks, memory, files — without going through the chat interface. Configurable tool blacklist for safety (`run_python` blocked by default). Optional dependency: install `mcp` to enable.

**27 core tools** (plus any from plugins):

- **Web search** — configurable search provider (DuckDuckGo default, Brave/Google/SerpAPI), with page fetching and content extraction
- **Gmail** — Read your inbox, search emails, draft replies. Multi-account support. Draft-only: the agent creates drafts, you send them
- **Google Calendar** — View events, create new ones (with confirmation). Read and create only — no delete, no modify
- **Job search pipeline** — Search boards, save listings, track application status, auto-generate cover letters as formatted PDFs
- **Proactive job scanning** — Scheduled multi-platform scans with AI fit assessment against your profile, delivered via Discord/Telegram
- **Task & reminder system** — Natural language dates, priority levels, due date tracking, background reminder delivery. The agent can list, complete, edit, and remove tasks conversationally — not just via slash commands
- **Daily briefing** — Aggregates email, calendar, tasks, jobs, reminders, and watchlist topics into a single morning report
- **Proactive insights** — Cross-references tasks, email, calendar, jobs, and reminders every 6 hours to surface actionable connections. Delivered via notifications. Stays silent when nothing is worth flagging
- **Persistent memory** — Two-layer memory system: global facts persist across all projects, project-specific memories stay scoped. Semantic search retrieves the most relevant memories per query instead of loading all (requires optional `sentence-transformers` — works on CPU, uses GPU if available)
- **File operations** — Read, write, and manage files in sandboxed project workspaces
- **Code execution** — Run Python in a sandboxed workspace with timeout protection
- **PDF generation** — Professional cover letters with formatted headers, or general documents from any text
- **Notification routing** — Background email monitoring with priority filtering, delivered to Discord, Telegram, email, or all three
- **Markdown notes** — Capture timestamped thoughts, research, and links organized as daily markdown files. Searchable across your project

**Background daemon.** A lightweight scheduler (`daemon.py`) that runs in the background and executes scheduled tasks — daily briefings, email monitoring, job scans, and reminder delivery — without keeping the chat open. Manages its own PID file, handles graceful shutdown, and routes notifications to Discord, Telegram, or email based on your config. Enable `--hot-reload` or set `"hot_reload": true` in your daemon config to auto-restart subprocesses when Python files change — useful for plugin development and iterating on core modules.

**Semantic memory search.** Optionally install `sentence-transformers` for meaning-based memory retrieval. Instead of loading every memory into context, the agent retrieves the top 15 most relevant to each query using 384-dimensional embeddings. Falls back gracefully to loading all memories when the package isn't installed. Works on CPU; auto-detects and uses GPU when available.

**Context window management.** Automatic conversation compression on all four interfaces when context gets large — summarizes older exchanges with Haiku, keeps recent ones intact. You never hit a wall mid-conversation. The `/status` command shows context usage percentage and compression count.

**Prompt caching.** The system prompt is split into stable and dynamic blocks with `cache_control` breakpoints. Stable content (behavioral directives, identity, tool parameter guidance, custom prompt) is cached across turns; only the dynamic portion (date/time, memories) is re-sent. Tool definitions are also cached. Daemon tasks (job scanning, briefings, digests) use the same pattern. Typical input token savings: 40–60%.

**User-customizable system prompt.** The `/prompt` command lets you add persistent behavioral instructions that layer on top of the core template — "always respond in bullet points", "use British spelling", etc. Stored in `config.json`, survives restarts, configurable during onboarding. `/prompt clear` removes it.

**Project system.** Separate workspaces with their own memories, tasks, conversations, and files. Switch between work, creative projects, and job searching without context bleed.

**Calibrated honesty.** The system prompt enforces honest evaluation — praise when earned, critique when warranted. No default enthusiasm, no sugarcoating, no inflated feedback. Combined with act-don't-ask behavior: when you tell the agent to do something, it does it immediately instead of asking for confirmation or optional details.

**Self-knowledge.** The agent knows what it is. A dynamic self-knowledge section in the system prompt describes First Contact's identity, capabilities, tool count, skill count, and architecture — rebuilt every turn so the agent can accurately answer questions about itself.

**Timezone-aware.** All timestamps use the user's configured timezone (`config.briefing.timezone`). Notes, tasks, reminders, briefings, and the system prompt's date/time display all use `memory.local_now()` instead of bare `datetime.now()`.

**Personalized onboarding.** A guided setup wizard configures your profile, communication style, integrations, and notification preferences. Then the agent has a short conversation with you to calibrate its personality to how you actually communicate — not just what you selected from a menu. No config file editing required.

**Two-tier help system.** Type `/help` for a category overview, `/help <category>` for detailed commands. Help text is shared across all interfaces from a single source of truth (`help_data.py`), formatted appropriately for each platform.

**Service registry.** A centralized module (`service_registry.py`) tracks which integrations are configured and healthy — Discord, Telegram, Gmail, Calendar, web search, job search. The `/status` command shows available integrations. Onboarding, the daemon, and the system prompt all read from the registry instead of each doing their own credential checks.

**Shared conversation loop.** All four interfaces delegate to a single `conversation.py` module that handles the API call, tool execution loop, streaming, and confirmations. Adding a new interface means wiring up callbacks — all capabilities come for free.

**Interface parity.** Nine features work identically across all four interfaces: conversation loop, prompt caching, context compression, human-in-the-loop confirmations, suggested workflows, model switching, project switching, token/cost tracking, and conversation persistence.

**Transparent status.** The `/status` command shows everything at a glance: active model, project, context usage, session cost, available integrations, daemon status, last briefing, last scan results, pending tasks, reminders, and memory counts.

**Suggested workflows.** After onboarding, the agent shows personalized suggestions based on what you configured — email triage if Gmail is connected, calendar checks if Calendar is set up, daemon tips if Discord/Telegram are available. Shown once on first startup across all interfaces.

## Architecture

```
┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐
│ Terminal  │  │  Web UI  │  │ Discord  │  │ Telegram │
│ (chat.py) │  │ (web_ui/)│  │(disc_bot)│  │(tele_bot)│
└────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘
     │              │              │              │
     └──────────────┴──────┬──────┴──────────────┘
                           │
                    ┌──────▼──────────────────┐
                    │       Shared Core          │
                    │  conversation.py           │
                    │  memory.py · models.py     │
                    │  tools.py · tasks.py       │
                    │  service_registry · plugins │
                    │  briefing · documents      │
                    │  notifications · files     │
                    │  help_data · creative      │
                    │  job_scanner · daemon      │
                    └────────────┬───────────────┘
                                 │
              ┌──────────┬───────┼───────┬──────────┐
              ▼          ▼       ▼       ▼          ▼
         ┌────────┐ ┌────────┐ ┌───┐ ┌────────┐ ┌────────┐
         │ Gmail  │ │Calendar│ │Web│ │  Job   │ │  File  │
         │  API   │ │  API   │ │   │ │ Boards │ │ System │
         └────────┘ └────────┘ └───┘ └────────┘ └────────┘
```

**37 Python modules:**

| File | Purpose |
|------|---------|
| `chat.py` | Terminal interface — primary interactive chat |
| `web_ui/server.py` | WebSocket server — standalone web frontend (vanilla HTML/CSS/JS client) |
| `discord_bot.py` | Discord bot with background monitoring loops |
| `telegram_bot.py` | Telegram bot |
| `conversation.py` | Shared conversation turn loop — all 4 interfaces delegate here |
| `memory.py` | Persistent memory, semantic search, system prompt, projects |
| `models.py` | Model routing, provider dispatch, API calls, pricing, context compression, specialists |
| `providers/` | Provider abstraction — Anthropic, OpenAI, Gemini with Anthropic-compatible wrapper |
| `search_providers/` | Search provider abstraction — DuckDuckGo, Brave, Google, SerpAPI |
| `tools.py` | 27 core tool definitions + plugin routing |
| `tasks.py` | Task and reminder system with natural language dates |
| `documents.py` | Document generation — PDF (cover letters, generic), DOCX, XLSX |
| `briefing.py` | Daily briefing aggregation (7 data sources) |
| `notifications.py` | Email classification and notification routing |
| `insights.py` | Proactive cross-source insight synthesis (daemon-only, Sonnet tier) |
| `job_scanner.py` | Proactive multi-platform job scanning with AI fit assessment |
| `batch_api.py` | Batch API wrapper for 50% cost job assessments |
| `daemon.py` | Background scheduler for briefings, email, scans, reminders |
| `onboarding.py` | Interactive setup wizard (21 steps, multi-interface) |
| `help_data.py` | Shared help categories and per-interface formatters |
| `creative.py` | Creative project tools (world bible, characters, locations) |
| `skills_loader.py` | Extensible skills system (keyword matching, specialist prompt injection) |
| `files.py` | Project file management (import, list, remove, validation) |
| `parsers.py` | Binary document text extraction (PDF, DOCX, XLSX) |
| `service_registry.py` | Centralized integration status checks (6 built-in services) |
| `plugin_generator.py` | Plugin template generator (scaffolds new plugins with metadata and docs) |
| `plugins/` | Plugin loader — auto-discovers user-installable tool packages |
| `mcp_server.py` | MCP server — exposes tools to Claude Desktop, Cursor, and other MCP clients |
| `sync.py` | File sync with version conflict resolution |

The four interfaces are thin layers. All logic lives in the shared core — model routing, tool execution, memory, notifications. Adding a new interface means writing the I/O adapter; all tools and capabilities come for free.

**Building new interfaces:** The `interfaces/` directory contains an `InterfaceAdapter` abstract base class that defines the contract for new interfaces. Subclass it, implement the abstract methods (receive input, send output, send files, notifications, confirmation), and wire up the shared core. See `interfaces/example_adapter.py` for a reference. The existing interfaces predate this pattern and work independently.

## Quick Start

**Prerequisites:** Python 3.10+, an [Anthropic API key](https://console.anthropic.com/)

```bash
# Clone the repo
git clone https://github.com/slomei/first-contact.git
cd first-contact

# Run setup
./setup.sh

# Start talking
source venv/bin/activate
python chat.py

# Optional: start with background daemon
python chat.py --with-daemon

# Or run the daemon separately
python daemon.py
```

The setup script creates a virtual environment, installs dependencies, and copies config templates. On first launch, the onboarding wizard walks you through everything else — name, integrations, preferences, and a short calibration conversation so the agent learns how you actually communicate.

For the web interface instead of terminal:

```bash
pip install websockets
python web_ui/server.py
# Open web_ui/index.html in a browser
```

For background monitoring, run `python daemon.py` in a separate terminal (or use `--with-daemon`). The daemon handles scheduled briefings, email monitoring, job scans, and reminder delivery without keeping the chat open.

### Optional dependencies

**Semantic memory search:** Install `sentence-transformers` for meaning-based memory retrieval. Without it, the agent loads all memories into context (works fine for smaller collections). With it, the agent retrieves only the top 15 most relevant memories per query using vector embeddings.

```bash
pip install sentence-transformers
```

Works on CPU. Auto-detects and uses GPU (CUDA) when available for faster embedding.

### Optional integrations

**Gmail & Calendar:** Require Google Cloud OAuth credentials. Supports multiple Gmail accounts. The onboarding wizard guides you through setup, or run `/email setup` and `/cal setup` later.

**Discord bot:** Create a bot at [discord.com/developers](https://discord.com/developers/applications), add the token to your `.env`, invite the bot to your server. The onboarding wizard walks through this step by step.

**Telegram bot:** Message [@BotFather](https://t.me/BotFather) on Telegram, create a bot, add the token to your `.env`. Setup mode auto-detects your user ID on first message.

### MCP Server

Expose First Contact's tools to Claude Desktop, Cursor, or any MCP client. Install the optional dependency and add the server to your client's config:

```bash
pip install mcp
```

**Claude Desktop** (`claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "first-contact": {
      "command": "python",
      "args": ["/path/to/first-contact/mcp_server.py"]
    }
  }
}
```

**Important:** Tools that require human confirmation in the chat interface (calendar events, code execution) execute automatically via MCP. `run_python` is blacklisted by default. Review the blacklist in `config.json` under `"mcp"."blacklist"` and add any tools you want gated:

```json
{
  "mcp": {
    "blacklist": ["run_python", "create_calendar_event"]
  }
}
```

## Configuration

All configuration lives in two files (neither ships with personal data):

**`.env`** — API keys and tokens:
```
ANTHROPIC_API_KEY=your-key-here
DISCORD_BOT_TOKEN=your-discord-token        # optional
DISCORD_USER_ID=your-discord-id             # optional
TELEGRAM_BOT_TOKEN=your-telegram-token      # optional
TELEGRAM_USER_ID=your-telegram-id           # optional
OPENAI_API_KEY=your-openai-key              # optional, for openai provider
GEMINI_API_KEY=your-gemini-key              # optional, for gemini provider
BRAVE_SEARCH_API_KEY=your-key              # optional, for brave search provider
GOOGLE_SEARCH_API_KEY=your-key             # optional, for google search provider
GOOGLE_SEARCH_CX=your-search-engine-id     # optional, for google search provider
SERPAPI_KEY=your-key                        # optional, for serpapi search provider
```

**`config.json`** — Generated by the onboarding wizard. Contains your profile, briefing schedule, notification preferences, job scan queries, and integration settings. Run `/setup` anytime to reconfigure. Provider and daemon configuration:

```json
{
  "provider": "anthropic",
  "model_tiers": null,
  "search_provider": "duckduckgo",
  "daemon": {
    "enabled": true,
    "briefing_time": "07:00",
    "email_check_interval_minutes": 30,
    "scan_interval_hours": 12,
    "reminder_check_interval_minutes": 5,
    "notify_channel": "discord"
  }
}
```

Set `"provider"` to `"openai"` or `"gemini"` to switch LLM providers. Override individual model tiers with `"model_tiers": {"fast": "...", "standard": "...", "quality": "..."}`. Set `"search_provider"` to `"brave"`, `"google"`, or `"serpapi"` to switch search engines (default: `"duckduckgo"`).

## Security Model

This isn't an afterthought — security is baked into the architecture.

**Draft-only email.** The agent creates Gmail drafts. It cannot send email. The OAuth scope is `gmail.compose` (draft creation), not `gmail.send`. You review and send from your email client.

**Calendar: create only.** The agent can read your calendar and create events (with mandatory confirmation). It cannot delete or modify existing events.

**Credential lockdown.** API keys live in `.env` (never committed). OAuth tokens are `chmod 600`. No secrets in source code.

**Web content is untrusted.** Every fetched page is wrapped with isolation markers before entering the conversation. The agent is instructed to treat web content as data, never as instructions. Prompt injection from web pages can't trigger tool use.

**Anti-injection on email drafts.** When drafting replies, external email content is explicitly marked as untrusted data in the system prompt. The agent drafts based on user intent, not on instructions found in incoming email.

**File access sandboxed.** The `read_file` tool is restricted to the project directory. It cannot read dotfiles, system paths, or anything outside the project tree. No access to `.ssh`, `.env`, or system configs.

**Rate limits everywhere.** 10 drafts per session, 10 web fetches per session, 20 notifications per hour, 3 manual job scans per day. Prevents runaway API costs and abuse.

**Human-in-the-loop.** Calendar events and code execution require confirmation on all four interfaces (terminal prompt, web UI dialog, Discord DM, Telegram inline keyboard). Everything destructive asks first.

**User-gated messaging.** Discord and Telegram bots only respond to your user ID. Nobody else can interact with your agent.

## Structural Safety Model

Most AI agent projects tell the model to be safe. First Contact assumes the model won't listen, and builds accordingly.

Safety that depends on an AI model choosing to follow instructions will eventually fail. First Contact's security is built on four structural principles that enforce boundaries in code, not in prompts.

### 1. No Tool, No Action

The agent's capabilities are defined by the tool registry. If a tool doesn't exist for an action, the agent cannot take it. Capability restriction is the strongest form of safety — you can't misuse what doesn't exist.

**Enforced in:** `tools.py` (tool registry defines all available actions), `plugins/__init__.py` (plugin tools go through the same registry with sandboxed execution), `get_cached_tools()` (only registered tools are presented to the model)

*Example: The agent can draft emails but cannot send them. There is no "send email" tool. The absence of the capability is the safety mechanism.*

### 2. Code Gates, Not Prompt Gates

Any action that affects the outside world passes through structural enforcement the model cannot override. Confirmation flows block execution until a human approves. Rate limits are enforced in Python. File access is sandboxed before the model sees results. OAuth scopes are narrowed at the API level. The model doesn't decide whether to ask permission — the code decides for it.

**Enforced in:** `conversation.py` (confirmation flows via `confirm_fn`, blocks on `threading.Event`), `tools.py` (rate limits, file path sandboxing), Gmail/Calendar integrations (narrowed OAuth scopes), `plugins/__init__.py` (read-only config copies)

*Example: When the agent creates a calendar event, the code blocks execution and presents the action to the user for approval. The model cannot skip this step regardless of what its prompt says.*

### 3. External Data Is Never Trusted

Content from web searches, emails, files, and URLs is data to be processed, not commands to be followed. All external content enters through structured tool outputs that separate content from the instruction context.

**Enforced in:** Web search results return via tool output (not injected into system prompt), email content processed through Gmail tool output, `read_file` returns content as tool results (sandboxed to project directories), plugins receive copied conversation history

*Example: A web search result containing "ignore previous instructions" is treated as text content, not as a command. Even if the model were influenced, the code gates (Principle 2) would block any dangerous action.*

### 4. The Prompt Is the Weakest Layer

Behavioral directives in the system prompt shape how the agent communicates — calibrated honesty, act-don't-ask, self-knowledge. They are explicitly NOT relied upon for safety-critical boundaries. When a prompt directive and a code gate conflict, code wins. Always. The prompt layer exists for UX quality, not for safety enforcement.

**Enforced in:** `memory.py` (behavioral directives shape communication style, not security boundaries), every safety-critical boundary has a corresponding code-level enforcement (Principles 1–3)

*Example: The system prompt says "act, don't ask" to reduce unnecessary confirmation requests. But the confirmation code overrides this for any action touching external systems — code requires confirmation regardless of what the prompt says.*

## Commands

First Contact responds to natural conversation and also supports direct commands. Type `/help` for a category overview, or `/help <category>` for details:

| Category | Commands |
|----------|----------|
| **Chat** | `/opus`, `/sonnet`, `/haiku`, `/challenge on\|off`, `/prompt [text\|clear]`, `/new`, `/load`, `/conversations`, `/delete`, `/clear` |
| **Memory** | `/remember`, `/remember -p`, `/forget`, `/memories`, `/memories search`, `/note`, `/notes`, `/notes search` |
| **Email** | `/email check`, `/email read`, `/email search`, `/draft reply`, `/draft new`, `/draft work`, `/drafts`, `/email setup` |
| **Calendar** | `/cal`, `/cal tomorrow`, `/cal week`, `/cal add`, `/cal setup` |
| **Jobs** | `/work search`, `/work save`, `/work list`, `/work remove`, `/work apply`, `/work track`, `/work status`, `/resume`, `/cover` |
| **Scanning** | `/scan`, `/scan results`, `/scan status`, `/scan queries`, `/scan query add\|remove`, `/scan on\|off` |
| **Tasks** | `/task add`, `/tasks`, `/task done`, `/task remove`, `/task edit`, `/task note`, `/tasks done`, `/remind`, `/reminders`, `/remind cancel` |
| **Web** | `/web`, `/fetch`, `/read`, `/write`, `/run`, `/pdf` |
| **System** | `/help`, `/status`, `/briefing`, `/notify`, `/project`, `/watch`, `/digest`, `/tokens`, `/billing`, `/delegates`, `/skills`, `/plugins`, `/setup`, `/update`, `/reset`, `/characters`, `/locations` |

Claude also uses tools autonomously when they'd help — searching the web mid-conversation, saving facts to memory, checking your calendar when you ask about availability.

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on adding tools, building new interfaces, and code style.

## Built By

Built by a video editor with 13 years in feature animation, not a software engineer. If I can build this, the barrier to entry is lower than you think.

## License

[MIT](LICENSE)
