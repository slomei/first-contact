"""
WebSocket server for the First Contact web frontend.

Thin adapter — all logic in the shared core modules.
Each WebSocket connection gets its own conversation state.
"""

from dotenv import load_dotenv
load_dotenv()

import argparse
import asyncio
import json
import os
import re
import sys
import threading

# Add parent dir to path so we can import shared core
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import anthropic
import conversation
import memory
import models
import onboarding
import tools
import files

try:
    import websockets
except ImportError:
    print("websockets not installed. Run: pip install websockets")
    sys.exit(1)


# Short name -> full model ID (matches the <select> values in the new UI)
MODEL_MAP = {
    "sonnet": "claude-sonnet-4-6",
    "haiku": "claude-haiku-4-5",
    "opus": "claude-opus-4-6",
}


class Connection:
    """Per-client state. Isolated from other connections and from models.py globals."""

    def __init__(self):
        self.history = []
        self.active_model = "claude-sonnet-4-6"
        self.active_project = "general"
        self.session_input_tokens = 0
        self.session_output_tokens = 0
        self.session_cost = 0.0
        self.session_cache_creation_tokens = 0
        self.session_cache_read_tokens = 0
        self.compressions = 0
        self._pending_confirm = None


def make_web_confirm_fn(ws, conn, loop):
    """Create a confirm_fn that sends a WebSocket confirmation dialog and blocks until response."""

    def confirm_fn(prompt):
        clean_prompt = tools.clean_confirm_prompt(prompt)
        event = threading.Event()
        holder = {"approved": False}
        conn._pending_confirm = {"event": event, "holder": holder}

        try:
            asyncio.run_coroutine_threadsafe(
                ws.send(json.dumps({"type": "confirm", "content": clean_prompt})),
                loop,
            ).result(timeout=5)
        except Exception:
            conn._pending_confirm = None
            return False

        if not event.wait(timeout=60):
            conn._pending_confirm = None
            try:
                asyncio.run_coroutine_threadsafe(
                    ws.send(json.dumps({
                        "type": "status",
                        "content": "Confirmation timed out. Action cancelled.",
                    })),
                    loop,
                ).result(timeout=5)
            except Exception:
                pass
            return False

        approved = holder["approved"]
        conn._pending_confirm = None
        return approved

    return confirm_fn


async def handle_message(ws, conn, data):
    """Handle an incoming 'message' request — stream API response, handle tool loop."""
    user_msg = data.get("content", "").strip()
    if not user_msg:
        return

    # Sync project state so system prompt uses the right project's memories
    memory.active_project = conn.active_project
    memory.memories = memory.load_memories()

    # Override model if client sent one (accept short names or full IDs)
    if data.get("model"):
        resolved = MODEL_MAP.get(data["model"], data["model"])
        if resolved in models.MODELS.values():
            conn.active_model = resolved

    # --- Slash command handling ---
    if user_msg.startswith("/prompt"):
        arg = user_msg[7:].strip()
        if not arg:
            current = memory.get_custom_prompt()
            if current:
                msg = f"Current custom prompt:\n{current}"
            else:
                msg = "No custom prompt set. Send /prompt <text> to add one."
        elif arg.lower() == "clear":
            memory.set_custom_prompt("")
            msg = "Custom prompt cleared."
        else:
            memory.set_custom_prompt(arg)
            msg = "Custom prompt set."
        await ws.send(json.dumps({"type": "status", "content": msg}))
        return

    conn.history.append({"role": "user", "content": user_msg})

    loop = asyncio.get_event_loop()
    confirm_fn = make_web_confirm_fn(ws, conn, loop)

    def on_stream_chunk(text):
        asyncio.run_coroutine_threadsafe(
            ws.send(json.dumps({"type": "stream", "content": text})),
            loop,
        ).result()

    def on_tool_start(name, tool_input):
        status = tools.tool_status_text(name, tool_input)
        asyncio.run_coroutine_threadsafe(
            ws.send(json.dumps({
                "type": "tool_status",
                "content": status,
                "tool": name,
            })),
            loop,
        ).result(timeout=5)

    def on_tool_end(name):
        asyncio.run_coroutine_threadsafe(
            ws.send(json.dumps({"type": "tool_end", "tool": name})),
            loop,
        ).result(timeout=5)

    try:
        result = await loop.run_in_executor(
            None,
            lambda: conversation.run_conversation_turn(
                conn.history,
                conn.active_model,
                confirm_fn=confirm_fn,
                on_stream_chunk=on_stream_chunk,
                on_tool_start=on_tool_start,
                on_tool_end=on_tool_end,
                query=user_msg,
            ),
        )

        conn.session_input_tokens += result["input_tokens"]
        conn.session_output_tokens += result["output_tokens"]
        conn.session_cost += result["cost"]
        conn.session_cache_creation_tokens += result["cache_creation_tokens"]
        conn.session_cache_read_tokens += result["cache_read_tokens"]

        short_model = models.MODEL_SHORT_NAMES.get(conn.active_model, conn.active_model)
        await ws.send(json.dumps({
            "type": "response",
            "content": result["text"],
            "model": short_model,
            "input_tokens": result["input_tokens"],
            "output_tokens": result["output_tokens"],
            "cost": round(result["cost"], 6),
            "session_cost": round(conn.session_cost, 4),
            "cache_creation_tokens": conn.session_cache_creation_tokens,
            "cache_read_tokens": conn.session_cache_read_tokens,
        }))

        # Context compression — prevent unbounded history growth
        compression = models.compress_conversation(history=conn.history)
        if compression:
            old_tok, new_tok, removed, kept, new_history = compression
            conn.history = new_history
            conn.compressions += 1
            await ws.send(json.dumps({
                "type": "status",
                "content": f"Context compressed: ~{old_tok:,} \u2192 ~{new_tok:,} tokens "
                           f"({removed} exchanges summarized, {kept} kept).",
            }))

    except anthropic.BadRequestError as e:
        msg = str(e)
        if "too long" in msg or "token" in msg.lower():
            await ws.send(json.dumps({
                "type": "error",
                "content": "Message too long for the context window. Starting a new conversation.",
            }))
            _save_conversation(conn)
            conn.history = []
        else:
            await ws.send(json.dumps({
                "type": "error",
                "content": f"Request error: {msg}",
            }))
    except anthropic.RateLimitError:
        await ws.send(json.dumps({
            "type": "error",
            "content": "Rate limited by the API. Please wait a moment and try again.",
        }))
    except anthropic.APIConnectionError:
        await ws.send(json.dumps({
            "type": "error",
            "content": "Cannot reach the Anthropic API. Check your internet connection.",
        }))
    except anthropic.AuthenticationError:
        await ws.send(json.dumps({
            "type": "error",
            "content": "Invalid API key. Check ANTHROPIC_API_KEY in .env.",
        }))
    except anthropic.InternalServerError:
        await ws.send(json.dumps({
            "type": "error",
            "content": "Anthropic API is temporarily unavailable. Try again shortly.",
        }))
    except Exception as e:
        await ws.send(json.dumps({
            "type": "error",
            "content": f"Unexpected error: {type(e).__name__}",
        }))


def _save_conversation(conn):
    """Save a connection's conversation history via the shared core."""
    if len(conn.history) >= 2:
        try:
            return models.save_conversation(conn.history)
        except Exception:
            pass
    return None


def _list_conversations():
    """Return conversation list for the sidebar."""
    filenames = memory.list_conversations()
    entries = []
    for f in reversed(filenames):
        # Filenames are YYYY-MM-DD_slug.txt
        name = f.replace(".txt", "")
        parts = name.split("_", 1)
        date = parts[0] if parts else ""
        title = parts[1].replace("-", " ") if len(parts) > 1 else name
        entries.append({"filename": f, "title": title, "date": date})
    return entries


async def handle_file_upload(ws, conn, data):
    """Handle file uploads from the web client (drag-and-drop)."""
    uploaded = data.get("files", [])
    if not uploaded:
        await ws.send(json.dumps({
            "type": "file_upload_result",
            "content": "No files received.",
            "success_count": 0,
            "error_count": 0,
        }))
        return

    success_count = 0
    error_count = 0
    results = []

    for item in uploaded:
        name = item.get("name", "")
        contents = item.get("contents", "")

        ok, ext = files.validate_extension(name)
        if not ok:
            results.append(f"Skipped {name}: unsupported type ({ext or 'no extension'})")
            error_count += 1
            continue

        try:
            filepath = files.write_file_contents(name, contents)
        except Exception as e:
            results.append(f"Failed to save {name}: {e}")
            error_count += 1
            continue

        # Inject into conversation history
        msg, filename, line_count = files.format_file_for_injection(filepath, contents)
        conn.history.append({"role": "user", "content": msg})
        results.append(f"Loaded {filename} ({line_count} lines)")
        success_count += 1

    summary = "\n".join(results)
    await ws.send(json.dumps({
        "type": "file_upload_result",
        "content": summary,
        "success_count": success_count,
        "error_count": error_count,
    }))


async def handler(ws):
    """Handle a single WebSocket connection."""
    conn = Connection()
    print(f"Client connected ({ws.remote_address})")

    try:
        # Send conversation list on connect
        await ws.send(json.dumps({
            "type": "conversation_list",
            "conversations": _list_conversations(),
        }))

        # Show suggested workflows on first connection after onboarding
        config = memory.load_config()
        if not config.get("suggestions_shown"):
            workflows = onboarding.get_suggested_workflows()
            if workflows:
                lines = "\n".join(f"  {i}. {s}" for i, s in enumerate(workflows, 1))
                await ws.send(json.dumps({
                    "type": "status",
                    "content": f"Based on your setup, try these first:\n{lines}",
                }))
                config["suggestions_shown"] = True
                memory.save_config(config)

        async for raw in ws:
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await ws.send(json.dumps({
                    "type": "error",
                    "content": "Invalid JSON",
                }))
                continue

            msg_type = data.get("type", "")

            if msg_type == "message":
                # Run as task so the dispatch loop continues to process
                # confirm_response messages while handle_message is awaiting
                # tool execution in the thread pool.
                asyncio.create_task(handle_message(ws, conn, data))

            elif msg_type == "new_chat":
                _save_conversation(conn)
                conn.history = []
                conn.session_input_tokens = 0
                conn.session_output_tokens = 0
                conn.session_cost = 0.0
                conn.session_cache_creation_tokens = 0
                conn.session_cache_read_tokens = 0
                conn.compressions = 0
                await ws.send(json.dumps({
                    "type": "status",
                    "content": "New conversation started.",
                }))
                await ws.send(json.dumps({
                    "type": "conversation_list",
                    "conversations": _list_conversations(),
                }))

            elif msg_type == "file_upload":
                await handle_file_upload(ws, conn, data)

            elif msg_type == "confirm_response":
                approved = data.get("approved", False)
                print(f"[confirm] Received confirm_response: approved={approved}, pending={conn._pending_confirm is not None}")
                if conn._pending_confirm:
                    conn._pending_confirm["holder"]["approved"] = approved
                    conn._pending_confirm["event"].set()

            elif msg_type == "set_model":
                model_id = data.get("model", "")
                # Accept short names (sonnet/haiku/opus) or full IDs
                resolved = MODEL_MAP.get(model_id, model_id)
                if resolved in models.MODELS.values():
                    conn.active_model = resolved
                    short = models.MODEL_SHORT_NAMES.get(resolved, resolved)
                    await ws.send(json.dumps({
                        "type": "status",
                        "content": f"Switched to {short}.",
                    }))
                else:
                    await ws.send(json.dumps({
                        "type": "error",
                        "content": f"Unknown model: {model_id}",
                    }))

            elif msg_type == "set_project":
                name = data.get("project", "")
                name = re.sub(r'[^\w-]', '-', name.lower()).strip('-')
                if not name:
                    # No name: return project list
                    projects = memory.list_projects()
                    active = conn.active_project
                    lines = [f"  {p} {'<<' if p == active else ''}" for p in projects]
                    await ws.send(json.dumps({
                        "type": "status",
                        "content": f"Projects:\n" + "\n".join(lines),
                    }))
                else:
                    conn.active_project = name
                    memory.active_project = name
                    memory.switch_project(name)
                    mems = memory.load_memories()
                    memory.memories = mems
                    mem_note = f" Loaded {len(mems)} memor{'y' if len(mems) == 1 else 'ies'}." if mems else ""
                    await ws.send(json.dumps({
                        "type": "status",
                        "content": f"Switched to project: {name}.{mem_note}",
                    }))

            else:
                await ws.send(json.dumps({
                    "type": "error",
                    "content": f"Unknown message type: {msg_type}",
                }))

    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        _save_conversation(conn)
        print(f"Client disconnected ({ws.remote_address})")


async def main(host="0.0.0.0", port=8765):
    """Start the WebSocket server."""
    # Load memories at startup
    combined, _, _ = memory.load_all_memories()
    memory.memories = combined

    print(f"First Contact WebSocket server listening on ws://{host}:{port}")
    print(f"Open web_ui/index.html in a browser to connect.")
    print(f"Loaded {len(memory.memories)} memories.")

    async with websockets.serve(handler, host, port):
        await asyncio.Future()  # Run forever


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="First Contact WebSocket server")
    parser.add_argument("--host", default="0.0.0.0", help="Bind address (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8765, help="Port (default: 8765)")
    args = parser.parse_args()

    try:
        asyncio.run(main(args.host, args.port))
    except KeyboardInterrupt:
        print("\nServer stopped.")
