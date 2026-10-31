from __future__ import annotations
from dataclasses import dataclass
from urllib.parse import urlparse
import httpx
from .config import settings


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    source: str
    quality: str


class SearchUnavailable(RuntimeError):
    pass


class SearchProvider:
    async def search(self, query: str) -> list[SearchResult]:
        raise NotImplementedError


class BraveSearchProvider(SearchProvider):
    HIGH_QUALITY = {"reuters.com", "apnews.com", "bbc.com", "theguardian.com", "nytimes.com", "washingtonpost.com", "britannica.com", "pbs.org", "history.com", "thehindu.com", "indianexpress.com", "moma.org", "nobelprize.org"}

    def __init__(self, api_key: str | None = None, client=None):
        self.api_key = api_key if api_key is not None else settings.brave_search_api_key
        self.client = client

    async def search(self, query: str) -> list[SearchResult]:
        if not self.api_key:
            raise SearchUnavailable("Search provider is not configured")
        try:
            if self.client:
                response = await self.client.get("https://api.search.brave.com/res/v1/web/search", params={"q": query, "count": 8}, headers={"X-Subscription-Token": self.api_key, "Accept": "application/json"})
            else:
                async with httpx.AsyncClient(timeout=8) as client:
                    response = await client.get("https://api.search.brave.com/res/v1/web/search", params={"q": query, "count": 8}, headers={"X-Subscription-Token": self.api_key, "Accept": "application/json"})
            response.raise_for_status()
            items = response.json().get("web", {}).get("results", [])
        except Exception as exc:
            raise SearchUnavailable("Search provider request failed") from exc
        found = []
        for item in items:
            url = item.get("url", "")
            host = (urlparse(url).hostname or "").lower().removeprefix("www.")
            root = ".".join(host.split(".")[-2:])
            found.append(SearchResult(item.get("title", "")[:400], url, item.get("description", "")[:1200], host, "high" if root in self.HIGH_QUALITY else "other"))
        return found


def get_search_provider() -> SearchProvider:
    return BraveSearchProvider()
