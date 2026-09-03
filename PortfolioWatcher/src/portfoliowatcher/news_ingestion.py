"""News ingestion: Google News RSS per ticker + SEC EDGAR filings.

Both sources are free and require no API key, only a well-formed User-Agent
for SEC EDGAR (required by SEC's fair-access policy). Google News RSS is
used instead of the classic Yahoo Finance RSS feed
(``feeds.finance.yahoo.com/rss/2.0/headline``), which Yahoo has deprecated
and now returns a 404 for every ticker.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import quote_plus

import httpx

log = logging.getLogger(__name__)

GOOGLE_NEWS_RSS_URL = "https://news.google.com/rss/search"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"

#: Filing types material enough to warrant a look at every run.
MATERIAL_FORMS = frozenset({"8-K", "10-Q", "10-K"})


def google_news_query(ticker: str) -> str:
    """Builds a query specific enough to avoid unrelated-ticker noise.

    Plain ``"{ticker}"`` alone pulls in a lot of generic chatter (forum
    posts, unrelated pages mentioning the letters), so the query is narrowed
    to results that also mention stock-related or filing-related terms.
    """
    return f'"{ticker}" (stock OR shares OR earnings OR SEC OR analyst)'


@dataclass
class NewsItem:
    """One news headline or SEC filing, normalized for the LLM pipeline."""

    ticker: str
    source: str  # "google_news_rss" | "sec_edgar"
    guid: str  # stable identifier used for de-duplication
    title: str
    link: str
    published_at: datetime
    summary: str = ""


class NewsIngestor:
    """Fetches raw news/filings for a set of tickers."""

    def __init__(self, sec_user_agent: str, timeout: float = 10.0) -> None:
        self.sec_user_agent = sec_user_agent or "PortfolioWatcher contact@example.com"
        self.timeout = timeout

    # ------------------------------------------------------------ Google News

    def fetch_rss(self, ticker: str) -> list[NewsItem]:
        try:
            import feedparser
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("feedparser is required for RSS ingestion") from exc

        query = quote_plus(google_news_query(ticker))
        url = f"{GOOGLE_NEWS_RSS_URL}?q={query}&hl=en-US&gl=US&ceid=US:en"
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.get(url)
                response.raise_for_status()
                raw = response.content
        except httpx.HTTPError:
            log.exception("failed to fetch Google News RSS for %s", ticker)
            return []

        parsed = feedparser.parse(raw)
        items: list[NewsItem] = []
        for entry in parsed.entries:
            published = _parse_rss_date(entry.get("published"))
            items.append(
                NewsItem(
                    ticker=ticker,
                    source="google_news_rss",
                    guid=entry.get("id") or entry.get("link", ""),
                    title=entry.get("title", ""),
                    link=entry.get("link", ""),
                    published_at=published,
                    summary=entry.get("summary", ""),
                )
            )
        return items

    # ----------------------------------------------------------- SEC EDGAR

    def fetch_sec_filings(self, ticker: str, since: datetime | None = None) -> list[NewsItem]:
        cik = self._lookup_cik(ticker)
        if cik is None:
            log.info("no SEC CIK found for %s; skipping EDGAR filings", ticker)
            return []

        url = SEC_SUBMISSIONS_URL.format(cik=cik)
        try:
            with httpx.Client(
                timeout=self.timeout, headers={"User-Agent": self.sec_user_agent}
            ) as client:
                response = client.get(url)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError:
            log.exception("failed to fetch SEC submissions for %s (CIK %s)", ticker, cik)
            return []

        recent = data.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        accession_numbers = recent.get("accessionNumber", [])
        filing_dates = recent.get("filingDate", [])
        primary_docs = recent.get("primaryDocument", [])

        items: list[NewsItem] = []
        for form, accession, filing_date, primary_doc in zip(
            forms, accession_numbers, filing_dates, primary_docs, strict=False
        ):
            if form not in MATERIAL_FORMS:
                continue
            published = datetime.strptime(filing_date, "%Y-%m-%d").replace(tzinfo=UTC)
            if since is not None and published < since:
                continue
            accession_nodash = accession.replace("-", "")
            link = (
                f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
                f"{accession_nodash}/{primary_doc}"
            )
            items.append(
                NewsItem(
                    ticker=ticker,
                    source="sec_edgar",
                    guid=accession,
                    title=f"{form} filing for {ticker}",
                    link=link,
                    published_at=published,
                    summary=f"{form} filed on {filing_date}",
                )
            )
        return items

    def _lookup_cik(self, ticker: str) -> str | None:
        """Resolve a ticker to its zero-padded 10-digit CIK via SEC's public map."""
        try:
            with httpx.Client(
                timeout=self.timeout, headers={"User-Agent": self.sec_user_agent}
            ) as client:
                response = client.get(SEC_TICKER_MAP_URL)
                response.raise_for_status()
                mapping = response.json()
        except httpx.HTTPError:
            log.exception("failed to fetch SEC ticker->CIK map")
            return None

        target = ticker.upper()
        for entry in mapping.values():
            if str(entry.get("ticker", "")).upper() == target:
                return str(entry.get("cik_str", "")).zfill(10)
        return None

    def fetch_all(self, tickers: list[str], since: datetime | None = None) -> list[NewsItem]:
        items: list[NewsItem] = []
        for ticker in tickers:
            items.extend(self.fetch_rss(ticker))
            items.extend(self.fetch_sec_filings(ticker, since=since))
        return items


def _parse_rss_date(value: str | None) -> datetime:
    if not value:
        return datetime.now(UTC)
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z"):
        try:
            parsed = datetime.strptime(value, fmt)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return parsed
        except ValueError:
            continue
    return datetime.now(UTC)
