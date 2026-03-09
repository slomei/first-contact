"""Tavily search provider.

Built for AI agents. Free tier: 1,000 queries/month (basic search depth).
Requires TAVILY_API_KEY in .env.

API docs: https://docs.tavily.com/
"""

import os

from search_providers import SearchProvider

try:
    from tavily import TavilyClient
except ImportError:
    TavilyClient = None


class TavilyProvider(SearchProvider):

    @property
    def name(self):
        return "tavily"

    def search(self, query, max_results=5):
        api_key = os.environ.get("TAVILY_API_KEY")
        if not api_key:
            raise ValueError(
                "Tavily requires TAVILY_API_KEY in .env. "
                "Get a free key at https://tavily.com/"
            )
        if TavilyClient is None:
            raise ValueError(
                "Tavily requires the tavily-python package. "
                "Install with: pip install tavily-python"
            )

        client = TavilyClient(api_key=api_key)
        response = client.search(query, max_results=max_results, search_depth="basic")

        results = []
        for item in response.get("results", []):
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": item.get("content", ""),
            })
        return results[:max_results]
