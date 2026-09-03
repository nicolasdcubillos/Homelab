"""CLI entrypoints: ``portfoliowatcher daily`` and ``portfoliowatcher weekly``."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import UTC, datetime, timedelta

from dotenv import load_dotenv

from .config import PortfolioConfig, load_config
from .llm_pipeline import AzureOpenAIClient, LLMPipeline
from .news_ingestion import NewsIngestor
from .notifier import Notifier, NotifierError, build_notifier
from .prices import PriceProvider
from .reports import build_daily_report, build_weekly_report, portfolio_summary_text
from .state import StateStore

log = logging.getLogger("portfoliowatcher")


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _load_all(config_path: str) -> PortfolioConfig:
    load_dotenv()
    return load_config(config_path)


async def _dispatch(config: PortfolioConfig, message: str, *, dry_run: bool) -> None:
    if dry_run:
        print(message)
        return
    notifiers: list[Notifier] = [build_notifier(name) for name in config.notifiers]
    for notifier in notifiers:
        try:
            await notifier.send(message)
        except NotifierError:
            log.exception("notifier %s failed to send", notifier.name)
        finally:
            await notifier.aclose()


def run_daily(config_path: str, *, dry_run: bool) -> str:
    """Two-section daily subscription: risk alerts + strong recommendations."""
    config = _load_all(config_path)
    ingestor = NewsIngestor(sec_user_agent=config.sec_edgar_user_agent)
    llm_client = AzureOpenAIClient(config.azure_openai)

    with StateStore(config.state_path) as state:
        pipeline = LLMPipeline(llm_client, config.azure_openai, state=state)

        since = datetime.now(UTC) - timedelta(days=1)
        all_items = ingestor.fetch_all(config.tickers(), since=since)

        unseen = [item for item in all_items if not state.is_seen(item.guid)]
        for item in unseen:
            state.mark_seen(item.guid, item.ticker, item.source)

        results = pipeline.process_items(unseen)
        report = build_daily_report(results)
        message = report.render()

    asyncio.run(_dispatch(config, message, dry_run=dry_run))
    return message


def run_weekly(config_path: str, *, dry_run: bool, force: bool = False) -> str:
    """Full portfolio analysis, run every ``analysis_interval_days``."""
    config = _load_all(config_path)
    price_provider = PriceProvider()
    llm_client = AzureOpenAIClient(config.azure_openai)

    with StateStore(config.state_path) as state:
        if not force:
            last_run = state.last_full_analysis_at()
            if last_run is not None:
                elapsed = datetime.now(UTC) - last_run
                if elapsed < timedelta(days=config.analysis_interval_days):
                    log.info(
                        "skipping weekly analysis: last run %s ago, interval is %s days",
                        elapsed,
                        config.analysis_interval_days,
                    )
                    return ""

        snapshots = price_provider.fetch_all(config.tickers())
        for ticker, snap in snapshots.items():
            state.record_price_snapshot(ticker, snap.price, snap.previous_close, snap.sector)

        pipeline = LLMPipeline(llm_client, config.azure_openai, state=state)
        summary = portfolio_summary_text(config, snapshots)
        narrative = pipeline.weekly_report(summary)
        message = build_weekly_report(narrative)

        state.mark_full_analysis_run()

    asyncio.run(_dispatch(config, message, dry_run=dry_run))
    return message


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="portfoliowatcher")
    parser.add_argument(
        "--config",
        default=os.getenv("PORTFOLIOWATCHER_CONFIG_PATH", "config/portfolio.yaml"),
        help="Path to portfolio.yaml",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print instead of sending")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")

    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("daily", help="Run the daily risk/opportunity subscription")

    weekly = subparsers.add_parser("weekly", help="Run the full portfolio analysis")
    weekly.add_argument("--force", action="store_true", help="Ignore the interval check")

    analyze = subparsers.add_parser(
        "analyze", help="Alias for weekly with a configurable interval override"
    )
    analyze.add_argument("--interval-days", type=int, default=None)
    analyze.add_argument("--force", action="store_true", help="Ignore the interval check")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)

    if args.command == "daily":
        run_daily(args.config, dry_run=args.dry_run)
    elif args.command == "weekly":
        run_weekly(args.config, dry_run=args.dry_run, force=args.force)
    elif args.command == "analyze":
        if args.interval_days is not None:
            os.environ["PORTFOLIOWATCHER_INTERVAL_OVERRIDE"] = str(args.interval_days)
        run_weekly(args.config, dry_run=args.dry_run, force=args.force)
    else:  # pragma: no cover - argparse enforces valid choices
        parser.error(f"unknown command {args.command!r}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
