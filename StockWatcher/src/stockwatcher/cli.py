"""Command line interface.

stockwatcher run --dry-run          one scan, print alerts instead of sending
stockwatcher run                    one scan, send real notifications
stockwatcher discover --dry-run     force a discovery pass
stockwatcher probe <host> <query>   inspect one store's raw response
stockwatcher stores                 list the persisted store registry
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from .config import Config, ConfigError, load_config
from .http import HttpClient
from .models import Store
from .providers import build_provider
from .runner import Runner
from .state import build_state_store

log = logging.getLogger("stockwatcher")

DEFAULT_WATCHES = "config/watches.yaml"
DEFAULT_STORES = "config/stores.yaml"


def _setup_logging(verbose: bool, json_logs: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    if json_logs:
        logging.basicConfig(
            level=level,
            format='{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s",'
            '"msg":"%(message)s"}',
        )
    else:
        logging.basicConfig(level=level, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("azure").setLevel(logging.WARNING)


def _load(args: argparse.Namespace) -> Config:
    config = load_config(args.watches, args.stores)
    if getattr(args, "state_backend", None):
        config.state.backend = args.state_backend
    if getattr(args, "state_path", None):
        config.state.path = args.state_path
    if getattr(args, "concurrency", None):
        config.runtime.concurrency = args.concurrency
    if getattr(args, "store", None):
        wanted = {s.lower() for s in args.store}
        config.stores = [s for s in config.stores if s.host.lower() in wanted]
        if not config.stores:
            config.stores = [Store(host=h) for h in sorted(wanted)]
    if getattr(args, "watch", None):
        wanted = {w.lower() for w in args.watch}
        config.watches = [w for w in config.watches if w.name.lower() in wanted]
    return config


async def _cmd_run(args: argparse.Namespace) -> int:
    config = _load(args)
    if not config.watches:
        log.error("no watches selected")
        return 2
    if not config.stores:
        log.error("no stores configured; check %s", args.stores)
        return 2

    state = build_state_store(config.state)
    http = HttpClient(
        concurrency=config.runtime.concurrency,
        timeout=config.runtime.timeout,
        default_delay=config.runtime.default_delay,
        rate=config.runtime.rate,
        user_agent=config.runtime.user_agent,
    )
    async with state:
        runner = Runner(config, state, http, dry_run=args.dry_run)
        try:
            discover = False if args.no_discovery else (True if args.discover else None)
            summary = await runner.run(discover=discover)
        finally:
            await runner.aclose()
            await http.aclose()

    print(json.dumps({"summary": summary.as_dict()}, indent=2, default=str))
    if summary.new_hits == 0:
        print("\nNo new availability since the last run.")
    return 0


async def _cmd_discover(args: argparse.Namespace) -> int:
    from .discovery import discover_stores

    config = _load(args)
    state = build_state_store(config.state)
    http = HttpClient(
        concurrency=config.runtime.concurrency,
        timeout=config.runtime.timeout,
        rate=config.runtime.rate,
        user_agent=config.runtime.user_agent,
    )
    async with state:
        records = await state.list_stores()
        known = {s.host for s in config.stores} | {r.host for r in records}
        try:
            promoted = await discover_stores(
                watches=config.enabled_watches(),
                known_hosts=known,
                http=http,
                config=config.discovery,
                state=state,
            )
        finally:
            await http.aclose()

    if not promoted:
        print(
            "No new stores discovered (configure BRAVE_SEARCH_API_KEY / "
            "BING_SEARCH_API_KEY / SERPAPI_API_KEY to enable web search)."
        )
    for record in promoted:
        print(f"+ {record.host}  [{record.provider}/{record.country}]  {record.note}")
    return 0


async def _cmd_stores(args: argparse.Namespace) -> int:
    config = _load(args)
    state = build_state_store(config.state)
    async with state:
        records = await state.list_stores()

    print(f"{len(config.stores)} configured store(s), {len(records)} registry record(s)\n")
    for store in config.stores:
        flag = " " if store.enabled else "x"
        print(f"[{flag}] {store.host:38s} {store.provider:11s} {store.country}  (config)")
    for record in sorted(records, key=lambda r: r.host):
        if any(s.host == record.host for s in config.stores):
            continue
        flag = " " if record.enabled else "x"
        print(
            f"[{flag}] {record.host:38s} {record.provider:11s} {record.country}  "
            f"({record.source}, fails={record.fail_count})"
        )
    return 0


async def _cmd_probe(args: argparse.Namespace) -> int:
    """Inspect one store directly — the fastest way to debug a provider."""
    config = _load(args)
    store = next(
        (s for s in config.stores if s.host.lower() == args.host.lower()),
        Store(host=args.host.lower(), provider=args.provider),
    )
    if args.provider and store.provider != args.provider:
        store = Store(
            host=store.host,
            provider=args.provider,
            country=store.country,
            name=store.name,
            delay=store.delay,
            options=store.options,
        )

    http = HttpClient(
        concurrency=config.runtime.concurrency,
        timeout=config.runtime.timeout,
        rate=config.runtime.rate,
        user_agent=config.runtime.user_agent,
    )
    provider = build_provider(store, http)
    try:
        refs = await provider.search(args.query)
        print(f"{store.host} [{store.provider}] search {args.query!r} -> {len(refs)} result(s)")
        for ref in refs[: args.limit]:
            print(f"\n  {ref.title}\n  {ref.url}")
            product = await provider.fetch(ref)
            if product is None:
                print("    (no product payload)")
                continue
            in_stock = [v for v in product.variants if v.available]
            print(
                f"    price={product.price} currency={product.currency} "
                f"gender={product.gender.value} colorway={product.colorway}"
            )
            print(f"    variants: {len(product.variants)} total, {len(in_stock)} available")
            for variant in product.variants:
                mark = "IN STOCK" if variant.available else "  --    "
                size = f" -> {variant.size}" if variant.size else ""
                print(f"      [{mark}] {variant.label}{size}")
    finally:
        await provider.aclose()
        await http.aclose()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stockwatcher",
        description="Generic product availability watcher with WhatsApp alerts.",
    )
    parser.add_argument("--watches", default=DEFAULT_WATCHES, help="path to watches.yaml")
    parser.add_argument("--stores", default=DEFAULT_STORES, help="path to stores.yaml")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--json-logs", action="store_true", help="structured logs for Azure")
    parser.add_argument("--state-backend", choices=["sqlite", "azure_table", "none"])
    parser.add_argument("--state-path", help="sqlite database path")
    parser.add_argument("--concurrency", type=int)

    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run one availability pass")
    run.add_argument(
        "--dry-run",
        action="store_true",
        help="print alerts to the console instead of sending them",
    )
    run.add_argument("--discover", action="store_true", help="force a discovery pass this run")
    run.add_argument("--no-discovery", action="store_true", help="skip discovery this run")
    run.add_argument("--store", action="append", help="limit to these hosts (repeatable)")
    run.add_argument("--watch", action="append", help="limit to these watch names (repeatable)")
    run.set_defaults(func=_cmd_run)

    discover = sub.add_parser("discover", help="run store auto-discovery now")
    discover.set_defaults(func=_cmd_discover)

    stores = sub.add_parser("stores", help="list configured and discovered stores")
    stores.set_defaults(func=_cmd_stores)

    probe = sub.add_parser("probe", help="probe a single store (debugging)")
    probe.add_argument("host")
    probe.add_argument("query")
    probe.add_argument("--provider", default=None, help="override the provider")
    probe.add_argument("--limit", type=int, default=5)
    probe.set_defaults(func=_cmd_probe)

    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        from dotenv import load_dotenv

        env_file = Path(".env")
        if env_file.exists():
            load_dotenv(env_file)
    except ImportError:  # pragma: no cover - optional
        pass

    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose, args.json_logs)

    try:
        return asyncio.run(args.func(args))
    except ConfigError as exc:
        log.error("config error: %s", exc)
        return 2
    except KeyboardInterrupt:  # pragma: no cover
        return 130


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
