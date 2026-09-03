from __future__ import annotations

import httpx
import pytest
import respx

from portfoliowatcher.news_ingestion import (
    GOOGLE_NEWS_RSS_URL,
    NewsIngestor,
    google_news_query,
)

SAMPLE_FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
  <title>"MSFT" stock - Google News</title>
  <item>
    <title>Microsoft beats earnings expectations</title>
    <link>https://example.com/news/msft-earnings</link>
    <guid>https://example.com/news/msft-earnings</guid>
    <pubDate>Mon, 01 Jan 2024 12:00:00 GMT</pubDate>
    <description>Microsoft reported strong quarterly results.</description>
  </item>
  <item>
    <title>Analyst upgrades Microsoft to buy</title>
    <link>https://example.com/news/msft-upgrade</link>
    <guid>https://example.com/news/msft-upgrade</guid>
    <pubDate>Tue, 02 Jan 2024 08:00:00 GMT</pubDate>
    <description>An analyst raised their rating on Microsoft shares.</description>
  </item>
</channel>
</rss>
"""


def test_google_news_query_is_specific():
    query = google_news_query("MSFT")
    assert '"MSFT"' in query
    assert "stock" in query


@respx.mock
def test_fetch_rss_uses_google_news_and_parses_entries():
    respx.get(url__startswith=GOOGLE_NEWS_RSS_URL).mock(
        return_value=httpx.Response(200, content=SAMPLE_FEED)
    )
    ingestor = NewsIngestor(sec_user_agent="Test test@example.com")
    items = ingestor.fetch_rss("MSFT")

    assert len(items) == 2
    assert items[0].ticker == "MSFT"
    assert items[0].source == "google_news_rss"
    assert "earnings" in items[0].title.lower()
    assert items[0].link == "https://example.com/news/msft-earnings"

    request = respx.calls.last.request
    assert "news.google.com/rss/search" in str(request.url)
    assert "MSFT" in str(request.url)


@respx.mock
def test_fetch_rss_returns_empty_on_http_error():
    respx.get(url__startswith=GOOGLE_NEWS_RSS_URL).mock(return_value=httpx.Response(404))
    ingestor = NewsIngestor(sec_user_agent="Test test@example.com")
    items = ingestor.fetch_rss("NVDA")
    assert items == []


@respx.mock
def test_fetch_sec_filings_skips_when_cik_not_found():
    respx.get("https://www.sec.gov/files/company_tickers.json").mock(
        return_value=httpx.Response(200, json={"0": {"ticker": "AAPL", "cik_str": 320193}})
    )
    ingestor = NewsIngestor(sec_user_agent="Test test@example.com")
    items = ingestor.fetch_sec_filings("NOPE")
    assert items == []


@respx.mock
def test_fetch_sec_filings_filters_material_forms():
    respx.get("https://www.sec.gov/files/company_tickers.json").mock(
        return_value=httpx.Response(200, json={"0": {"ticker": "MSFT", "cik_str": 789019}})
    )
    respx.get(url__regex=r"https://data\.sec\.gov/submissions/.*").mock(
        return_value=httpx.Response(
            200,
            json={
                "filings": {
                    "recent": {
                        "form": ["8-K", "4", "10-Q"],
                        "accessionNumber": ["0001-24-000001", "0001-24-000002", "0001-24-000003"],
                        "filingDate": ["2024-01-05", "2024-01-06", "2024-01-07"],
                        "primaryDocument": ["a.htm", "b.htm", "c.htm"],
                    }
                }
            },
        )
    )
    ingestor = NewsIngestor(sec_user_agent="Test test@example.com")
    items = ingestor.fetch_sec_filings("MSFT")
    assert len(items) == 2
    assert {item.title.split()[0] for item in items} == {"8-K", "10-Q"}
    assert all(item.source == "sec_edgar" for item in items)


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__])
