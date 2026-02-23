"""Google Custom Search provider.

Best result quality. Free tier: 100 queries/day, $5 per 1,000 after that.
Requires GOOGLE_SEARCH_API_KEY and GOOGLE_SEARCH_CX in .env.

API docs: https://developers.google.com/custom-search/v1/overview
"""

import os

import requests

from search_providers import SearchProvider


class GoogleProvider(SearchProvider):

    API_URL = "https://www.googleapis.com/customsearch/v1"

    @property
    def name(self):
        return "google"

    def search(self, query, max_results=5):
        api_key = os.environ.get("GOOGLE_SEARCH_API_KEY")
        cx = os.environ.get("GOOGLE_SEARCH_CX")
        if not api_key or not cx:
            raise ValueError(
                "Google Custom Search requires GOOGLE_SEARCH_API_KEY and "
                "GOOGLE_SEARCH_CX in .env. See https://developers.google.com/custom-search/v1/overview"
            )

        resp = requests.get(
            self.API_URL,
            params={"key": api_key, "cx": cx, "q": query, "num": min(max_results, 10)},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

        results = []
        for item in data.get("items", []):
            results.append({
                "title": item.get("title", ""),
                "url": item.get("link", ""),
                "snippet": item.get("snippet", ""),
            })
        return results[:max_results]
