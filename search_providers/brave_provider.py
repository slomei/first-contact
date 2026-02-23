"""Brave Search provider.

Recommended upgrade from DuckDuckGo — official API, free tier (2,000 queries/month).
Requires BRAVE_SEARCH_API_KEY in .env.

API docs: https://api.search.brave.com/app/documentation/web-search
"""

import os

import requests

from search_providers import SearchProvider


class BraveProvider(SearchProvider):

    API_URL = "https://api.search.brave.com/res/v1/web/search"

    @property
    def name(self):
        return "brave"

    def search(self, query, max_results=5):
        api_key = os.environ.get("BRAVE_SEARCH_API_KEY")
        if not api_key:
            raise ValueError(
                "Brave Search requires BRAVE_SEARCH_API_KEY in .env. "
                "Get a free key at https://api.search.brave.com/"
            )

        resp = requests.get(
            self.API_URL,
            headers={"X-Subscription-Token": api_key, "Accept": "application/json"},
            params={"q": query, "count": max_results},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

        results = []
        for item in data.get("web", {}).get("results", []):
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": item.get("description", ""),
            })
        return results[:max_results]
