"""SerpAPI search provider.

Power user option. Paid: starts at $50/month (has small trial).
Requires SERPAPI_KEY in .env.

API docs: https://serpapi.com/search-api
"""

import os

import requests

from search_providers import SearchProvider


class SerpAPIProvider(SearchProvider):

    API_URL = "https://serpapi.com/search"

    @property
    def name(self):
        return "serpapi"

    def search(self, query, max_results=5):
        api_key = os.environ.get("SERPAPI_KEY")
        if not api_key:
            raise ValueError(
                "SerpAPI requires SERPAPI_KEY in .env. "
                "Get a key at https://serpapi.com/"
            )

        resp = requests.get(
            self.API_URL,
            params={"q": query, "num": max_results, "api_key": api_key, "engine": "google"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

        results = []
        for item in data.get("organic_results", []):
            results.append({
                "title": item.get("title", ""),
                "url": item.get("link", ""),
                "snippet": item.get("snippet", ""),
            })
        return results[:max_results]
