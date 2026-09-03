"""Store auto-discovery.

This is what lets the watcher generalize beyond sneakers: point it at a new
product category and it finds that category's retailers by itself.

Every N runs (default 3):
  1. Web-search each watch's ``match`` terms to harvest candidate domains.
  2. Probe each candidate for ``/search/suggest.json``.  If it answers with
     valid Shopify JSON **and** contains a product matching the watch, promote
     it into the store registry with ``first_seen`` / ``last_ok`` /
     ``fail_count``.
  3. Stores that keep failing are auto-retired by the runner.

Where step 2 writes is pluggable — see :mod:`stockwatcher.discovery.registry`.
It defaults to the run's state store, but with several users each owning their
own state a shared append-only registry is what stops every user from paying
for the same discovery again.

Discovery runs after notifications and is fully exception-guarded, so it can
never block or slow the availability pass.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime

from ..config import DiscoveryConfig, Watch
from ..http import HttpClient
from ..matching import text_excluded, text_matches
from ..models import Store, StoreRecord
from ..providers.shopify import ShopifyProvider, looks_like_shopify
from ..state import StateStore
from .registry import (
    StateStoreRegistry,
    StoreRegistry,
    YamlStoreRegistry,
    build_store_registry,
)
from .search import SearchBackend, build_search_backend, host_of

log = logging.getLogger(__name__)

#: Marketplaces, aggregators, and social sites that are never useful as stores.
BLOCKED_HOST_SUFFIXES = (
    "amazon.com",
    "ebay.com",
    "walmart.com",
    "target.com",
    "google.com",
    "youtube.com",
    "facebook.com",
    "instagram.com",
    "tiktok.com",
    "twitter.com",
    "x.com",
    "reddit.com",
    "pinterest.com",
    "wikipedia.org",
    "stockx.com",
    "goat.com",
    "grailed.com",
    "poshmark.com",
    "mercari.com",
    "depop.com",
    "aliexpress.com",
    "etsy.com",
    "sneakernews.com",
    "solecollector.com",
    "hypebeast.com",
    "complex.com",
    "nicekicks.com",
    "kicksonfire.com",
    "sole retriever",
    "soleretriever.com",
    "medium.com",
    "quora.com",
    "linkedin.com",
    "yahoo.com",
    "bing.com",
)

SUGGEST_PATH = "/search/suggest.json"


def is_blocked(host: str) -> bool:
    return any(host == suffix or host.endswith("." + suffix) for suffix in BLOCKED_HOST_SUFFIXES)


def candidate_hosts(urls: Iterable[str], known: set[str]) -> list[str]:
    """Normalize search-result URLs into a deduped list of probe candidates."""
    seen: list[str] = []
    known_bare = {h.removeprefix("www.") for h in known}
    for url in urls:
        host = host_of(url)
        if not host or is_blocked(host):
            continue
        if host in known or host.removeprefix("www.") in known_bare:
            continue
        if host in seen:
            continue
        seen.append(host)
    return seen


async def probe_shopify(
    host: str,
    watch: Watch,
    http: HttpClient,
    *,
    timeout_marker: str | None = None,
) -> bool:
    """True when ``host`` is Shopify *and* sells something matching ``watch``."""
    store = Store(host=host, provider="shopify", source="discovery")
    provider = ShopifyProvider(store, http)
    for query in watch.search_queries[:2]:
        try:
            payload = await http.get_json(
                f"https://{host}{SUGGEST_PATH}",
                params={
                    "q": query,
                    "resources[type]": "product",
                    "resources[limit]": "10",
                },
            )
        except Exception as exc:
            log.debug("probe %s failed: %s", host, exc)
            return False
        if not looks_like_shopify(payload):
            return False
        for ref in provider.parse_search(payload):
            text = f"{ref.title} {ref.url}"
            if text_matches(watch, text) and not text_excluded(watch, text):
                return True
    return False


def discovery_queries(watch: Watch) -> list[str]:
    """Search-engine queries derived from a watch's match terms."""
    queries: list[str] = []
    for term in watch.match[:3]:
        queries.append(f"{term} buy online in stock")
        queries.append(f'"{term}" shop')
    return queries[:4]


async def discover_stores(
    *,
    watches: Sequence[Watch],
    known_hosts: set[str],
    http: HttpClient,
    config: DiscoveryConfig,
    state: StateStore,
    backend: SearchBackend | None = None,
    registry: StoreRegistry | None = None,
) -> list[StoreRecord]:
    """Harvest, probe and promote new Shopify stores.  Best-effort throughout.

    ``registry`` is where promotions land; it defaults to the one
    ``config.registry_path`` asks for (the state store when unset).  Whatever
    it already holds is added to ``known_hosts``, which is the point of a
    shared registry: a host somebody else already promoted is never probed
    again.
    """
    search = backend or build_search_backend(http, config.backend)
    if not search.enabled:
        return []
    if registry is None:
        registry = build_store_registry(config, state)

    promoted: list[StoreRecord] = []
    known = set(known_hosts) | await registry.known_hosts()

    for watch in watches:
        if len(promoted) >= config.max_promotions_per_run:
            break
        urls: list[str] = []
        for query in discovery_queries(watch):
            try:
                urls.extend(await search.search(query, limit=20))
            except Exception as exc:
                log.debug("search %r failed: %s", query, exc)
        candidates = candidate_hosts(urls, known)[: config.max_candidates]
        if not candidates:
            continue

        results = await asyncio.gather(
            *(probe_shopify(host, watch, http) for host in candidates),
            return_exceptions=True,
        )
        for host, ok in zip(candidates, results, strict=True):
            if isinstance(ok, BaseException) or not ok:
                continue
            record = StoreRecord(
                host=host,
                provider="shopify",
                country=_guess_country(host),
                enabled=True,
                first_seen=datetime.now(UTC),
                last_ok=datetime.now(UTC),
                fail_count=0,
                source="discovery",
                note=f"discovered via watch {watch.name!r}",
            )
            await registry.add(record)
            promoted.append(record)
            known.add(host)
            log.info("promoted store %s (watch %s)", host, watch.name)
            if len(promoted) >= config.max_promotions_per_run:
                break
    return promoted


_CCTLD_COUNTRY = {
    ".ca": "CA",
    ".co.uk": "GB",
    ".uk": "GB",
    ".de": "DE",
    ".fr": "FR",
    ".jp": "JP",
    ".au": "AU",
    ".it": "IT",
    ".es": "ES",
    ".mx": "MX",
    ".co": "CO",
}


def _guess_country(host: str) -> str:
    for suffix, country in _CCTLD_COUNTRY.items():
        if host.endswith(suffix):
            return country
    return "US"


__all__ = [
    "BLOCKED_HOST_SUFFIXES",
    "StateStoreRegistry",
    "StoreRegistry",
    "YamlStoreRegistry",
    "build_store_registry",
    "candidate_hosts",
    "discover_stores",
    "discovery_queries",
    "is_blocked",
    "probe_shopify",
]
