# First Contact — Web Frontend

Standalone HTML/CSS/JS frontend that connects to the Python backend via WebSocket. Foundation for the eventual Tauri desktop app.

This is a new interface alongside `chat.py`, `discord_bot.py`, and `telegram_bot.py`. It does not replace any of them.

## Quick Start

```bash
# Install dependency (if not already)
pip install websockets

# Start the WebSocket server
python web_ui/server.py

# Open in browser
# File > Open web_ui/index.html
# Or: wslview web_ui/index.html
```

The server listens on `ws://localhost:8765` by default. Pass `--port` to change:

```bash
python web_ui/server.py --port 9000
```

## Architecture

```
web_ui/
├── server.py    # WebSocket server (thin adapter — all logic in shared core)
├── index.html   # Entry point
├── styles.css   # All styling (CSS custom properties, responsive)
├── app.js       # Client logic (WebSocket, rendering, controls)
└── README.md    # This file
```

**server.py** follows the same thin-adapter pattern as all other interfaces:
- Per-connection state (`Connection` class) — own conversation history, model, token counters
- Streams API responses via `client.messages.stream()`
- Tool loop (up to 10 turns) matching `chat.py`'s pattern

**Frontend** is vanilla HTML/CSS/JS — no framework, no build step.

## WebSocket Protocol

All messages are JSON. The `type` field determines the message kind.

### Client → Server

| Type | Fields | Description |
|------|--------|-------------|
| `message` | `content`, `model` | Send a chat message. `model` is the model ID to use. |
| `new_chat` | — | Clear conversation history, reset counters. |
| `set_model` | `model` | Switch the active model for this connection. |

### Server → Client

| Type | Fields | Description |
|------|--------|-------------|
| `stream` | `content` | Partial text chunk during streaming. Append to current bubble. |
| `tool_status` | `content` | Tool execution status (e.g., "Searching the web: ..."). |
| `response` | `content`, `input_tokens`, `output_tokens`, `cost`, `session_cost` | Final response with token/cost data. |
| `status` | `content` | Status text (e.g., "New conversation started.", "Switched to haiku."). |
| `error` | `content` | Error message. |

### Example Flow

```
Client: {"type": "message", "content": "What's the weather?", "model": "claude-sonnet-4-6"}
Server: {"type": "stream", "content": "Let me "}
Server: {"type": "stream", "content": "search for "}
Server: {"type": "stream", "content": "that."}
Server: {"type": "tool_status", "content": "Searching the web: \"current weather\""}
Server: {"type": "stream", "content": "Based on "}
Server: {"type": "stream", "content": "my search..."}
Server: {"type": "response", "content": "Based on my search...", "input_tokens": 1200, "output_tokens": 150, "cost": 0.0059, "session_cost": 0.0059}
```

## Tauri Integration Guide

The frontend is designed to drop into a Tauri webview with minimal changes:

1. **WebSocket URL**: Change `WS_URL` in `app.js` to point to a Tauri-spawned sidecar, or replace WebSocket with Tauri's `invoke()` IPC.

2. **localStorage**: Replace with `@tauri-apps/plugin-store` for persistent settings.

3. **External links**: Replace `window.open()` with `@tauri-apps/plugin-shell`'s `open()`.

4. **Server**: `server.py` becomes a Tauri sidecar process, spawned and managed by the Rust backend.

5. **File paths**: Use Tauri's `path` module instead of hardcoded paths.

Everything else (HTML, CSS, message rendering, accent color, auto-scroll) works as-is inside a webview.
