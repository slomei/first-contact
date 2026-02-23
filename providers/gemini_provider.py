"""Gemini provider — wraps the Google GenAI SDK in an Anthropic-compatible surface."""

import json
import os
import uuid

try:
    from google import genai as _genai_sdk
    from google.genai import types as _genai_types
except ImportError:
    _genai_sdk = None
    _genai_types = None

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


class GeminiProvider(Provider):
    """Wraps Google GenAI SDK to look like anthropic.Anthropic()."""

    _raw_client = None

    @property
    def name(self):
        return "gemini"

    def _get_raw_client(self):
        if self._raw_client is None:
            if _genai_sdk is None:
                raise ImportError(
                    "google-genai package not installed. Install with: pip install google-genai"
                )
            self._raw_client = _genai_sdk.Client(
                api_key=os.environ.get("GEMINI_API_KEY", ""),
            )
        return self._raw_client

    def get_client(self):
        ns = MessagesNamespace(
            create_fn=self._create,
            stream_fn=self._stream,
        )
        return AnthropicCompatClient(ns)

    def get_tiers(self):
        return {
            "fast": "gemini-2.0-flash-lite",
            "standard": "gemini-2.0-flash",
            "quality": "gemini-2.5-pro",
        }

    def get_pricing(self):
        return {
            "gemini-2.5-pro":        {"input": 1.25, "output": 10.00},
            "gemini-2.0-flash":      {"input": 0.10, "output": 0.40},
            "gemini-2.0-flash-lite": {"input": 0.075, "output": 0.30},
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
        """Map Anthropic model IDs to Gemini equivalents via tier lookup."""
        tiers = self.get_tiers()
        tier = _ANTHROPIC_TO_TIER.get(model)
        if tier:
            return tiers[tier]
        return model

    def _extract_system(self, system):
        """Convert Anthropic system param to plain text for Gemini system_instruction."""
        if system is None:
            return None
        if isinstance(system, str):
            return system
        parts = []
        for block in system:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block["text"])
            elif isinstance(block, str):
                parts.append(block)
        return "\n\n".join(parts) if parts else None

    def _translate_tools(self, tools):
        """Convert Anthropic tool schemas to Gemini function declarations."""
        if not tools or _genai_types is None:
            return None
        declarations = []
        for tool in tools:
            schema = dict(tool.get("input_schema", {}))
            schema.pop("cache_control", None)
            # Remove unsupported JSON Schema fields
            schema.pop("additionalProperties", None)
            declarations.append(_genai_types.FunctionDeclaration(
                name=tool["name"],
                description=tool.get("description", ""),
                parameters=schema,
            ))
        return [_genai_types.Tool(function_declarations=declarations)]

    def _build_contents(self, messages):
        """Convert Anthropic messages to Gemini contents list."""
        if _genai_types is None:
            return []
        contents = []
        for msg in messages:
            role = "user" if msg["role"] == "user" else "model"
            content = msg["content"]

            if isinstance(content, str):
                contents.append(_genai_types.Content(
                    role=role,
                    parts=[_genai_types.Part.from_text(text=content)],
                ))
                continue

            if isinstance(content, list):
                parts = []
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "text":
                            parts.append(_genai_types.Part.from_text(text=block["text"]))
                        elif block.get("type") == "tool_use":
                            parts.append(_genai_types.Part.from_function_call(
                                name=block["name"],
                                args=block["input"],
                            ))
                        elif block.get("type") == "tool_result":
                            parts.append(_genai_types.Part.from_function_response(
                                name=block.get("tool_use_id", "unknown"),
                                response={"result": block.get("content", "")},
                            ))
                if parts:
                    contents.append(_genai_types.Content(role=role, parts=parts))
                continue

        return contents

    def _normalize_response(self, response):
        """Convert Gemini response to Anthropic-style Message."""
        content_blocks = []

        candidate = response.candidates[0] if response.candidates else None
        if candidate and candidate.content and candidate.content.parts:
            for part in candidate.content.parts:
                if hasattr(part, "text") and part.text:
                    content_blocks.append(TextBlock(part.text))
                elif hasattr(part, "function_call") and part.function_call:
                    fc = part.function_call
                    content_blocks.append(ToolUseBlock(
                        id=f"toolu_{uuid.uuid4().hex[:24]}",
                        name=fc.name,
                        input=dict(fc.args) if fc.args else {},
                    ))

        has_tool_calls = any(b.type == "tool_use" for b in content_blocks)
        stop_reason = "tool_use" if has_tool_calls else "end_turn"

        usage_meta = getattr(response, "usage_metadata", None)
        usage = Usage(
            input_tokens=getattr(usage_meta, "prompt_token_count", 0) if usage_meta else 0,
            output_tokens=getattr(usage_meta, "candidates_token_count", 0) if usage_meta else 0,
        )

        return Message(content_blocks, stop_reason, usage)

    # --- API methods ---

    def _create(self, **kwargs):
        """Translate and send a generate_content request."""
        client = self._get_raw_client()
        model = self._map_model(kwargs.get("model", "gemini-2.0-flash"))

        config_kwargs = {}
        max_tokens = kwargs.get("max_tokens")
        if max_tokens:
            config_kwargs["max_output_tokens"] = max_tokens

        system_text = self._extract_system(kwargs.get("system"))
        if system_text:
            config_kwargs["system_instruction"] = system_text

        tools = self._translate_tools(kwargs.get("tools"))
        if tools:
            config_kwargs["tools"] = tools

        config = _genai_types.GenerateContentConfig(**config_kwargs) if config_kwargs else None

        contents = self._build_contents(kwargs.get("messages", []))

        response = client.models.generate_content(
            model=model,
            contents=contents,
            config=config,
        )

        return self._normalize_response(response)

    def _stream(self, **kwargs):
        """Translate and send a streaming generate_content request."""
        client = self._get_raw_client()
        model = self._map_model(kwargs.get("model", "gemini-2.0-flash"))

        config_kwargs = {}
        max_tokens = kwargs.get("max_tokens")
        if max_tokens:
            config_kwargs["max_output_tokens"] = max_tokens

        system_text = self._extract_system(kwargs.get("system"))
        if system_text:
            config_kwargs["system_instruction"] = system_text

        tools = self._translate_tools(kwargs.get("tools"))
        if tools:
            config_kwargs["tools"] = tools

        config = _genai_types.GenerateContentConfig(**config_kwargs) if config_kwargs else None

        contents = self._build_contents(kwargs.get("messages", []))

        stream = client.models.generate_content_stream(
            model=model,
            contents=contents,
            config=config,
        )

        collected_text = []
        collected_tool_calls = []
        usage_data = {"prompt_tokens": 0, "completion_tokens": 0}

        def chunk_iter():
            for chunk in stream:
                if chunk.candidates and chunk.candidates[0].content:
                    for part in chunk.candidates[0].content.parts:
                        if hasattr(part, "text") and part.text:
                            collected_text.append(part.text)
                            yield part.text
                        elif hasattr(part, "function_call") and part.function_call:
                            fc = part.function_call
                            collected_tool_calls.append(ToolUseBlock(
                                id=f"toolu_{uuid.uuid4().hex[:24]}",
                                name=fc.name,
                                input=dict(fc.args) if fc.args else {},
                            ))
                usage_meta = getattr(chunk, "usage_metadata", None)
                if usage_meta:
                    usage_data["prompt_tokens"] = getattr(
                        usage_meta, "prompt_token_count", 0)
                    usage_data["completion_tokens"] = getattr(
                        usage_meta, "candidates_token_count", 0)

        def finalize():
            content_blocks = []
            full_text = "".join(collected_text)
            if full_text:
                content_blocks.append(TextBlock(full_text))
            content_blocks.extend(collected_tool_calls)
            stop_reason = "tool_use" if collected_tool_calls else "end_turn"
            usage = Usage(
                input_tokens=usage_data["prompt_tokens"],
                output_tokens=usage_data["completion_tokens"],
            )
            return Message(content_blocks, stop_reason, usage)

        return StreamWrapper(chunk_iter(), finalize)


register_provider("gemini", GeminiProvider)
