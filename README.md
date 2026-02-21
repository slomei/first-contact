# First Contact

A personal AI agent built from scratch with the Anthropic API. Not a chatbot — an agent that actually does things.

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Anthropic API](https://img.shields.io/badge/Anthropic-Claude-blueviolet.svg)](https://www.anthropic.com/)

---

## What Is This?

First Contact is a personal AI agent that connects to your email, calendar, job boards, and the web — then helps you manage all of it through natural conversation. It runs locally, stores everything on your machine, and never sends an email without your explicit approval. Built security-first: draft-only email, credential lockdown, untrusted web content isolation, human-in-the-loop for every write operation.

## Features

**Four interfaces, one agent.** Talk to First Contact through the terminal, a web GUI, Discord, or Telegram. All four share the same brain, memory, and tools.

**Smart model routing.** Every request is routed to the right Claude model for the job. Haiku handles research and summaries. Sonnet handles conversation and code. Opus handles cover letters, deep analysis, and creative writing. A director model evaluates each message and can delegate to specialist agents (researcher, writer, coder, analyst) when the task calls for it.

**17 integrated tools:**

- **Web search** — DuckDuckGo-powered, with page fetching and content extraction
- **Gmail** — Read your inbox, search emails, draft replies. Multi-account support. Draft-only: the agent creates drafts, you send them
- **Google Calendar** — View events, create new ones (with confirmation). Read and create only — no delete, no modify
- **Job search pipeline** — Search boards, save listings, track application status, auto-generate cover letters as formatted PDFs
- **Proactive job scanning** — Scheduled multi-platform scans with AI fit assessment against your profile, delivered via Discord/Telegram
- **Task & reminder system** — Natural language dates, priority levels, due date tracking, background reminder delivery
- **Daily briefing** — Aggregates email, calendar, tasks, jobs, reminders, and watchlist topics into a single morning report
- **Persistent memory** — Two-layer memory system: global facts persist across all projects, project-specific memories stay scoped
- **File operations** — Read, write, and manage files in sandboxed project workspaces
- **Code execution** — Run Python in a sandboxed workspace with timeout protection
- **PDF generation** — Professional cover letters with formatted headers, or general documents from any text
- **Notification routing** — Background email monitoring with priority filtering, delivered to Discord, Telegram, email, or all three
- **Markdown notes** — Capture timestamped thoughts, research, and links organized as daily markdown files. Searchable across your project

**Background daemon.** A lightweight scheduler (`daemon.py`) that runs in the background and executes scheduled tasks — daily briefings, email monitoring, job scans, and reminder delivery — without keeping the chat open. Works with Discord, Telegram, or email notifications.

**Context window management.** Automatic conversation compression when context gets large — summarizes older exchanges with Haiku, keeps recent ones intact. You never hit a wall mid-conversation.

**Project system.** Separate workspaces with their own memories, tasks, conversations, and files. Switch between work, creative projects, and job searching without context bleed.

**Personalized onboarding.** A guided setup wizard configures your profile, communication style, integrations, and notification preferences. Then the agent has a short conversation with you to calibrate its personality to how you actually communicate — not just what you selected from a menu. No config file editing required.

## Architecture

```
┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐
│  Terminal    │  │   Web GUI   │  │   Discord    │  │  Telegram   │
│  (chat.py)  │  │  (gui.py)   │  │(discord_bot) │  │(telegram_bot│
└──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘
       │                │                │                │
       └────────────────┴────────┬───────┴────────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │     Shared Core         │
                    │  memory.py · models.py  │
                    │  tools.py · tasks.py    │
                    │  briefing · documents   │
                    │  notifications · sync   │
                    └────────────┬────────────┘
                                 │
              ┌──────────┬───────┼───────┬──────────┐
              ▼          ▼       ▼       ▼          ▼
         ┌────────┐ ┌────────┐ ┌───┐ ┌────────┐ ┌────────┐
         │ Gmail  │ │Calendar│ │Web│ │  Job   │ │  File  │
         │  API   │ │  API   │ │   │ │ Boards │ │ System │
         └────────┘ └────────┘ └───┘ └────────┘ └────────┘
```

The four interfaces are thin layers. All logic lives in the shared core — model routing, tool execution, memory, notifications. Adding a new interface means writing the I/O adapter; all tools and capabilities come for free.

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

For background monitoring, run `python daemon.py` in a separate terminal (or use `--with-daemon`). The daemon handles scheduled briefings, email monitoring, job scans, and reminder delivery without keeping the chat open.

### Optional integrations

**Gmail & Calendar:** Require Google Cloud OAuth credentials. Supports multiple Gmail accounts. The onboarding wizard guides you through setup, or run `/email setup` and `/cal setup` later.

**Discord bot:** Create a bot at [discord.com/developers](https://discord.com/developers/applications), add the token to your `.env`, invite the bot to your server. The onboarding wizard walks through this step by step.

**Telegram bot:** Message [@BotFather](https://t.me/BotFather) on Telegram, create a bot, add the token to your `.env`. Setup mode auto-detects your user ID on first message.

## Configuration

All configuration lives in two files (neither ships with personal data):

**`.env`** — API keys and tokens:
```
ANTHROPIC_API_KEY=your-key-here
DISCORD_BOT_TOKEN=your-discord-token        # optional
DISCORD_USER_ID=your-discord-id             # optional
TELEGRAM_BOT_TOKEN=your-telegram-token      # optional
TELEGRAM_USER_ID=your-telegram-id           # optional
```

**`config.json`** — Generated by the onboarding wizard. Contains your profile, briefing schedule, notification preferences, job scan queries, and integration settings. Run `/setup` anytime to reconfigure. Includes daemon configuration:

```json
{
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

## Security Model

This isn't an afterthought — security is baked into the architecture.

**Draft-only email.** The agent creates Gmail drafts. It cannot send email. The OAuth scope is `gmail.compose` (draft creation), not `gmail.send`. You review and send from your email client.

**Calendar: create only.** The agent can read your calendar and create events (with mandatory confirmation). It cannot delete or modify existing events.

**Credential lockdown.** API keys live in `.env` (never committed). OAuth tokens are `chmod 600`. No secrets in source code.

**Web content is untrusted.** Every fetched page is wrapped with isolation markers before entering the conversation. The agent is instructed to treat web content as data, never as instructions. Prompt injection from web pages can't trigger tool use.

**Anti-injection on email drafts.** When drafting replies, external email content is explicitly marked as untrusted data in the system prompt. The agent drafts based on user intent, not on instructions found in incoming email.

**File access sandboxed.** The `read_file` tool is restricted to the project directory. It cannot read dotfiles, system paths, or anything outside the project tree. No access to `.ssh`, `.env`, or system configs.

**Rate limits everywhere.** 10 drafts per session, 10 web fetches per session, 20 notifications per hour, 3 manual job scans per day. Prevents runaway API costs and abuse.

**Human-in-the-loop.** Calendar events require confirmation. File overwrites require confirmation. Everything destructive asks first.

**User-gated messaging.** Discord and Telegram bots only respond to your user ID. Nobody else can interact with your agent.

## Commands

First Contact responds to natural conversation and also supports direct commands. Type `/help` for a category overview, or `/help <category>` for details:

| Category | Commands |
|----------|----------|
| **Chat** | `/opus`, `/sonnet`, `/haiku`, `/challenge on\|off`, `/new`, `/clear` |
| **Memory** | `/remember`, `/remember -p`, `/forget`, `/memories`, `/note`, `/notes` |
| **Email** | `/email check`, `/email read`, `/email search`, `/draft reply`, `/draft new`, `/draft work` |
| **Calendar** | `/cal`, `/cal tomorrow`, `/cal week`, `/cal add`, `/cal setup` |
| **Jobs** | `/work search`, `/work save`, `/work list`, `/work apply`, `/work track`, `/work status` |
| **Scanning** | `/scan`, `/scan results`, `/scan queries`, `/scan on\|off` |
| **Tasks** | `/task add`, `/tasks`, `/task done`, `/remind`, `/reminders` |
| **Web** | `/web`, `/fetch`, `/read`, `/write`, `/run`, `/pdf` |
| **System** | `/help`, `/status`, `/briefing`, `/notify`, `/project`, `/setup`, `/delegates` |

Claude also uses tools autonomously when they'd help — searching the web mid-conversation, saving facts to memory, checking your calendar when you ask about availability.

## Built By

Built by a video editor with 13 years in feature animation, not a software engineer. If I can build this, the barrier to entry is lower than you think.

## License

[MIT](LICENSE)
