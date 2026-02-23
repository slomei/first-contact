"""OpenAI provider — wraps the OpenAI SDK in an Anthropic-compatible surface."""

import json
import os
import uuid

try:
    import openai as _openai_sdk
except ImportError:
    _openai_sdk = None

from providers import Provider, register_provider
from providers.compat import (
    AnthropicCompatClient, Message, MessagesNamespace, StreamWrapper,
    TextBlock, ToolUseBlock, Usage,
)

# Map Anthropic model IDs → tier names for transparent passthrough
_ANTHROPIC_TO_TIER = {
    "claude-haiku-4-5": "fast",
    "claude-haiku-4-5-20251001": "fast",
    "claude-sonnet-4-6": "standard",
    "claude-sonnet-4-5-20250929": "standard",
    "claude-sonnet-4-5": "standard",
    "claude-opus-4-6": "quality",
}


class OpenAIProvider(Provider):
    """Wraps openai.OpenAI() to look like anthropic.Anthropic()."""

    _raw_client = None

    @property
    def name(self):
        return "openai"

    def _get_raw_client(self):
        if self._raw_client is None:
            if _openai_sdk is None:
                raise ImportError("openai package not installed. Install with: pip install openai")
            self._raw_client = _openai_sdk.OpenAI()
        return self._raw_client

    def get_client(self):
        ns = MessagesNamespace(
            create_fn=self._create,
            stream_fn=self._stream,
        )
        return AnthropicCompatClient(ns)

    def get_tiers(self):
        return {
            "fast": "gpt-4o-mini",
            "standard": "gpt-4o",
            "quality": "o3",
        }

    def get_pricing(self):
        return {
            "gpt-4o":      {"input": 2.50, "output": 10.00},
            "gpt-4o-mini": {"input": 0.15, "output": 0.60},
            "o3":          {"input": 10.00, "output": 40.00},
        }

    def get_features(self):
        return {
            "prompt_caching": False,
            "batch_api": False,
            "streaming": True,
            "tool_use": True,
        }

    # --- Translation helpers ---

    def _map_model(self, model):
        """Map Anthropic model IDs to OpenAI equivalents via tier lookup."""
        tiers = self.get_tiers()
        tier = _ANTHROPIC_TO_TIER.get(model)
        if tier:
            return tiers[tier]
        # Already an OpenAI model ID or unknown — pass through
        return model

    def _translate_system(self, system):
        """Convert Anthropic system param to OpenAI system message."""
        if system is None:
            return []
        if isinstance(system, str):
            return [{"role": "system", "content": system}]
        # List of content blocks (Anthropic cached prompt format)
        parts = []
        for block in system:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block["text"])
            elif isinstance(block, str):
                parts.append(block)
        if parts:
            return [{"role": "system", "content": "\n\n".join(parts)}]
        return []

    def _translate_tools(self, tools):
        """Convert Anthropic tool schemas to OpenAI function calling format."""
        if not tools:
            return None
        oai_tools = []
        for tool in tools:
            schema = dict(tool.get("input_schema", {}))
            schema.pop("cache_control", None)
            fn = {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": schema,
                },
            }
            oai_tools.append(fn)
        return oai_tools

    def _translate_messages(self, messages):
        """Convert Anthropic message format to OpenAI format."""
        oai_msgs = []
        for msg in messages:
            role = msg["role"]
            content = msg["content"]

            if isinstance(content, str):
                oai_msgs.append({"role": role, "content": content})
                continue

            if isinstance(content, list):
                # Assistant message with tool_use blocks
                if role == "assistant":
                    text_parts = []
                    tool_calls = []
                    for block in content:
                        if isinstance(block, dict):
                            if block.get("type") == "text":
                                text_parts.append(block["text"])
                            elif block.get("type") == "tool_use":
                                tool_calls.append({
                                    "id": block["id"],
                                    "type": "function",
                                    "function": {
                                        "name": block["name"],
                                        "arguments": json.dumps(block["input"]),
                                    },
                                })
                    assistant_msg = {"role": "assistant"}
                    if text_parts:
                        assistant_msg["content"] = "\n".join(text_parts)
                    else:
                        assistant_msg["content"] = None
                    if tool_calls:
                        assistant_msg["tool_calls"] = tool_calls
                    oai_msgs.append(assistant_msg)

                # User message with tool_result blocks
                elif role == "user":
                    for block in content:
                        if isinstance(block, dict):
                            if block.get("type") == "tool_result":
                                oai_msgs.append({
                                    "role": "tool",
                                    "tool_call_id": block.get("tool_use_id", ""),
                                    "content": block.get("content", ""),
                                })
                            elif block.get("type") == "text":
                                oai_msgs.append({
                                    "role": "user",
                                    "content": block["text"],
                                })
                continue

            oai_msgs.append({"role": role, "content": str(content)})
        return oai_msgs

    def _normalize_response(self, response):
        """Convert OpenAI ChatCompletion to Anthropic-style Message."""
        choice = response.choices[0]
        msg = choice.message

        content_blocks = []
        if msg.content:
            content_blocks.append(TextBlock(msg.content))

        if msg.tool_calls:
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except (json.JSONDecodeError, TypeError):
                    args = {}
                content_blocks.append(ToolUseBlock(
                    id=tc.id,
                    name=tc.function.name,
                    input=args,
                ))

        stop_reason = "tool_use" if msg.tool_calls else "end_turn"

        usage = Usage(
            input_tokens=getattr(response.usage, "prompt_tokens", 0),
            output_tokens=getattr(response.usage, "completion_tokens", 0),
        )

        return Message(content_blocks, stop_reason, usage)

    # --- API methods ---

    def _create(self, **kwargs):
        """Translate and send a create request."""
        client = self._get_raw_client()
        model = self._map_model(kwargs.get("model", "gpt-4o"))

        oai_kwargs = {
            "model": model,
            "max_tokens": kwargs.get("max_tokens", 4096),
        }

        # System prompt
        system_msgs = self._translate_system(kwargs.get("system"))

        # Messages
        user_msgs = self._translate_messages(kwargs.get("messages", []))
        oai_kwargs["messages"] = system_msgs + user_msgs

        # Tools
        tools = self._translate_tools(kwargs.get("tools"))
        if tools:
            oai_kwargs["tools"] = tools

        response = client.chat.completions.create(**oai_kwargs)
        return self._normalize_response(response)

    def _stream(self, **kwargs):
        """Translate and send a streaming request."""
        client = self._get_raw_client()
        model = self._map_model(kwargs.get("model", "gpt-4o"))

        oai_kwargs = {
            "model": model,
            "max_tokens": kwargs.get("max_tokens", 4096),
            "stream": True,
        }

        system_msgs = self._translate_system(kwargs.get("system"))
        user_msgs = self._translate_messages(kwargs.get("messages", []))
        oai_kwargs["messages"] = system_msgs + user_msgs

        tools = self._translate_tools(kwargs.get("tools"))
        if tools:
            oai_kwargs["tools"] = tools

        stream = client.chat.completions.create(**oai_kwargs)

        # Accumulate for final message
        collected_text = []
        collected_tool_calls = {}  # index -> {id, name, arguments}
        usage_data = {"prompt_tokens": 0, "completion_tokens": 0}

        def chunk_iter():
            for chunk in stream:
                if not chunk.choices:
                    # Usage chunk at end
                    if hasattr(chunk, "usage") and chunk.usage:
                        usage_data["prompt_tokens"] = getattr(chunk.usage, "prompt_tokens", 0)
                        usage_data["completion_tokens"] = getattr(chunk.usage, "completion_tokens", 0)
                    continue
                delta = chunk.choices[0].delta
                if delta.content:
                    collected_text.append(delta.content)
                    yield delta.content
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in collected_tool_calls:
                            collected_tool_calls[idx] = {
                                "id": tc.id or "",
                                "name": "",
                                "arguments": "",
                            }
                        if tc.id:
                            collected_tool_calls[idx]["id"] = tc.id
                        if tc.function:
                            if tc.function.name:
                                collected_tool_calls[idx]["name"] = tc.function.name
                            if tc.function.arguments:
                                collected_tool_calls[idx]["arguments"] += tc.function.arguments
                # Check for usage in chunk
                if hasattr(chunk, "usage") and chunk.usage:
                    usage_data["prompt_tokens"] = getattr(chunk.usage, "prompt_tokens", 0)
                    usage_data["completion_tokens"] = getattr(chunk.usage, "completion_tokens", 0)

        def finalize():
            content_blocks = []
            full_text = "".join(collected_text)
            if full_text:
                content_blocks.append(TextBlock(full_text))
            for idx in sorted(collected_tool_calls):
                tc = collected_tool_calls[idx]
                try:
                    args = json.loads(tc["arguments"])
                except (json.JSONDecodeError, TypeError):
                    args = {}
                content_blocks.append(ToolUseBlock(
                    id=tc["id"],
                    name=tc["name"],
                    input=args,
                ))
            stop_reason = "tool_use" if collected_tool_calls else "end_turn"
            usage = Usage(
                input_tokens=usage_data["prompt_tokens"],
                output_tokens=usage_data["completion_tokens"],
            )
            return Message(content_blocks, stop_reason, usage)

        return StreamWrapper(chunk_iter(), finalize)


register_provider("openai", OpenAIProvider)
