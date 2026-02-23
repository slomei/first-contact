"""DuckDuckGo search provider.

Default provider — no API key needed, works out of the box.

Uses the duckduckgo-search (ddgs) library, which is an unofficial scraper.
It reverse-engineers DuckDuckGo's endpoints and may break if DDG changes them.
The library also uses browser impersonation (primp) which generates stderr
warnings that are suppressed here.
"""

import contextlib
import io

try:
    from ddgs import DDGS
except ImportError:
    DDGS = None

from search_providers import SearchProvider


class DuckDuckGoProvider(SearchProvider):

    @property
    def name(self):
        return "duckduckgo"

    def search(self, query, max_results=5):
        if DDGS is None:
            return []
        with contextlib.redirect_stderr(io.StringIO()):
            raw = DDGS().text(query, max_results=max_results)
        if not raw:
            return []
        return [
            {"title": r.get("title", ""), "url": r.get("href", ""), "snippet": r.get("body", "")}
            for r in raw
        ]
