"""Provider abstraction layer.

Defines the Provider ABC, registry, and factory for swapping between
Anthropic, OpenAI, and Gemini without changes outside models.py.
"""

from abc import ABC, abstractmethod

# --- Provider ABC ---

class Provider(ABC):
    """Base class for all LLM providers."""

    @property
    @abstractmethod
    def name(self):
        """Short provider name (e.g. 'anthropic', 'openai', 'gemini')."""
        ...

    @abstractmethod
    def get_client(self):
        """Return a client with .messages.create() and .messages.stream()."""
        ...

    @abstractmethod
    def get_tiers(self):
        """Return model tier mapping: {"fast": str, "standard": str, "quality": str}."""
        ...

    @abstractmethod
    def get_pricing(self):
        """Return pricing dict: {model_id: {"input": float, "output": float}}."""
        ...

    @abstractmethod
    def get_features(self):
        """Return feature flags: {"prompt_caching": bool, "batch_api": bool, "streaming": bool, "tool_use": bool}."""
        ...

    def get_cache_multipliers(self):
        """Return (write_multiplier, read_multiplier) for prompt caching costs.

        Default (0.0, 0.0) — no caching overhead for providers that don't support it.
        """
        return (0.0, 0.0)


# --- Registry ---

_registry = {}


def register_provider(name, cls):
    """Register a provider class by name."""
    _registry[name] = cls


def get_provider_class(name):
    """Get a registered provider class by name, or None."""
    return _registry.get(name)


def list_providers():
    """Return list of registered provider names."""
    return list(_registry.keys())
