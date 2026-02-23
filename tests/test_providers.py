"""Tests for the provider abstraction layer.

All tests use mocks — no real API calls.
"""

import json
from unittest.mock import MagicMock, patch

import pytest


# --- Provider ABC and registry ---

def test_anthropic_provider_registered():
    import providers.anthropic_provider
    import providers
    assert "anthropic" in providers.list_providers()


def test_openai_provider_registered():
    import providers.openai_provider
    import providers
    assert "openai" in providers.list_providers()


def test_gemini_provider_registered():
    import providers.gemini_provider
    import providers
    assert "gemini" in providers.list_providers()


def test_factory_returns_correct_class():
    import providers.anthropic_provider
    import providers
    cls = providers.get_provider_class("anthropic")
    assert cls is providers.anthropic_provider.AnthropicProvider


def test_factory_returns_none_for_unknown():
    import providers
    assert providers.get_provider_class("fake_provider") is None


# --- Provider interface compliance ---

def test_anthropic_has_required_tiers():
    from providers.anthropic_provider import AnthropicProvider
    tiers = AnthropicProvider().get_tiers()
    assert "fast" in tiers
    assert "standard" in tiers
    assert "quality" in tiers


def test_openai_has_required_tiers():
    from providers.openai_provider import OpenAIProvider
    tiers = OpenAIProvider().get_tiers()
    assert "fast" in tiers
    assert "standard" in tiers
    assert "quality" in tiers


def test_gemini_has_required_tiers():
    from providers.gemini_provider import GeminiProvider
    tiers = GeminiProvider().get_tiers()
    assert "fast" in tiers
    assert "standard" in tiers
    assert "quality" in tiers


def test_anthropic_caching_enabled():
    from providers.anthropic_provider import AnthropicProvider
    features = AnthropicProvider().get_features()
    assert features["prompt_caching"] is True


def test_openai_caching_disabled():
    from providers.openai_provider import OpenAIProvider
    features = OpenAIProvider().get_features()
    assert features["prompt_caching"] is False


def test_gemini_caching_disabled():
    from providers.gemini_provider import GeminiProvider
    features = GeminiProvider().get_features()
    assert features["prompt_caching"] is False


def test_pricing_covers_tier_models():
    """Every tier model ID has a pricing entry."""
    from providers.anthropic_provider import AnthropicProvider
    from providers.openai_provider import OpenAIProvider
    from providers.gemini_provider import GeminiProvider

    for ProviderCls in (AnthropicProvider, OpenAIProvider, GeminiProvider):
        p = ProviderCls()
        tiers = p.get_tiers()
        pricing = p.get_pricing()
        for tier_name, model_id in tiers.items():
            assert model_id in pricing, f"{p.name}: tier '{tier_name}' model '{model_id}' not in pricing"


# --- Compat type tests ---

def test_message_has_expected_attributes():
    from providers.compat import Message, TextBlock, Usage
    usage = Usage(100, 50)
    msg = Message([TextBlock("hello")], "end_turn", usage)
    assert msg.content[0].type == "text"
    assert msg.content[0].text == "hello"
    assert msg.usage.input_tokens == 100
    assert msg.usage.output_tokens == 50
    assert msg.stop_reason == "end_turn"


def test_tool_use_block_attributes():
    from providers.compat import ToolUseBlock
    block = ToolUseBlock(id="toolu_123", name="web_search", input={"query": "test"})
    assert block.type == "tool_use"
    assert block.id == "toolu_123"
    assert block.name == "web_search"
    assert block.input == {"query": "test"}


def test_usage_cache_defaults_zero():
    from providers.compat import Usage
    usage = Usage(100, 50)
    assert usage.cache_creation_input_tokens == 0
    assert usage.cache_read_input_tokens == 0


def test_usage_cache_custom_values():
    from providers.compat import Usage
    usage = Usage(100, 50, cache_creation_input_tokens=30, cache_read_input_tokens=20)
    assert usage.cache_creation_input_tokens == 30
    assert usage.cache_read_input_tokens == 20


def test_stream_wrapper_context_manager():
    from providers.compat import StreamWrapper, Message, TextBlock, Usage

    chunks = ["Hello", " world"]
    final_msg = Message([TextBlock("Hello world")], "end_turn", Usage(10, 5))

    wrapper = StreamWrapper(iter(chunks), lambda: final_msg)
    with wrapper as stream:
        collected = list(stream.text_stream)
    assert collected == ["Hello", " world"]
    assert wrapper.get_final_message().content[0].text == "Hello world"


def test_anthropic_compat_client_structure():
    from providers.compat import AnthropicCompatClient, MessagesNamespace
    create_fn = MagicMock()
    stream_fn = MagicMock()
    ns = MessagesNamespace(create_fn, stream_fn)
    client = AnthropicCompatClient(ns)
    assert hasattr(client, "messages")
    assert hasattr(client.messages, "create")
    assert hasattr(client.messages, "stream")


# --- OpenAI translation tests ---

def test_openai_system_translation():
    """cache_control stripped, text blocks concatenated."""
    from providers.openai_provider import OpenAIProvider
    provider = OpenAIProvider()
    system = [
        {"type": "text", "text": "You are helpful.", "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "Be concise."},
    ]
    result = provider._translate_system(system)
    assert len(result) == 1
    assert result[0]["role"] == "system"
    assert "You are helpful." in result[0]["content"]
    assert "Be concise." in result[0]["content"]
    assert "cache_control" not in result[0]["content"]


def test_openai_tool_translation():
    """input_schema → function.parameters, cache_control stripped."""
    from providers.openai_provider import OpenAIProvider
    provider = OpenAIProvider()
    tools = [{
        "name": "web_search",
        "description": "Search the web",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "cache_control": {"type": "ephemeral"},
        },
    }]
    result = provider._translate_tools(tools)
    assert len(result) == 1
    assert result[0]["type"] == "function"
    assert result[0]["function"]["name"] == "web_search"
    assert "query" in result[0]["function"]["parameters"]["properties"]
    assert "cache_control" not in result[0]["function"]["parameters"]


def test_openai_message_translation_tool_result():
    """tool_result blocks → tool role messages."""
    from providers.openai_provider import OpenAIProvider
    provider = OpenAIProvider()
    messages = [{
        "role": "user",
        "content": [
            {"type": "tool_result", "tool_use_id": "toolu_123", "content": "search results"},
        ],
    }]
    result = provider._translate_messages(messages)
    assert len(result) == 1
    assert result[0]["role"] == "tool"
    assert result[0]["tool_call_id"] == "toolu_123"
    assert result[0]["content"] == "search results"


def test_openai_message_translation_tool_use():
    """tool_use blocks in assistant → tool_calls array."""
    from providers.openai_provider import OpenAIProvider
    provider = OpenAIProvider()
    messages = [{
        "role": "assistant",
        "content": [
            {"type": "tool_use", "id": "toolu_456", "name": "web_search", "input": {"query": "test"}},
        ],
    }]
    result = provider._translate_messages(messages)
    assert len(result) == 1
    assert result[0]["role"] == "assistant"
    assert len(result[0]["tool_calls"]) == 1
    assert result[0]["tool_calls"][0]["function"]["name"] == "web_search"


def test_openai_response_normalization():
    """ChatCompletion → Message with correct blocks."""
    from providers.openai_provider import OpenAIProvider
    provider = OpenAIProvider()

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "Hello!"
    mock_response.choices[0].message.tool_calls = None
    mock_response.usage.prompt_tokens = 100
    mock_response.usage.completion_tokens = 20

    msg = provider._normalize_response(mock_response)
    assert msg.content[0].type == "text"
    assert msg.content[0].text == "Hello!"
    assert msg.stop_reason == "end_turn"
    assert msg.usage.input_tokens == 100
    assert msg.usage.output_tokens == 20


def test_openai_response_normalization_tool_calls():
    """ChatCompletion with tool_calls → ToolUseBlock objects."""
    from providers.openai_provider import OpenAIProvider
    provider = OpenAIProvider()

    mock_tc = MagicMock()
    mock_tc.id = "call_123"
    mock_tc.function.name = "web_search"
    mock_tc.function.arguments = '{"query": "test"}'

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = None
    mock_response.choices[0].message.tool_calls = [mock_tc]
    mock_response.usage.prompt_tokens = 50
    mock_response.usage.completion_tokens = 10

    msg = provider._normalize_response(mock_response)
    assert msg.stop_reason == "tool_use"
    tool_blocks = [b for b in msg.content if b.type == "tool_use"]
    assert len(tool_blocks) == 1
    assert tool_blocks[0].name == "web_search"
    assert tool_blocks[0].input == {"query": "test"}


def test_openai_model_mapping():
    """Anthropic model IDs map to OpenAI equivalents."""
    from providers.openai_provider import OpenAIProvider
    provider = OpenAIProvider()
    assert provider._map_model("claude-haiku-4-5") == "gpt-4o-mini"
    assert provider._map_model("claude-sonnet-4-6") == "gpt-4o"
    assert provider._map_model("claude-opus-4-6") == "o3"
    # Unknown passthrough
    assert provider._map_model("gpt-4o") == "gpt-4o"


# --- Tier system tests ---

def test_tier_defaults_from_provider(monkeypatch):
    """get_tier returns the provider's default fast model."""
    import models
    # Reset provider state
    monkeypatch.setattr(models, "_provider", None)
    monkeypatch.setattr(models, "_client", None)
    monkeypatch.setattr(models, "_model_data_initialized", False)
    assert models.get_tier("fast") == "claude-haiku-4-5"
    assert models.get_tier("standard") == "claude-sonnet-4-6"
    assert models.get_tier("quality") == "claude-opus-4-6"


def test_config_tier_override(monkeypatch):
    """Config model_tiers overrides provider defaults."""
    import models
    import memory

    monkeypatch.setattr(models, "_provider", None)
    monkeypatch.setattr(models, "_client", None)
    monkeypatch.setattr(models, "_model_data_initialized", False)

    def mock_config():
        return {
            "provider": "anthropic",
            "model_tiers": {"fast": "custom-fast-model"},
        }
    monkeypatch.setattr(memory, "load_config", mock_config)

    assert models.get_tier("fast") == "custom-fast-model"
    assert models.get_tier("standard") == "claude-sonnet-4-6"


def test_get_provider_name(monkeypatch):
    """get_provider_name returns active provider."""
    import models
    monkeypatch.setattr(models, "_provider", None)
    monkeypatch.setattr(models, "_client", None)
    monkeypatch.setattr(models, "_model_data_initialized", False)
    assert models.get_provider_name() == "anthropic"


def test_get_provider_features(monkeypatch):
    """get_provider_features returns feature flags."""
    import models
    monkeypatch.setattr(models, "_provider", None)
    monkeypatch.setattr(models, "_client", None)
    monkeypatch.setattr(models, "_model_data_initialized", False)
    features = models.get_provider_features()
    assert features["prompt_caching"] is True
    assert features["batch_api"] is True


def test_reset_client_clears_state(monkeypatch):
    """reset_client() clears provider, client, and model data flag."""
    import models
    # Set some state
    monkeypatch.setattr(models, "_provider", "something")
    monkeypatch.setattr(models, "_client", "something")
    monkeypatch.setattr(models, "_model_data_initialized", True)

    models.reset_client()
    assert models._provider is None
    assert models._client is None
    assert models._model_data_initialized is False


# --- Integration test (mocked) ---

def test_get_client_returns_compat_client_for_openai(monkeypatch):
    """When provider is openai, its get_client returns AnthropicCompatClient."""
    from providers.compat import AnthropicCompatClient
    from providers.openai_provider import OpenAIProvider

    provider = OpenAIProvider()
    # Mock the raw OpenAI client so we don't need the SDK
    monkeypatch.setattr(provider, "_get_raw_client", lambda: MagicMock())

    client = provider.get_client()
    assert isinstance(client, AnthropicCompatClient)
    assert hasattr(client, "messages")
    assert hasattr(client.messages, "create")
    assert hasattr(client.messages, "stream")


def test_model_data_updates_for_openai(monkeypatch):
    """_init_model_data updates MODELS/PRICING when provider is openai."""
    import models
    import memory

    monkeypatch.setattr(models, "_provider", None)
    monkeypatch.setattr(models, "_client", None)
    monkeypatch.setattr(models, "_model_data_initialized", False)

    def mock_config():
        return {"provider": "openai"}
    monkeypatch.setattr(memory, "load_config", mock_config)

    # Trigger provider init without going through get_client (conftest mocks it)
    models._get_provider()
    models._init_model_data()

    assert models.MODELS["/haiku"] == "gpt-4o-mini"
    assert models.MODELS["/sonnet"] == "gpt-4o"
    assert models.MODELS["/opus"] == "o3"
    assert models.CACHE_WRITE_MULTIPLIER == 0.0
    assert models.CACHE_READ_MULTIPLIER == 0.0

    # Clean up
    models.reset_client()


def test_anthropic_cache_multipliers():
    """Anthropic provider returns non-zero cache multipliers."""
    from providers.anthropic_provider import AnthropicProvider
    write_mult, read_mult = AnthropicProvider().get_cache_multipliers()
    assert write_mult == 1.25
    assert read_mult == 0.10


def test_openai_cache_multipliers():
    """OpenAI provider returns zero cache multipliers (no caching)."""
    from providers.openai_provider import OpenAIProvider
    write_mult, read_mult = OpenAIProvider().get_cache_multipliers()
    assert write_mult == 0.0
    assert read_mult == 0.0


def test_gemini_cache_multipliers():
    """Gemini provider returns zero cache multipliers (no caching)."""
    from providers.gemini_provider import GeminiProvider
    write_mult, read_mult = GeminiProvider().get_cache_multipliers()
    assert write_mult == 0.0
    assert read_mult == 0.0
