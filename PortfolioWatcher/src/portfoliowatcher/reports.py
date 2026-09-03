"""Assembles the daily (2-section) message and the weekly portfolio report."""

from __future__ import annotations

from dataclasses import dataclass

from .config import PortfolioConfig
from .llm_pipeline import AnalysisResult
from .prices import PriceSnapshot, sector_concentration

DISCLAIMER = (
    "⚠️ Esto es información generada automáticamente para apoyar tu decisión. "
    "No es asesoría financiera y no se ejecuta ninguna orden de compra/venta."
)


@dataclass
class DailyReport:
    risk_alerts: list[AnalysisResult]
    opportunities: list[AnalysisResult]

    def render(self) -> str:
        lines = ["📊 *PortfolioWatcher — Resumen diario*", ""]
        lines.append(f"🔻 *Alertas de riesgo* ({len(self.risk_alerts)})")
        if self.risk_alerts:
            for result in self.risk_alerts:
                lines.append(_render_signal_line(result))
        else:
            lines.append("Sin alertas de riesgo relevantes hoy.")
        lines.append("")
        lines.append(f"🔺 *Recomendaciones fuertes* ({len(self.opportunities)})")
        if self.opportunities:
            for result in self.opportunities:
                lines.append(_render_signal_line(result))
        else:
            lines.append("Sin oportunidades destacadas hoy.")
        lines.append("")
        lines.append(DISCLAIMER)
        return "\n".join(lines)


def _render_signal_line(result: AnalysisResult) -> str:
    severity_emoji = {"low": "🟡", "medium": "🟠", "high": "🔴"}.get(result.severity, "⚪")
    return f"{severity_emoji} *{result.item.ticker}* ({result.severity}): {result.thesis}"


def build_daily_report(analysis_results: list[AnalysisResult]) -> DailyReport:
    """Split analysis results into the daily subscription's two sections.

    ``ruido`` items are already meant to be dropped by the pipeline, but any
    that slip through are excluded defensively here too.
    """
    risk_alerts = [r for r in analysis_results if r.signal_type == "riesgo"]
    opportunities = [r for r in analysis_results if r.signal_type == "oportunidad"]
    return DailyReport(risk_alerts=risk_alerts, opportunities=opportunities)


def portfolio_summary_text(config: PortfolioConfig, snapshots: dict[str, PriceSnapshot]) -> str:
    """Renders the raw data handed to the LLM for the weekly report — no LLM call here."""
    lines = ["Holdings actuales:"]
    weights: dict[str, float] = {}
    for holding in config.holdings:
        snap = snapshots.get(holding.ticker)
        price = snap.price if snap else None
        market_value = (price or holding.avg_cost) * holding.quantity
        weights[holding.ticker] = market_value
        change = f"{snap.change_pct:+.2f}%" if snap and snap.change_pct is not None else "N/D"
        if price:
            lines.append(
                f"- {holding.ticker}: {holding.quantity:g} unidades, costo prom. "
                f"${holding.avg_cost:.2f}, precio actual ${price:.2f}"
            )
        else:
            lines.append(f"- {holding.ticker}: precio no disponible")
        lines.append(f"  variación vs cierre anterior: {change}, sector: {holding.sector_hint}")

    concentration = sector_concentration(snapshots, weights)
    if concentration:
        lines.append("")
        lines.append("Concentración sectorial (por valor de mercado):")
        for sector, fraction in sorted(concentration.items(), key=lambda kv: -kv[1]):
            lines.append(f"- {sector}: {fraction * 100:.1f}%")

    lines.append("")
    lines.append(
        f"Perfil de riesgo: {config.risk_profile.tolerance} / {config.risk_profile.horizon}"
    )
    return "\n".join(lines)


def build_weekly_report(narrative: str) -> str:
    """Wraps the LLM-produced narrative with the same disclaimer used daily."""
    return "\n\n".join(
        [
            "📈 *PortfolioWatcher — Informe semanal de portafolio*",
            narrative.strip(),
            DISCLAIMER,
        ]
    )
