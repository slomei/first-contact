"""
WebSocket server for the First Contact web frontend.

Thin adapter — all logic in the shared core modules.
Each WebSocket connection gets its own conversation state.
"""

import argparse
import asyncio
import json
import os
import sys

# Add parent dir to path so we can import shared core
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import memory
import models
import tools

try:
    import websockets
except ImportError:
    print("websockets not installed. Run: pip install websockets")
    sys.exit(1)


class Connection:
    """Per-client state. Isolated from other connections and from models.py globals."""

    def __init__(self):
        self.history = []
        self.active_model = "claude-sonnet-4-6"
        self.session_input_tokens = 0
        self.session_output_tokens = 0
        self.session_cost = 0.0


async def handle_message(ws, conn, data):
    """Handle an incoming 'message' request — stream API response, handle tool loop."""
    user_msg = data.get("content", "").strip()
    if not user_msg:
        return

    # Override model if client sent one
    if data.get("model") and data["model"] in models.MODELS.values():
        conn.active_model = data["model"]

    conn.history.append({"role": "user", "content": user_msg})

    system_prompt = memory.build_system_prompt(
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
            prices = models.PRICING.get(conn.active_model, {"input": 0, "output": 0})
            msg_cost = (input_tokens * prices["input"] + output_tokens * prices["output"]) / 1_000_000
            total_input += input_tokens
            total_output += output_tokens
            total_cost += msg_cost

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
                        }))
                        result, is_error = tools.execute_tool(
                            block.name, block.input, confirm_fn=None
                        )
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

        await ws.send(json.dumps({
            "type": "response",
            "content": response_text,
            "input_tokens": total_input,
            "output_tokens": total_output,
            "cost": round(total_cost, 6),
            "session_cost": round(conn.session_cost, 4),
        }))

    except Exception as e:
        await ws.send(json.dumps({
            "type": "error",
            "content": f"Error: {e}",
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
    except Exception as e:
        await ws.send(json.dumps({
            "type": "error",
            "content": f"API error: {e}",
        }))
        return None


def _sync_stream(ws, conn, system_prompt, loop):
    """Synchronous streaming call — runs in a thread pool executor."""
    with models.get_client().messages.stream(
        model=conn.active_model,
        max_tokens=4096,
        system=system_prompt,
        messages=conn.history,
        tools=tools.TOOLS,
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
                conn.history = []
                conn.session_input_tokens = 0
                conn.session_output_tokens = 0
                conn.session_cost = 0.0
                await ws.send(json.dumps({
                    "type": "status",
                    "content": "New conversation started.",
                }))

            elif msg_type == "set_model":
                model_id = data.get("model", "")
                if model_id in models.MODELS.values():
                    conn.active_model = model_id
                    short = models.MODEL_SHORT_NAMES.get(model_id, model_id)
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
