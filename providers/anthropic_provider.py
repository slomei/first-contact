"""Anthropic provider — zero-overhead pass-through to the native SDK."""

import anthropic

from providers import Provider, register_provider


class AnthropicProvider(Provider):
    """Returns the raw anthropic.Anthropic() client. No translation layer."""

    _client = None

    @property
    def name(self):
        return "anthropic"

    def get_client(self):
        if self._client is None:
            self._client = anthropic.Anthropic()
        return self._client

    def get_tiers(self):
        return {
            "fast": "claude-haiku-4-5",
            "standard": "claude-sonnet-4-6",
            "quality": "claude-opus-4-6",
        }

    def get_pricing(self):
        return {
            "claude-sonnet-4-5": {"input": 3.00, "output": 15.00},
            "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
            "claude-haiku-4-5":  {"input": 0.80, "output": 4.00},
            "claude-opus-4-6":   {"input": 15.00, "output": 75.00},
        }

    def get_features(self):
        return {
            "prompt_caching": True,
            "batch_api": True,
            "streaming": True,
            "tool_use": True,
        }

    def get_cache_multipliers(self):
        return (1.25, 0.10)


register_provider("anthropic", AnthropicProvider)
