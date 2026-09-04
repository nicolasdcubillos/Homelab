"""The scan orchestrator.

One "run" = search every enabled store for every enabled watch, normalize what
comes back, diff it against stored state, and notify on the transitions.

Design constraints baked in here:

* A single failing store must never abort the run.
* Scanning ~40 stores must finish well under a minute -> everything is
  ``asyncio`` with a bounded semaphore in :class:`~stockwatcher.http.HttpClient`.
* Discovery runs *after* notifications so it can never slow down alerting.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime

from .config import Config, NotifyTarget, Watch
from .http import HttpClient, RateLimited
from .matching import build_observations, store_allowed, text_matches
from .models import Alert, Hit, Product, ProductRef, RunSummary, Store, StoreRecord
from .notifiers import Notifier, build_notifier, resolve_destinations
from .providers import ProviderError, build_provider
from .state import StateStore, detect_transitions

log = logging.getLogger(__name__)

#: What a watch notifies when it says nothing.
DEFAULT_NOTIFY = (NotifyTarget("whatsapp"),)


def merge_stores(config_stores: Sequence[Store], records: Iterable[StoreRecord]) -> list[Store]:
    """Config stores win on provider/country; the registry contributes discoveries."""
    records = list(records)
    by_host = {r.host: r for r in records}
    merged: dict[str, Store] = {}
    for store in config_stores:
        record = by_host.get(store.host)
        # A discovered store reaches the config list through the shared registry
        # (which is append-only, so it never retires anything).  Auto-retire is
        # per user and lives in their state, so honour it here or a store that
        # failed `retire_after_failures` times would be scanned forever.
        if store.source == "discovery" and record is not None and not record.enabled:
            continue
        merged[store.host] = store
    for record in records:
        if record.host in merged:
            continue
        if not record.enabled:
            continue
        merged[record.host] = record.to_store()
    return list(merged.values())


def _same_listing(left: Hit, right: Hit) -> bool:
    """True when two hits describe the same size of the same listing."""
    return (
        left.store_host == right.store_host
        and left.product_url == right.product_url
        and left.variant_label == right.variant_label
    )


def consolidate_queries(queries: Sequence[str], limit: int = 4) -> list[str]:
    """Drop queries whose results another query already covers.

    Store search is an implicit AND, so a query is redundant when a *broader*
    query (a subset of its tokens) is also being run: searching ``"mind 002"``
    already returns everything ``"nike mind 002"`` and ``"mind 002 flyknit"``
    would.  Collapsing these matters a lot in practice — firing seven near
    identical queries at one Shopify host trips its bot challenge and the store
    silently returns nothing.

    For the three Nike Mind watches this turns 7 queries into 3.
    """
    parsed = [(q, frozenset(q.lower().split())) for q in dict.fromkeys(queries) if q.strip()]
    # Broadest (fewest tokens) first so narrower supersets can be dropped.
    parsed.sort(key=lambda item: (len(item[1]), item[0]))

    kept: list[tuple[str, frozenset[str]]] = []
    for query, tokens in parsed:
        if any(existing <= tokens for _, existing in kept):
            continue
        kept.append((query, tokens))
    return [query for query, _ in kept[:limit]]


def _canonical(url: str) -> str:
    return url.split("?")[0].rstrip("/").lower()


def hit_detail(hit: Hit) -> dict:
    """Serialize one hit for the run summary (``stockwatcher run`` JSON output).

    Kept flat and self-contained — no lookup against watches/stores needed —
    so a caller like HomelabDashboard can render a result card straight from
    this dict without importing anything from this package.
    """
    return {
        "watch": hit.watch_name,
        "store": hit.store_name,
        "product": hit.product_title,
        "variant": hit.variant_label,
        "price": hit.price_text,
        "url": hit.product_url,
        "image": hit.image_url,
        "color_matched": hit.color_matched,
    }


class Runner:
    """Executes one availability pass."""

    def __init__(
        self,
        config: Config,
        state: StateStore,
        http: HttpClient,
        *,
        dry_run: bool = False,
        notifier_overrides: dict[tuple[str, tuple[str, ...]], Notifier] | None = None,
    ) -> None:
        self.config = config
        self.state = state
        self.http = http
        self.dry_run = dry_run
        self._notifiers: dict[tuple[str, tuple[str, ...]], Notifier] = dict(
            notifier_overrides or {}
        )
        self.summary = RunSummary()

    # ------------------------------------------------------------- notifiers

    def _notifier(self, target: NotifyTarget) -> Notifier:
        """Build (once) the notifier that serves ``target``.

        Notifiers are cached per *(channel, destination)*: two watches sending
        to the same address share one client and one message budget, while two
        watches pointed at different addresses stay separate.
        """
        if self.dry_run:
            channel, destinations = "console", []
        else:
            channel = target.channel.lower()
            destinations = resolve_destinations(
                channel,
                override=self.config.notify.override_to.get(channel),
                configured=list(target.to) or self.config.notify.to.get(channel),
            )
        key = (channel, tuple(destinations))
        if key not in self._notifiers:
            options = {
                "max_hits_per_message": self.config.notify.max_hits_per_message,
                "max_messages_per_run": self.config.notify.max_messages_per_run,
            }
            if destinations:
                options["to"] = list(destinations)
            self._notifiers[key] = build_notifier(channel, options)
        return self._notifiers[key]

    async def aclose(self) -> None:
        for notifier in self._notifiers.values():
            try:
                await notifier.aclose()
            except Exception as exc:  # pragma: no cover - defensive
                log.debug("notifier close failed: %s", exc)

    # ------------------------------------------------------------------ scan

    async def run(self, *, discover: bool | None = None) -> RunSummary:
        self.summary = RunSummary(started_at=datetime.now(UTC))
        run_number = await self.state.next_run_number()

        records = await self.state.list_stores()
        stores = merge_stores(self.config.enabled_stores(), records)
        watches = self.config.enabled_watches()
        log.info("run #%s: %s store(s) x %s watch(es)", run_number, len(stores), len(watches))

        results = await asyncio.gather(
            *(self._scan_store(store, watches) for store in stores),
            return_exceptions=True,
        )

        observations: list[tuple[Hit, bool]] = []
        fail_hosts: list[str] = []
        for store, result in zip(stores, results, strict=True):
            if isinstance(result, BaseException):
                self.summary.stores_failed += 1
                fail_hosts.append(store.host)
                message = f"{store.host}: {type(result).__name__}: {result}"
                self.summary.errors.append(message)
                log.warning("store failed: %s", message)
                continue
            self.summary.stores_scanned += 1
            observations.extend(result)

        self.summary.hits = sum(1 for _, available in observations if available)
        previous = await self.state.get_states(hit.key for hit, _ in observations)
        transition = detect_transitions(observations, previous)
        self.summary.new_hits = len(transition.new_hits)
        self.summary.hit_details = [hit_detail(hit) for hit in transition.new_hits]

        if transition.new_hits:
            await self._notify(transition.new_hits, watches)
        await self.state.set_states(transition.updates)
        await self._record_store_health(stores, fail_hosts, records)

        should_discover = self._should_discover(run_number) if discover is None else discover
        if should_discover:
            await self._discover(watches, stores)

        log.info("run summary: %s", self.summary.as_dict())
        return self.summary

    async def _scan_store(self, store: Store, watches: Sequence[Watch]) -> list[tuple[Hit, bool]]:
        relevant = [w for w in watches if store_allowed(w, store)]
        if not relevant:
            return []
        provider = build_provider(store, self.http)
        started = time.monotonic()
        try:
            refs = await self._collect_refs(provider, store, relevant)
            products = await self._fetch_products(provider, store, refs)
        finally:
            await provider.aclose()
            self.summary.store_seconds[store.host] = round(time.monotonic() - started, 1)

        observations: list[tuple[Hit, bool]] = []
        for product in products:
            self.summary.products_seen += 1
            self.summary.variants_seen += len(product.variants)
            for watch in relevant:
                observations.extend(build_observations(watch, product, store))
        return observations

    async def _collect_refs(
        self, provider, store: Store, watches: Sequence[Watch]
    ) -> list[ProductRef]:
        queries = consolidate_queries(
            [q for w in watches for q in w.search_queries],
            limit=self.config.runtime.max_queries_per_store,
        )
        # Sequential per store: these all hit the same host, and the client
        # serializes them anyway.  Running them as a gather only made the
        # request burst look more robotic.
        refs: dict[str, ProductRef] = {}
        failures: list[Exception] = []
        for query in queries:
            try:
                results = await provider.search(query)
            except RateLimited:
                # Being throttled means we learned nothing about this store;
                # bubble it up so the run summary shows it as a failure rather
                # than as "no stock".
                raise
            except Exception as exc:
                log.debug("%s search %r failed: %s", store.host, query, exc)
                failures.append(exc)
                continue
            for ref in results[: self.config.runtime.max_products_per_query]:
                if not self._ref_is_interesting(ref, watches):
                    continue
                refs.setdefault(_canonical(ref.url), ref)

        # One flaky query is tolerable; every query failing means the store told
        # us nothing at all.  Reporting that as "scanned, no stock" would hide a
        # broken store forever, because a clean scan resets its fail_count and
        # auto-retire would never fire.
        if failures and len(failures) == len(queries):
            raise failures[0]
        return list(refs.values())

    @staticmethod
    def _ref_is_interesting(ref: ProductRef, watches: Sequence[Watch]) -> bool:
        """Cheap pre-filter so we only pay for PDP fetches that can match."""
        haystack = f"{ref.title} {ref.handle or ''} {ref.url}"
        if not ref.title and not ref.handle:
            return True
        return any(text_matches(watch, haystack) for watch in watches)

    async def _fetch_products(
        self, provider, store: Store, refs: Sequence[ProductRef]
    ) -> list[Product]:
        products: list[Product] = []
        for ref in refs:
            try:
                product = await provider.fetch(ref)
            except Exception as exc:
                log.debug("%s fetch %s failed: %s", store.host, ref.url, exc)
                continue
            if product is not None:
                products.append(product)
        return products

    # -------------------------------------------------------------- notifying

    async def _notify(self, hits: Sequence[Hit], watches: Sequence[Watch]) -> None:
        targets_by_watch = {w.name: w.notify for w in watches}
        per_target: dict[NotifyTarget, list[Hit]] = {}
        for hit in hits:
            for target in targets_by_watch.get(hit.watch_name, DEFAULT_NOTIFY):
                bucket = per_target.setdefault(target, [])
                # Two watches can match the same listing (e.g. "mind 002" and
                # "mind 002 flyknit").  Send one message, not two identical ones.
                if any(_same_listing(hit, seen) for seen in bucket):
                    continue
                bucket.append(hit)

        for target, target_hits in per_target.items():
            try:
                notifier = self._notifier(target)
                before = getattr(notifier, "messages_sent", 0)
                await notifier.send(Alert(tuple(target_hits)))
                self.summary.hits_notified += len(target_hits)
                self.summary.messages_sent += getattr(notifier, "messages_sent", 0) - before
            except Exception as exc:
                message = f"notifier {target.channel}: {exc}"
                self.summary.errors.append(message)
                log.error("notification failed: %s", message)

    # ------------------------------------------------------------ bookkeeping

    async def _record_store_health(
        self,
        stores: Sequence[Store],
        fail_hosts: Sequence[str],
        records: Sequence[StoreRecord],
    ) -> None:
        by_host = {r.host: r for r in records}
        failed = set(fail_hosts)
        now = datetime.now(UTC)
        limit = self.config.discovery.retire_after_failures
        for store in stores:
            record = by_host.get(store.host)
            if record is None:
                record = StoreRecord(
                    host=store.host,
                    provider=store.provider,
                    country=store.country,
                    source=store.source,
                )
            if store.host in failed:
                record.fail_count += 1
                if record.source == "discovery" and record.fail_count >= limit:
                    record.enabled = False
                    record.note = f"auto-retired after {record.fail_count} failures"
                    log.info("retiring store %s", store.host)
            else:
                record.fail_count = 0
                record.last_ok = now
                record.enabled = True
                record.note = ""
            await self.state.upsert_store(record)

    def _should_discover(self, run_number: int) -> bool:
        discovery = self.config.discovery
        if not discovery.enabled:
            return False
        every = max(1, discovery.every_n_runs)
        return run_number % every == 1 % every if every > 1 else True

    async def _discover(self, watches: Sequence[Watch], stores: Sequence[Store]) -> None:
        from .discovery import discover_stores

        try:
            promoted = await discover_stores(
                watches=watches,
                known_hosts={s.host for s in stores},
                http=self.http,
                config=self.config.discovery,
                state=self.state,
            )
        except Exception as exc:  # pragma: no cover - discovery is best-effort
            self.summary.errors.append(f"discovery: {exc}")
            log.warning("discovery failed: %s", exc)
            return
        self.summary.discovered_stores = [record.host for record in promoted]
        if promoted:
            log.info(
                "discovered %s new store(s): %s",
                len(promoted),
                ", ".join(self.summary.discovered_stores),
            )


async def run_once(
    config: Config,
    state: StateStore,
    *,
    dry_run: bool = False,
    discover: bool | None = None,
) -> RunSummary:
    """Convenience entry point used by the CLI."""
    http = HttpClient(
        concurrency=config.runtime.concurrency,
        timeout=config.runtime.timeout,
        default_delay=config.runtime.default_delay,
        rate=config.runtime.rate,
        user_agent=config.runtime.user_agent,
    )
    runner = Runner(config, state, http, dry_run=dry_run)
    try:
        return await runner.run(discover=discover)
    finally:
        await runner.aclose()
        await http.aclose()


__all__ = ["ProviderError", "Runner", "hit_detail", "merge_stores", "run_once"]
