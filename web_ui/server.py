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
import sys

# Add parent dir to path so we can import shared core
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import anthropic
import memory
import models
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
        self.session_input_tokens = 0
        self.session_output_tokens = 0
        self.session_cost = 0.0
        self.session_cache_creation_tokens = 0
        self.session_cache_read_tokens = 0
        self.compressions = 0


async def handle_message(ws, conn, data):
    """Handle an incoming 'message' request — stream API response, handle tool loop."""
    user_msg = data.get("content", "").strip()
    if not user_msg:
        return

    # Override model if client sent one (accept short names or full IDs)
    if data.get("model"):
        resolved = MODEL_MAP.get(data["model"], data["model"])
        if resolved in models.MODELS.values():
            conn.active_model = resolved

    conn.history.append({"role": "user", "content": user_msg})

    system_prompt = memory.build_system_prompt_cached(
        memory.memories, query=user_msg
    )

    total_input = 0
    total_output = 0
    total_cost = 0.0

    try:
        for turn in range(10):
            response_text = ""

            # Use synchronous streaming in a thread to avoid blocking the event loop
            final = await _stream_response(
                ws, conn, system_prompt
            )

            if final is None:
                # Streaming failed — error already sent to client
                return

            # Collect the full text from the final message
            for block in final.content:
                if block.type == "text":
                    response_text += block.text

            # Token accounting
            input_tokens = final.usage.input_tokens
            output_tokens = final.usage.output_tokens
            cache_creation = getattr(final.usage, 'cache_creation_input_tokens', 0) or 0
            cache_read = getattr(final.usage, 'cache_read_input_tokens', 0) or 0
            prices = models.PRICING.get(conn.active_model, {"input": 0, "output": 0})
            input_cost = input_tokens * prices["input"]
            output_cost = output_tokens * prices["output"]
            cache_write_cost = cache_creation * prices["input"] * models.CACHE_WRITE_MULTIPLIER
            cache_read_cost = cache_read * prices["input"] * models.CACHE_READ_MULTIPLIER
            msg_cost = (input_cost + output_cost + cache_write_cost + cache_read_cost) / 1_000_000
            total_input += input_tokens
            total_output += output_tokens
            total_cost += msg_cost
            conn.session_cache_creation_tokens += cache_creation
            conn.session_cache_read_tokens += cache_read

            if final.stop_reason == "tool_use":
                # Build assistant content for history
                assistant_content = []
                for block in final.content:
                    if block.type == "text":
                        assistant_content.append({"type": "text", "text": block.text})
                    elif block.type == "tool_use":
                        assistant_content.append({
                            "type": "tool_use",
                            "id": block.id,
                            "name": block.name,
                            "input": block.input,
                        })
                conn.history.append({"role": "assistant", "content": assistant_content})

                # Execute each tool
                tool_results = []
                for block in final.content:
                    if block.type == "tool_use":
                        status = tools.tool_status_text(block.name, block.input)
                        await ws.send(json.dumps({
                            "type": "tool_status",
                            "content": status,
                            "tool": block.name,
                        }))
                        result, is_error = tools.execute_tool(
                            block.name, block.input, confirm_fn=None
                        )
                        await ws.send(json.dumps({
                            "type": "tool_end",
                            "tool": block.name,
                        }))
                        tool_result = {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        }
                        if is_error:
                            tool_result["is_error"] = True
                        tool_results.append(tool_result)
                conn.history.append({"role": "user", "content": tool_results})
                continue
            else:
                # Normal end — add to history
                conn.history.append({"role": "assistant", "content": response_text})
                break

        # Update session totals
        conn.session_input_tokens += total_input
        conn.session_output_tokens += total_output
        conn.session_cost += total_cost

        short_model = models.MODEL_SHORT_NAMES.get(conn.active_model, conn.active_model)
        await ws.send(json.dumps({
            "type": "response",
            "content": response_text,
            "model": short_model,
            "input_tokens": total_input,
            "output_tokens": total_output,
            "cost": round(total_cost, 6),
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
                "content": f"Context compressed: ~{old_tok:,} → ~{new_tok:,} tokens "
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


async def _stream_response(ws, conn, system_prompt):
    """Stream a single API call. Returns the final message or None on error."""
    try:
        # Run the synchronous streaming API in a thread
        loop = asyncio.get_event_loop()
        final = await loop.run_in_executor(
            None,
            lambda: _sync_stream(ws, conn, system_prompt, loop),
        )
        return final
    except anthropic.APIError:
        raise  # Let handle_message's specific handlers deal with these
    except Exception as e:
        await ws.send(json.dumps({
            "type": "error",
            "content": f"Streaming error: {type(e).__name__}",
        }))
        return None


def _sync_stream(ws, conn, system_prompt, loop):
    """Synchronous streaming call — runs in a thread pool executor."""
    with models.get_client().messages.stream(
        model=conn.active_model,
        max_tokens=4096,
        system=system_prompt,
        messages=conn.history,
        tools=tools.get_cached_tools(),
    ) as stream:
        for text in stream.text_stream:
            # Schedule the send on the event loop from this worker thread
            asyncio.run_coroutine_threadsafe(
                ws.send(json.dumps({"type": "stream", "content": text})),
                loop,
            ).result()
        return stream.get_final_message()


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
                await handle_message(ws, conn, data)

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
