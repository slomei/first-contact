"""Tests for search provider abstraction — ABC, registry, all 5 providers."""

import pytest


# --- ABC and Registry ---

class TestSearchProviderABC:
    def test_all_providers_implement_abc(self):
        from search_providers import (
            DuckDuckGoProvider, BraveProvider, GoogleProvider, SerpAPIProvider,
            TavilyProvider,
        )
        for cls in (DuckDuckGoProvider, BraveProvider, GoogleProvider, SerpAPIProvider, TavilyProvider):
            provider = cls()
            assert hasattr(provider, "name")
            assert hasattr(provider, "search")
            assert callable(provider.search)

    def test_all_providers_have_name(self):
        from search_providers import (
            DuckDuckGoProvider, BraveProvider, GoogleProvider, SerpAPIProvider,
            TavilyProvider,
        )
        names = {cls().name for cls in (DuckDuckGoProvider, BraveProvider, GoogleProvider, SerpAPIProvider, TavilyProvider)}
        assert names == {"duckduckgo", "brave", "google", "serpapi", "tavily"}


class TestRegistry:
    def test_default_is_duckduckgo(self, monkeypatch):
        import search_providers
        import memory
        monkeypatch.setattr(memory, "load_config", lambda: {})
        # Clear cache
        search_providers._cached_provider = None
        search_providers._cached_provider_name = None
        provider = search_providers.get_search_provider()
        assert provider.name == "duckduckgo"

    def test_config_selects_brave(self, monkeypatch):
        import search_providers
        import memory
        monkeypatch.setattr(memory, "load_config", lambda: {"search_provider": "brave"})
        search_providers._cached_provider = None
        search_providers._cached_provider_name = None
        provider = search_providers.get_search_provider()
        assert provider.name == "brave"

    def test_unknown_provider_raises(self, monkeypatch):
        import search_providers
        import memory
        monkeypatch.setattr(memory, "load_config", lambda: {"search_provider": "nonexistent"})
        search_providers._cached_provider = None
        search_providers._cached_provider_name = None
        with pytest.raises(ValueError, match="Unknown search provider"):
            search_providers.get_search_provider()

    def test_list_search_providers(self):
        import search_providers
        providers = search_providers.list_search_providers()
        assert "duckduckgo" in providers
        assert "brave" in providers
        assert "google" in providers
        assert "serpapi" in providers
        assert "tavily" in providers

    def test_caching(self, monkeypatch):
        import search_providers
        import memory
        monkeypatch.setattr(memory, "load_config", lambda: {})
        search_providers._cached_provider = None
        search_providers._cached_provider_name = None
        p1 = search_providers.get_search_provider()
        p2 = search_providers.get_search_provider()
        assert p1 is p2


# --- DuckDuckGo ---

class TestDuckDuckGoProvider:
    def test_returns_correct_format(self, monkeypatch):
        from search_providers.duckduckgo_provider import DuckDuckGoProvider, DDGS
        if DDGS is None:
            pytest.skip("ddgs not installed")

        from search_providers import duckduckgo_provider

        class FakeDDGS:
            def text(self, query, max_results=5):
                return [
                    {"title": "Test", "href": "https://example.com", "body": "A test result"},
                ]
        monkeypatch.setattr(duckduckgo_provider, "DDGS", FakeDDGS)
        provider = DuckDuckGoProvider()
        results = provider.search("test")
        assert len(results) == 1
        assert results[0]["title"] == "Test"
        assert results[0]["url"] == "https://example.com"
        assert results[0]["snippet"] == "A test result"

    def test_returns_empty_when_ddgs_unavailable(self, monkeypatch):
        from search_providers import duckduckgo_provider
        monkeypatch.setattr(duckduckgo_provider, "DDGS", None)
        from search_providers.duckduckgo_provider import DuckDuckGoProvider
        provider = DuckDuckGoProvider()
        assert provider.search("test") == []


# --- Brave ---

class TestBraveProvider:
    def test_constructs_correct_request(self, monkeypatch):
        from search_providers.brave_provider import BraveProvider
        monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "test-key")

        captured = {}
        class FakeResponse:
            def raise_for_status(self): pass
            def json(self):
                return {"web": {"results": [
                    {"title": "Brave Result", "url": "https://brave.com", "description": "A brave result"},
                ]}}

        import requests
        def fake_get(url, headers=None, params=None, timeout=None):
            captured["url"] = url
            captured["headers"] = headers
            captured["params"] = params
            return FakeResponse()
        monkeypatch.setattr(requests, "get", fake_get)

        provider = BraveProvider()
        results = provider.search("test query", max_results=3)

        assert captured["url"] == "https://api.search.brave.com/res/v1/web/search"
        assert captured["headers"]["X-Subscription-Token"] == "test-key"
        assert captured["params"]["q"] == "test query"
        assert captured["params"]["count"] == 3
        assert len(results) == 1
        assert results[0] == {"title": "Brave Result", "url": "https://brave.com", "snippet": "A brave result"}

    def test_missing_key_raises(self, monkeypatch):
        from search_providers.brave_provider import BraveProvider
        monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
        with pytest.raises(ValueError, match="BRAVE_SEARCH_API_KEY"):
            BraveProvider().search("test")


# --- Google ---

class TestGoogleProvider:
    def test_constructs_correct_request(self, monkeypatch):
        from search_providers.google_provider import GoogleProvider
        monkeypatch.setenv("GOOGLE_SEARCH_API_KEY", "gkey")
        monkeypatch.setenv("GOOGLE_SEARCH_CX", "gcx")

        captured = {}
        class FakeResponse:
            def raise_for_status(self): pass
            def json(self):
                return {"items": [
                    {"title": "Google Result", "link": "https://google.com", "snippet": "A google result"},
                ]}

        import requests
        def fake_get(url, params=None, timeout=None):
            captured["url"] = url
            captured["params"] = params
            return FakeResponse()
        monkeypatch.setattr(requests, "get", fake_get)

        provider = GoogleProvider()
        results = provider.search("test", max_results=5)

        assert captured["params"]["key"] == "gkey"
        assert captured["params"]["cx"] == "gcx"
        assert captured["params"]["q"] == "test"
        assert len(results) == 1
        assert results[0] == {"title": "Google Result", "url": "https://google.com", "snippet": "A google result"}

    def test_missing_key_raises(self, monkeypatch):
        from search_providers.google_provider import GoogleProvider
        monkeypatch.delenv("GOOGLE_SEARCH_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_SEARCH_CX", raising=False)
        with pytest.raises(ValueError, match="GOOGLE_SEARCH_API_KEY"):
            GoogleProvider().search("test")

    def test_missing_cx_raises(self, monkeypatch):
        from search_providers.google_provider import GoogleProvider
        monkeypatch.setenv("GOOGLE_SEARCH_API_KEY", "gkey")
        monkeypatch.delenv("GOOGLE_SEARCH_CX", raising=False)
        with pytest.raises(ValueError, match="GOOGLE_SEARCH_CX"):
            GoogleProvider().search("test")


# --- SerpAPI ---

class TestSerpAPIProvider:
    def test_constructs_correct_request(self, monkeypatch):
        from search_providers.serpapi_provider import SerpAPIProvider
        monkeypatch.setenv("SERPAPI_KEY", "skey")

        captured = {}
        class FakeResponse:
            def raise_for_status(self): pass
            def json(self):
                return {"organic_results": [
                    {"title": "Serp Result", "link": "https://serp.com", "snippet": "A serp result"},
                ]}

        import requests
        def fake_get(url, params=None, timeout=None):
            captured["url"] = url
            captured["params"] = params
            return FakeResponse()
        monkeypatch.setattr(requests, "get", fake_get)

        provider = SerpAPIProvider()
        results = provider.search("test", max_results=5)

        assert captured["params"]["api_key"] == "skey"
        assert captured["params"]["q"] == "test"
        assert captured["params"]["engine"] == "google"
        assert len(results) == 1
        assert results[0] == {"title": "Serp Result", "url": "https://serp.com", "snippet": "A serp result"}

    def test_missing_key_raises(self, monkeypatch):
        from search_providers.serpapi_provider import SerpAPIProvider
        monkeypatch.delenv("SERPAPI_KEY", raising=False)
        with pytest.raises(ValueError, match="SERPAPI_KEY"):
            SerpAPIProvider().search("test")


# --- Tavily ---

class TestTavilyProvider:
    def test_constructs_correct_request(self, monkeypatch):
        from search_providers.tavily_provider import TavilyProvider
        from search_providers import tavily_provider
        monkeypatch.setenv("TAVILY_API_KEY", "tvly-test-key")

        captured = {}

        class FakeTavilyClient:
            def __init__(self, api_key):
                captured["api_key"] = api_key

            def search(self, query, max_results=5, search_depth="basic"):
                captured["query"] = query
                captured["max_results"] = max_results
                captured["search_depth"] = search_depth
                return {"results": [
                    {"title": "Tavily Result", "url": "https://tavily.com", "content": "A tavily result"},
                ]}

        monkeypatch.setattr(tavily_provider, "TavilyClient", FakeTavilyClient)

        provider = TavilyProvider()
        results = provider.search("test query", max_results=3)

        assert captured["api_key"] == "tvly-test-key"
        assert captured["query"] == "test query"
        assert captured["max_results"] == 3
        assert captured["search_depth"] == "basic"
        assert len(results) == 1
        assert results[0] == {"title": "Tavily Result", "url": "https://tavily.com", "snippet": "A tavily result"}

    def test_returns_correct_format(self, monkeypatch):
        from search_providers.tavily_provider import TavilyProvider
        from search_providers import tavily_provider
        monkeypatch.setenv("TAVILY_API_KEY", "tvly-test-key")

        class FakeTavilyClient:
            def __init__(self, api_key): pass
            def search(self, query, max_results=5, search_depth="basic"):
                return {"results": [
                    {"title": "First", "url": "https://one.com", "content": "First result"},
                    {"title": "Second", "url": "https://two.com", "content": "Second result"},
                ]}

        monkeypatch.setattr(tavily_provider, "TavilyClient", FakeTavilyClient)

        results = TavilyProvider().search("test")
        assert len(results) == 2
        for r in results:
            assert set(r.keys()) == {"title", "url", "snippet"}

    def test_missing_key_raises(self, monkeypatch):
        from search_providers.tavily_provider import TavilyProvider
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
        with pytest.raises(ValueError, match="TAVILY_API_KEY"):
            TavilyProvider().search("test")

    def test_missing_package_raises(self, monkeypatch):
        from search_providers.tavily_provider import TavilyProvider
        from search_providers import tavily_provider
        monkeypatch.setenv("TAVILY_API_KEY", "tvly-test-key")
        monkeypatch.setattr(tavily_provider, "TavilyClient", None)
        with pytest.raises(ValueError, match="tavily-python"):
            TavilyProvider().search("test")
