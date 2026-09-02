"""Pluggable web-search backends used to harvest candidate retailer domains.

All backends degrade to a no-op when their API key is absent, so discovery
never breaks a run and the watcher works fine with zero search credentials
configured (it just relies on the seeded store list).

Backends, selected by ``STOCKWATCHER_SEARCH_BACKEND`` or auto-detected:
    ``brave``   -> ``BRAVE_SEARCH_API_KEY``
    ``bing``    -> ``BING_SEARCH_API_KEY`` (+ optional ``BING_SEARCH_ENDPOINT``)
    ``serpapi`` -> ``SERPAPI_API_KEY``
    ``none``    -> no-op
"""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from urllib.parse import urlsplit

from ..http import HttpClient

log = logging.getLogger(__name__)


class SearchBackend(ABC):
    name = "base"

    @abstractmethod
    async def search(self, query: str, *, limit: int = 20) -> list[str]:
        """Return result URLs for ``query``."""

    @property
    def enabled(self) -> bool:
        return True


class NullSearchBackend(SearchBackend):
    """Used when no API key is configured."""

    name = "none"

    async def search(self, query: str, *, limit: int = 20) -> list[str]:
        return []

    @property
    def enabled(self) -> bool:
        return False


class BraveSearchBackend(SearchBackend):
    name = "brave"
    endpoint = "https://api.search.brave.com/res/v1/web/search"

    def __init__(self, http: HttpClient, api_key: str) -> None:
        self.http = http
        self.api_key = api_key

    async def search(self, query: str, *, limit: int = 20) -> list[str]:
        response = await self.http.get(
            self.endpoint,
            params={"q": query, "count": min(limit, 20)},
            headers={"X-Subscription-Token": self.api_key, "Accept": "application/json"},
        )
        if response.status_code != 200:
            log.debug("brave search %r -> HTTP %s", query, response.status_code)
            return []
        payload = response.json()
        results = (payload.get("web") or {}).get("results") or []
        return [str(r.get("url")) for r in results if r.get("url")]


class BingSearchBackend(SearchBackend):
    name = "bing"

    def __init__(self, http: HttpClient, api_key: str, endpoint: str | None = None) -> None:
        self.http = http
        self.api_key = api_key
        self.endpoint = endpoint or os.getenv(
            "BING_SEARCH_ENDPOINT", "https://api.bing.microsoft.com/v7.0/search"
        )

    async def search(self, query: str, *, limit: int = 20) -> list[str]:
        response = await self.http.get(
            self.endpoint,
            params={"q": query, "count": min(limit, 50), "mkt": "en-US"},
            headers={"Ocp-Apim-Subscription-Key": self.api_key},
        )
        if response.status_code != 200:
            log.debug("bing search %r -> HTTP %s", query, response.status_code)
            return []
        payload = response.json()
        results = (payload.get("webPages") or {}).get("value") or []
        return [str(r.get("url")) for r in results if r.get("url")]


class SerpApiSearchBackend(SearchBackend):
    name = "serpapi"
    endpoint = "https://serpapi.com/search.json"

    def __init__(self, http: HttpClient, api_key: str) -> None:
        self.http = http
        self.api_key = api_key

    async def search(self, query: str, *, limit: int = 20) -> list[str]:
        response = await self.http.get(
            self.endpoint,
            params={"q": query, "num": min(limit, 30), "api_key": self.api_key, "gl": "us"},
        )
        if response.status_code != 200:
            log.debug("serpapi search %r -> HTTP %s", query, response.status_code)
            return []
        payload = response.json()
        results = payload.get("organic_results") or []
        return [str(r.get("link")) for r in results if r.get("link")]


def build_search_backend(http: HttpClient, backend: str = "auto") -> SearchBackend:
    """Instantiate the configured backend, or a no-op when unconfigured."""
    choice = (os.getenv("STOCKWATCHER_SEARCH_BACKEND") or backend or "auto").lower()

    def brave() -> SearchBackend | None:
        key = os.getenv("BRAVE_SEARCH_API_KEY")
        return BraveSearchBackend(http, key) if key else None

    def bing() -> SearchBackend | None:
        key = os.getenv("BING_SEARCH_API_KEY")
        return BingSearchBackend(http, key) if key else None

    def serpapi() -> SearchBackend | None:
        key = os.getenv("SERPAPI_API_KEY")
        return SerpApiSearchBackend(http, key) if key else None

    builders = {"brave": brave, "bing": bing, "serpapi": serpapi}

    if choice in builders:
        built = builders[choice]()
        if built is None:
            log.info("search backend %r has no API key configured; discovery is a no-op", choice)
            return NullSearchBackend()
        return built
    if choice in ("none", "null", "off"):
        return NullSearchBackend()

    for builder in (brave, bing, serpapi):
        built = builder()
        if built is not None:
            log.info("auto-selected %r search backend for discovery", built.name)
            return built
    log.info("no search API key configured; store discovery is a no-op")
    return NullSearchBackend()


def host_of(url: str) -> str | None:
    """Extract a lowercase hostname from a URL."""
    try:
        host = urlsplit(url).hostname
    except ValueError:  # pragma: no cover - defensive
        return None
    return host.lower() if host else None
