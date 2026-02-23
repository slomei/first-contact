"""Search provider abstraction layer.

Defines the SearchProvider ABC, registry, and factory for swapping between
DuckDuckGo, Brave, Google, and SerpAPI without changes outside the calling
modules (tools.py, job_scanner.py).

Same pattern as providers/__init__.py for LLM providers.
"""

from abc import ABC, abstractmethod

import memory

# --- Search Provider ABC ---


class SearchProvider(ABC):
    """Base class for all search providers.

    Every provider returns results in the same format:
    [{"title": str, "url": str, "snippet": str}, ...]
    """

    @property
    @abstractmethod
    def name(self):
        """Short provider name (e.g. 'duckduckgo', 'brave')."""
        ...

    @abstractmethod
    def search(self, query, max_results=5):
        """Search the web and return results.

        Returns:
            list[dict]: Each dict has 'title', 'url', 'snippet' keys.
            Empty list if no results or provider unavailable.
        """
        ...


# --- Registry ---

_registry = {}


def register_search_provider(name, cls):
    """Register a search provider class by name."""
    _registry[name] = cls


def get_search_provider_class(name):
    """Get a registered search provider class by name, or None."""
    return _registry.get(name)


def list_search_providers():
    """Return list of registered search provider names."""
    return list(_registry.keys())


# --- Factory ---

_cached_provider = None
_cached_provider_name = None


def get_search_provider():
    """Return the configured search provider instance.

    Reads 'search_provider' from config.json (default: 'duckduckgo').
    Caches the instance until the config changes.
    """
    global _cached_provider, _cached_provider_name

    cfg_name = memory.load_config().get("search_provider", "duckduckgo")

    if _cached_provider is not None and _cached_provider_name == cfg_name:
        return _cached_provider

    cls = _registry.get(cfg_name)
    if cls is None:
        available = ", ".join(sorted(_registry.keys())) or "(none)"
        raise ValueError(
            f"Unknown search provider: '{cfg_name}'. "
            f"Available: {available}"
        )

    _cached_provider = cls()
    _cached_provider_name = cfg_name
    return _cached_provider


# --- Auto-register providers on import ---

from search_providers.duckduckgo_provider import DuckDuckGoProvider
from search_providers.brave_provider import BraveProvider
from search_providers.google_provider import GoogleProvider
from search_providers.serpapi_provider import SerpAPIProvider

register_search_provider("duckduckgo", DuckDuckGoProvider)
register_search_provider("brave", BraveProvider)
register_search_provider("google", GoogleProvider)
register_search_provider("serpapi", SerpAPIProvider)
