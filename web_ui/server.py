"""
WebSocket server for the First Contact web frontend.

Thin adapter — all logic in the shared core modules.
Each WebSocket connection gets its own conversation state.
"""

from dotenv import load_dotenv
load_dotenv()

import argparse
import asyncio
import base64
import json
import os
import re
import sys
import tempfile
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


# Short name -> full model ID (resolved from active provider's tiers)
def _get_model_map():
    return {
        "sonnet": models.get_tier("standard"),
        "haiku": models.get_tier("fast"),
        "opus": models.get_tier("quality"),
    }


class Connection:
    """Per-client state. Isolated from other connections and from models.py globals."""

    def __init__(self):
        self.history = []
        self.active_model = models.get_tier("standard")
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


def _extract_attached_files(attached_files):
    """Process attached files from a message.

    Returns list of tuples: (kind, name, content) where kind is "image" or "text".
    Image items have an API image block dict as content; text items have a string.
    """
    results = []
    for item in attached_files:
        name = item.get("name", "")
        contents = item.get("contents", "")
        ok, ext = files.validate_extension(name)
        if not ok:
            continue

        # Write to temp file for extraction (especially binary formats)
        try:
            if contents.startswith("data:") and ";base64," in contents:
                b64_data = contents.split(";base64,", 1)[1]
                raw_bytes = base64.b64decode(b64_data)
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
                tmp.write(raw_bytes)
                tmp.close()
            else:
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext, mode="w")
                tmp.write(contents)
                tmp.close()

            if files.is_image_file(tmp.name):
                image_block = files.encode_image_for_api(tmp.name)
                results.append(("image", name, image_block))
            else:
                extracted = files.read_file_contents(tmp.name)
                results.append(("text", name, f"[Attached file: {name}]\n```\n{extracted}\n```"))
        except Exception as e:
            results.append(("text", name, f"[Failed to extract {name}: {type(e).__name__}]"))
        finally:
            try:
                os.unlink(tmp.name)
            except Exception:
                pass

    return results


async def handle_message(ws, conn, data):
    """Handle an incoming 'message' request — stream API response, handle tool loop."""
    user_msg = data.get("content", "").strip()
    attached_files = data.get("files", [])

    # Process any attached files
    multimodal_appended = False
    if attached_files:
        extracted = _extract_attached_files(attached_files)
        if extracted:
            has_images = any(r[0] == "image" for r in extracted)
            if has_images:
                # Build multimodal content list
                content_blocks = []
                for kind, name, data_item in extracted:
                    if kind == "image":
                        content_blocks.append(data_item)  # image block dict
                    else:
                        content_blocks.append({"type": "text", "text": data_item})
                if user_msg:
                    content_blocks.append({"type": "text", "text": user_msg})
                conn.history.append({"role": "user", "content": content_blocks})
                multimodal_appended = True
                if not user_msg:
                    user_msg = f"[User attached {len(extracted)} file(s)]"
            else:
                # Text-only attachments
                file_block = "\n\n".join(r[2] for r in extracted)
                user_msg = file_block + ("\n\n" + user_msg if user_msg else "")

    if not user_msg and not multimodal_appended:
        return

    # Sync project state so system prompt uses the right project's memories
    memory.active_project = conn.active_project
    memory.memories = memory.load_memories()

    # Override model if client sent one (accept short names or full IDs)
    if data.get("model"):
        resolved = _get_model_map().get(data["model"], data["model"])
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

    if user_msg.startswith("/profile"):
        import user_model
        arg = user_msg[8:].strip().lower()
        if arg == "clear":
            user_model.clear_profile()
            msg = "User profile cleared."
        elif arg.startswith("remove "):
            target = arg[7:].strip()
            removed = user_model.remove_entry(target)
            if not removed:
                for e in user_model.load_profile():
                    if target.lower() in e.get("text", "").lower():
                        removed = user_model.remove_entry(e["id"])
                        break
            msg = "Entry removed." if removed else "No matching entry found."
        else:
            entries = user_model.load_profile()
            if not entries:
                msg = "No learned profile entries yet. These are extracted automatically from conversations."
            else:
                groups = {}
                for e in entries:
                    groups.setdefault(e.get("category", "facts"), []).append(e)
                labels = {"facts": "Facts", "preferences": "Preferences", "patterns": "Patterns", "goals": "Goals"}
                lines = [f"**Learned User Profile** ({len(entries)} entries)\n"]
                for cat in ["facts", "preferences", "patterns", "goals"]:
                    items = groups.get(cat, [])
                    if not items:
                        continue
                    lines.append(f"**{labels[cat]}:**")
                    for item in items:
                        conf = f" ({item['confidence']:.0%})" if item.get("confidence") else ""
                        lines.append(f"- {item['text']}{conf}")
                    lines.append("")
                msg = "\n".join(lines)
        await ws.send(json.dumps({"type": "status", "content": msg}))
        return

    if user_msg.strip().lower() == "/conversations clear":
        count = memory.clear_all_conversations()
        msg = f"Cleared {count} conversation{'s' if count != 1 else ''}."
        await ws.send(json.dumps({"type": "status", "content": msg}))
        return

    if not multimodal_appended:
        conn.history.append({"role": "user", "content": user_msg})

    loop = asyncio.get_event_loop()
    confirm_fn = make_web_confirm_fn(ws, conn, loop)

    def on_stream_chunk(text):
        asyncio.run_coroutine_threadsafe(
            ws.send(json.dumps({"type": "stream", "content": text})),
            loop,
        ).result()

    used_tools = set()

    def on_tool_start(name, tool_input):
        used_tools.add(name)
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

        await ws.send(json.dumps({
            "type": "response",
            "content": result["text"],
            "model": conn.active_model,
            "input_tokens": result["input_tokens"],
            "output_tokens": result["output_tokens"],
            "cost": round(result["cost"], 6),
            "session_cost": round(conn.session_cost, 4),
            "cache_creation_tokens": conn.session_cache_creation_tokens,
            "cache_read_tokens": conn.session_cache_read_tokens,
        }))

        # Refresh sidebar file list if any write tools were used
        if used_tools & FILE_WRITE_TOOLS:
            await send_file_list(ws, conn)

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
            result = models.save_conversation(conn.history)
        except Exception:
            result = None
        try:
            import user_model
            user_model.maybe_extract(conn.history)
        except Exception:
            pass
        return result
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
            if contents.startswith("data:") and ";base64," in contents:
                b64_data = contents.split(";base64,", 1)[1]
                raw_bytes = base64.b64decode(b64_data)
                filepath = files.write_binary_file_contents(name, raw_bytes)
            else:
                filepath = files.write_file_contents(name, contents)
        except Exception as e:
            results.append(f"Failed to save {name}: {e}")
            error_count += 1
            continue

        # Inject into conversation — images as multimodal, text as before
        if files.is_image_file(filepath):
            try:
                image_block = files.encode_image_for_api(filepath)
                content = [image_block, {"type": "text", "text": f"[File: {name}] (image uploaded to project files)"}]
                conn.history.append({"role": "user", "content": content})
                results.append(f"Loaded {name} (image)")
                success_count += 1
            except ValueError as e:
                results.append(f"Failed to process {name}: {e}")
                error_count += 1
        else:
            # Read back via read_file_contents (routes binary to parsers)
            try:
                text = files.read_file_contents(filepath)
            except Exception as e:
                results.append(f"Saved {name} but could not extract text: {e}")
                error_count += 1
                continue

            msg, filename, line_count = files.format_file_for_injection(filepath, text)
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


FILE_WRITE_TOOLS = {"write_file", "save_note", "generate_pdf", "create_docx", "create_xlsx"}


async def send_file_list(ws, conn):
    """Send the current project file list (files/ + workspace/) to the client."""
    entries = []

    # Project files (persistent uploads)
    memory.active_project = conn.active_project
    for f in files.list_project_files():
        entries.append({"name": f["name"], "dir": "files"})

    # Workspace files (tool-written)
    workspace_dir = memory.get_workspace_dir()
    try:
        for name in sorted(os.listdir(workspace_dir)):
            path = os.path.join(workspace_dir, name)
            if os.path.isfile(path):
                entries.append({"name": name, "dir": "workspace"})
    except OSError:
        pass

    await ws.send(json.dumps({"type": "file_list", "files": entries}))


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

        # Send available models from current provider
        model_map = _get_model_map()
        await ws.send(json.dumps({
            "type": "models",
            "models": {tier: model_id for tier, model_id in model_map.items()},
            "active": conn.active_model,
        }))

        # Send current project files for sidebar
        await send_file_list(ws, conn)

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
                await send_file_list(ws, conn)

            elif msg_type == "confirm_response":
                approved = data.get("approved", False)
                print(f"[confirm] Received confirm_response: approved={approved}, pending={conn._pending_confirm is not None}")
                if conn._pending_confirm:
                    conn._pending_confirm["holder"]["approved"] = approved
                    conn._pending_confirm["event"].set()

            elif msg_type == "set_model":
                model_id = data.get("model", "")
                # Accept short names (sonnet/haiku/opus) or full IDs
                resolved = _get_model_map().get(model_id, model_id)
                if resolved in models.MODELS.values():
                    conn.active_model = resolved
                    await ws.send(json.dumps({
                        "type": "model_set",
                        "model": resolved,
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
