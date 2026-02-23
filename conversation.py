"""
Shared conversation turn loop used by all interfaces.

Extracts the core API call -> tool use -> loop pattern into a single function.
Each interface provides callbacks for streaming, tool status, and confirmation.

Imports memory (base module), models, and tools at module level.
No circular dependency risk — nothing imports conversation.py.
"""

import memory
import models
import tools


def extract_last_user_query(conversation_history):
    """Extract the last user message text for semantic retrieval.

    Returns the text content of the most recent user message, or None.
    Handles both string and list-of-blocks content formats.
    """
    for msg in reversed(conversation_history):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, str):
                return content
            elif isinstance(content, list):
                texts = [b.get("text", "") for b in content if b.get("type") == "text"]
                return " ".join(texts) if texts else None
    return None


def run_conversation_turn(
    conversation_history,
    active_model,
    confirm_fn=None,
    on_stream_chunk=None,
    on_tool_start=None,
    on_tool_end=None,
    query=None,
    creative_context="",
    max_tool_turns=10,
):
    """Run a full conversation turn with tool-use loop.

    This is the core loop shared by all 4 interfaces:
      API call -> check stop reason -> handle tool use -> loop

    Parameters
    ----------
    conversation_history : list[dict]
        Mutated in place. Assistant and tool-result messages are appended.
    active_model : str
        Full model ID (e.g. "claude-sonnet-4-6").
    confirm_fn : callable(str) -> bool, optional
        Passed to tools.execute_tool for interactive confirmations.
    on_stream_chunk : callable(str) -> None, optional
        If provided, uses the streaming API and calls this for each text chunk.
        If None, uses the non-streaming create API.
    on_tool_start : callable(name, tool_input) -> None, optional
        Called before each tool execution.
    on_tool_end : callable(name) -> None, optional
        Called after each tool execution.
    query : str, optional
        Last user message text for semantic memory retrieval.
    creative_context : str
        Creative project context string (e.g. from first-light project).
    max_tool_turns : int
        Maximum number of tool-use loop iterations.

    Returns
    -------
    dict with keys:
        "text" : str — final assistant text response (empty string if interrupted)
        "input_tokens" : int
        "output_tokens" : int
        "cache_creation_tokens" : int
        "cache_read_tokens" : int
        "cost" : float — total cost in USD
    """
    total_input = 0
    total_output = 0
    total_cost = 0.0
    total_cache_creation = 0
    total_cache_read = 0

    system_prompt = memory.build_system_prompt_cached(
        memory.memories, creative_context=creative_context, query=query
    )
    cached_tools = tools.get_cached_tools()

    response_text = ""

    for turn in range(max_tool_turns):
        response_text = ""

        if on_stream_chunk is not None:
            # Streaming path
            final = _stream_call(
                active_model, system_prompt, conversation_history,
                cached_tools, on_stream_chunk,
            )
        else:
            # Non-streaming path
            final = models.get_client().messages.create(
                model=active_model,
                max_tokens=4096,
                system=system_prompt,
                messages=conversation_history,
                tools=cached_tools,
            )

        # Token accounting
        input_tokens = final.usage.input_tokens
        output_tokens = final.usage.output_tokens
        cache_creation = getattr(final.usage, 'cache_creation_input_tokens', 0) or 0
        cache_read = getattr(final.usage, 'cache_read_input_tokens', 0) or 0
        prices = models.PRICING.get(active_model, {"input": 0, "output": 0})
        input_cost = input_tokens * prices["input"]
        output_cost = output_tokens * prices["output"]
        cache_write_cost = cache_creation * prices["input"] * models.CACHE_WRITE_MULTIPLIER
        cache_read_cost = cache_read * prices["input"] * models.CACHE_READ_MULTIPLIER
        msg_cost = (input_cost + output_cost + cache_write_cost + cache_read_cost) / 1_000_000
        total_input += input_tokens
        total_output += output_tokens
        total_cache_creation += cache_creation
        total_cache_read += cache_read
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
            conversation_history.append({"role": "assistant", "content": assistant_content})

            # Execute each tool
            tool_results = []
            for block in final.content:
                if block.type == "tool_use":
                    if on_tool_start is not None:
                        on_tool_start(block.name, block.input)
                    result, is_error = tools.execute_tool(
                        block.name, block.input, confirm_fn=confirm_fn
                    )
                    if on_tool_end is not None:
                        on_tool_end(block.name)
                    tool_result = {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    }
                    if is_error:
                        tool_result["is_error"] = True
                    tool_results.append(tool_result)
            conversation_history.append({"role": "user", "content": tool_results})
            continue
        else:
            # Final text response
            for block in final.content:
                if block.type == "text":
                    response_text += block.text
            conversation_history.append({"role": "assistant", "content": response_text})
            break

    return {
        "text": response_text,
        "input_tokens": total_input,
        "output_tokens": total_output,
        "cache_creation_tokens": total_cache_creation,
        "cache_read_tokens": total_cache_read,
        "cost": total_cost,
    }


def _stream_call(model, system_prompt, messages, tools_list, on_chunk):
    """Run a streaming API call, feeding chunks to the callback.

    Returns the final message object. Propagates KeyboardInterrupt after
    appending partial text to history (caller is responsible for catching).
    """

    response_text = ""
    try:
        with models.get_client().messages.stream(
            model=model,
            max_tokens=4096,
            system=system_prompt,
            messages=messages,
            tools=tools_list,
        ) as stream:
            for text in stream.text_stream:
                on_chunk(text)
                response_text += text
            return stream.get_final_message()
    except KeyboardInterrupt:
        if response_text:
            messages.append({"role": "assistant", "content": response_text})
        raise
