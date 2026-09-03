from __future__ import annotations

from datetime import UTC, datetime

from portfoliowatcher.config import Holding, PortfolioConfig, RiskProfile
from portfoliowatcher.llm_pipeline import AnalysisResult
from portfoliowatcher.news_ingestion import NewsItem
from portfoliowatcher.prices import PriceSnapshot
from portfoliowatcher.reports import (
    build_daily_report,
    build_weekly_report,
    portfolio_summary_text,
)


def _analysis_result(ticker: str, signal_type: str, severity: str = "medium") -> AnalysisResult:
    item = NewsItem(
        ticker=ticker,
        source="google_news_rss",
        guid=f"guid-{ticker}",
        title="headline",
        link="https://example.com",
        published_at=datetime(2024, 1, 1, tzinfo=UTC),
    )
    return AnalysisResult(
        item=item,
        signal_type=signal_type,
        severity=severity,
        thesis=f"Thesis for {ticker}",
        raw_response="{}",
        prompt="prompt",
    )


def test_build_daily_report_splits_sections():
    results = [
        _analysis_result("AAPL", "riesgo", "high"),
        _analysis_result("MSFT", "oportunidad", "medium"),
        _analysis_result("VOO", "ruido"),
    ]
    report = build_daily_report(results)
    assert len(report.risk_alerts) == 1
    assert report.risk_alerts[0].item.ticker == "AAPL"
    assert len(report.opportunities) == 1
    assert report.opportunities[0].item.ticker == "MSFT"


def test_daily_report_render_includes_disclaimer_and_sections():
    report = build_daily_report([_analysis_result("AAPL", "riesgo", "high")])
    text = report.render()
    assert "Alertas de riesgo" in text
    assert "Recomendaciones fuertes" in text
    assert "AAPL" in text
    assert "no es asesoría financiera" in text.lower() or "no se ejecuta" in text.lower()
    assert "Sin oportunidades destacadas hoy." in text


def test_daily_report_render_empty_sections():
    report = build_daily_report([])
    text = report.render()
    assert "Sin alertas de riesgo relevantes hoy." in text
    assert "Sin oportunidades destacadas hoy." in text


def _config() -> PortfolioConfig:
    return PortfolioConfig(
        analysis_interval_days=7,
        risk_profile=RiskProfile(horizon="long_term", tolerance="moderate"),
        holdings=[
            Holding(ticker="AAPL", quantity=10, avg_cost=150.0, sector_hint="technology"),
            Holding(ticker="VOO", quantity=5, avg_cost=400.0, sector_hint="broad_market_etf"),
        ],
    )


def test_portfolio_summary_text_includes_concentration():
    snapshots = {
        "AAPL": PriceSnapshot(
            ticker="AAPL", price=200.0, previous_close=190.0, sector="Technology", industry="Hardware"
        ),
        "VOO": PriceSnapshot(
            ticker="VOO", price=420.0, previous_close=420.0, sector="Diversified", industry=None
        ),
    }
    summary = portfolio_summary_text(_config(), snapshots)
    assert "AAPL" in summary
    assert "Concentración sectorial" in summary
    assert "Technology" in summary
    assert "moderate / long_term" in summary


def test_build_weekly_report_wraps_narrative():
    message = build_weekly_report("Análisis del portafolio esta semana.")
    assert "Informe semanal de portafolio" in message
    assert "Análisis del portafolio esta semana." in message
    assert "no se ejecuta" in message.lower()
