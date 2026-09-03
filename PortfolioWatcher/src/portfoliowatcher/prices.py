"""Thin wrapper around ``yfinance`` for prices, sectors and history snapshots."""

from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class PriceSnapshot:
    """A single point-in-time read for one ticker."""

    ticker: str
    price: float | None
    previous_close: float | None
    sector: str | None
    industry: str | None

    @property
    def change_pct(self) -> float | None:
        if self.price is None or not self.previous_close:
            return None
        return (self.price - self.previous_close) / self.previous_close * 100.0


class PriceProvider:
    """Fetches current price/sector data for tickers via yfinance.

    Wrapped behind a class (rather than bare module functions) so tests can
    substitute a fake provider without monkeypatching yfinance internals.
    """

    def fetch(self, ticker: str) -> PriceSnapshot:
        try:
            import yfinance as yf
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("yfinance is required for price lookups") from exc

        try:
            info = yf.Ticker(ticker).fast_info
            last_price = info.get("last_price")
            price = float(last_price) if last_price is not None else None
            previous_close = info.get("previous_close")
            prev_close = float(previous_close) if previous_close is not None else None
        except Exception:  # pragma: no cover - network/library variance
            log.exception("failed to fetch fast_info for %s", ticker)
            price, prev_close = None, None

        sector = industry = None
        try:
            full_info = yf.Ticker(ticker).get_info()
            sector = full_info.get("sector")
            industry = full_info.get("industry")
        except Exception:  # pragma: no cover - network/library variance
            log.debug("could not fetch sector/industry for %s", ticker)

        return PriceSnapshot(
            ticker=ticker,
            price=price,
            previous_close=prev_close,
            sector=sector,
            industry=industry,
        )

    def fetch_all(self, tickers: list[str]) -> dict[str, PriceSnapshot]:
        return {ticker: self.fetch(ticker) for ticker in tickers}


def sector_concentration(
    snapshots: dict[str, PriceSnapshot],
    weights: dict[str, float],
) -> dict[str, float]:
    """Return the fraction of portfolio value allocated to each sector.

    ``weights`` maps ticker -> current market value (quantity * price); tickers
    with unknown sector fall under ``"unknown"``.
    """
    total = sum(weights.values())
    if total <= 0:
        return {}
    totals: dict[str, float] = {}
    for ticker, value in weights.items():
        snap = snapshots.get(ticker)
        sector = (snap.sector if snap and snap.sector else "unknown") or "unknown"
        totals[sector] = totals.get(sector, 0.0) + value
    return {sector: value / total for sector, value in totals.items()}
