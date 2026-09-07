"""Deterministic Spanish report: facts and abstentions, never generated citations."""

from __future__ import annotations

import datetime as dt
from html import escape
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from .schemas import Evidence, OfficialEvent, ReportData, ReportSection, SnapshotData

SECTION_TITLES = (
    "Que paso esta semana",
    "Macro y evolucion de publicaciones",
    "Fed y expectativas",
    "Rates: 2y/10y/curva",
    "Dollar: DXY/USDJPY",
    "Volatility: VIX/MOVE",
    "Equities: S&P/Nasdaq/Russell/Dow y futuros",
    "Credit: HY/IG OAS",
    "Cross-asset: opcionales y NFCI",
    "Risk Regime: tres horizontes y contribuciones",
    "Cambio de regimen",
    "Correccion o deterioro estructural",
    "Proxima semana",
)


def _summary(snapshot: SnapshotData) -> str:
    return "\n".join(
        f"{x.horizon}: {x.data_status}; "
        + (
            f"score {x.score:.2f}/100, {x.regime or 'sin estado confirmado'}"
            if x.score is not None
            else "abstencion, sin score ni clasificacion global"
        )
        + f"; confianza {x.confidence}; {x.calibration_status}."
        for x in snapshot.horizons
    )


def _category_text(snapshot: SnapshotData, name: str) -> str:
    lines = []
    for horizon in snapshot.horizons:
        category = next((x for x in horizon.categories if x.category == name), None)
        if category is None:
            lines.append(f"{horizon.horizon}: SIN_DATOS.")
            continue
        lines.append(f"{horizon.horizon}: {category.reason}")
        lines.extend(f"{item.series_id}: {item.reading}" for item in category.evidence)
    return "\n".join(lines)


def _changes(snapshot: SnapshotData, previous: SnapshotData | None) -> str:
    comparable = (
        previous is not None
        and previous.model_version == snapshot.model_version
        and previous.as_of < snapshot.as_of
        and previous.mode == snapshot.mode
    )
    lines = []
    old = {x.horizon: x for x in previous.horizons} if comparable else {}
    for current in snapshot.horizons:
        prior = old.get(current.horizon)
        if prior and prior.score is not None and current.score is not None:
            lines.append(
                f"{current.horizon}: score {prior.score:.2f} -> {current.score:.2f}; "
                f"delta {current.score - prior.score:+.2f}; {prior.regime} -> {current.regime}."
            )
            earlier = {x.category: x for x in prior.categories}
            for category in current.categories:
                before = earlier.get(category.category)
                if before and before.value is not None and category.value is not None:
                    if before.value != category.value:
                        lines.append(
                            f"{current.horizon}/{category.category}: "
                            f"{before.value:+.3f} -> {category.value:+.3f}; "
                            f"fuentes {[x.series_id for x in category.evidence]}."
                        )
        else:
            lines.append(
                f"{current.horizon}: sin anterior comparable/evaluable; no imputar cambio."
            )
        lines.extend(f"{current.horizon}: {x}" for x in current.changes)
    return "\n".join(lines)


def _safe_link(url: str) -> str:
    try:
        parsed = urlsplit(url)
        if (
            parsed.scheme not in ("https", "http")
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or any(ord(x) < 32 for x in url)
        ):
            return escape(url)
    except ValueError:
        return escape(url)
    return f'<a href="{escape(url, quote=True)}" rel="noopener noreferrer">{escape(url)}</a>'


def _event_reading(event: OfficialEvent) -> str:
    if event.timestamp_precision == "exact":
        when = event.event_at.astimezone(ZoneInfo("America/New_York")).isoformat()
    else:
        when = event.event_at.date().isoformat() + " (hora no verificada)"
    state = "PROGRAMADO; realizacion no confirmada" if event.scheduled else "REFERENCIA PUBLICADA"
    return (
        f"{when} | {state} | {event.kind} | {event.title} | "
        f"fuente={event.source_id}, evento={event.event_id} | {event.source_url}"
    )


def _event_sections(snapshot: SnapshotData) -> tuple[str, str, str, str, list[Evidence]]:
    cutoff = snapshot.as_of
    today = cutoff.astimezone(ZoneInfo("America/New_York")).date()
    known = {}
    for event in sorted(
        snapshot.events,
        key=lambda x: (
            x.available_at,
            x.published_at or x.available_at,
            x.title,
            x.event_at,
            x.source_url,
        ),
    ):
        if event.available_at > cutoff or (event.published_at and event.published_at > cutoff):
            continue
        known[event.source_id, event.event_id] = event
    weekly, releases, fed, upcoming, matrix = [], [], [], [], []
    for event in sorted(known.values(), key=lambda x: (x.event_at, x.source_id, x.event_id)):
        if event.timestamp_precision == "exact":
            future = event.event_at > cutoff
            recent = cutoff - dt.timedelta(days=7) <= event.event_at <= cutoff
            soon = cutoff < event.event_at <= cutoff + dt.timedelta(days=7)
        else:
            day = event.event_at.date()
            # A scheduled date today has no proven closing/release time.
            future = day > today or (day == today and event.scheduled)
            recent = today - dt.timedelta(days=7) <= day <= today and not future
            soon = today <= day <= today + dt.timedelta(days=7) and future
        reading = _event_reading(event)
        included = False
        if recent:
            weekly.append(reading)
            if event.kind == "release":
                releases.append(reading)
            included = True
        if (
            not future
            and event.source_id == "fed"
            and event.kind in ("meeting", "minutes", "projection")
        ):
            fed.append(reading)
            included = True
        if soon and event.scheduled:
            upcoming.append(reading)
            included = True
        if included:
            matrix.append(
                Evidence(
                    series_id=f"EVENT:{event.source_id}:{event.event_id}",
                    reading=reading,
                    direction="NO_EVALUABLE" if event.scheduled else "MIXTA",
                    source_url=event.source_url,
                    observed_at=(
                        event.event_at
                        if event.timestamp_precision == "exact" and not future
                        else None
                    ),
                    available_at=event.available_at,
                )
            )
    return (
        "\n".join(weekly) or "Sin eventos oficiales verificables para los ultimos siete dias.",
        "\n".join(releases) or "Sin nuevas publicaciones oficiales verificables en la semana.",
        "\n".join(fed) or "Sin referencias FOMC/SEP/minutas verificables al corte.",
        (
            "Agenda oficial conocida al corte; proximos siete dias:\n" + "\n".join(upcoming)
            if upcoming
            else "Sin eventos oficiales programados verificables para los proximos "
            "siete dias. Agenda incompleta; no significa ausencia de eventos."
        ),
        matrix,
    )


def render_report(
    snapshot: SnapshotData,
    *,
    week_key: str,
    previous: SnapshotData | None = None,
) -> ReportData:
    summary = _summary(snapshot)
    changes = _changes(snapshot, previous)
    drivers = (
        "\n".join(f"{h.horizon}: {x}" for h in snapshot.horizons for x in h.drivers)
        or "Drivers no evaluables."
    )
    contradictions = (
        "\n".join(f"{h.horizon}: {x}" for h in snapshot.horizons for x in h.contradictions)
        or "No se detectan contradicciones evaluables; esto no demuestra ausencia de riesgos."
    )
    conditions = (
        "\n".join(f"{h.horizon}: {x}" for h in snapshot.horizons for x in h.would_change)
        or "Completar evidencia obligatoria antes de clasificar."
    )
    limitations = "\n".join(
        f"{item.series_id}: {item.reason or 'SIN_DATOS'}"
        for item in snapshot.coverage
        if not item.available
    )
    chronology, releases, fed_events, upcoming, matrix = _event_sections(snapshot)
    for horizon in snapshot.horizons:
        for category in horizon.categories:
            for item in category.evidence:
                entry = item.model_copy(deep=True)
                entry.reading = f"{horizon.horizon}/{category.category}: {entry.reading}"
                matrix.append(entry)
    for item in snapshot.coverage:
        matrix.append(
            Evidence(
                series_id=item.series_id,
                reading=f"Cobertura: {'DISPONIBLE' if item.available else 'NO_DISPONIBLE'}; "
                f"{item.reason}; publicado={item.published_at}; ingestado={item.ingested_at}.",
                direction="MIXTA" if item.available else "NO_EVALUABLE",
                source_url=item.source_url,
                observed_at=item.observed_at,
                available_at=item.published_at,
            )
        )
    fed = (
        "\n".join(
            f"{h.horizon}/{item.series_id}: {item.reading}"
            for h in snapshot.horizons
            for c in h.categories
            for item in c.evidence
            if item.series_id in ("FED_FUNDS", "FED_BALANCE")
        )
        or "Fed: SIN_DATOS."
    )
    correction = []
    for h in snapshot.horizons:
        categories = {x.category: x for x in h.categories}
        equity = categories.get("EQUITY")
        macro, credit, volatility = (categories.get(x) for x in ("MACRO", "CREDIT", "VOLATILITY"))
        if any(x is None or x.value is None for x in (equity, macro, credit, volatility)):
            correction.append(
                f"{h.horizon}: no puede distinguirse correccion de deterioro estructural: "
                "faltan macro/equity/credito/volatilidad o historia."
            )
        elif equity.value < 0 or any(
            item.series_id.endswith(":DRAWDOWN") and item.value is not None and item.value < 0
            for item in equity.evidence
        ):
            stressed = macro.value < 0 and (credit.value < 0 or volatility.value < 0)
            correction.append(
                f"{h.horizon}: caida/estructura equity adversa; "
                + (
                    "compatible con deterioro: macro y credito/volatilidad confirman."
                    if stressed
                    else "posible correccion sin confirmacion conjunta de deterioro."
                )
                + " Hipotesis, no certeza causal."
            )
        else:
            correction.append(
                f"{h.horizon}: estructura equity no adversa; revisar drawdown y retornos "
                "en evidencia. Una correccion sin pivotes confirmados no demuestra deterioro."
            )
    contributions = "\n".join(
        f"{h.horizon}: "
        + "; ".join(
            f"{c.category} {c.weight:g}%: "
            + (f"{c.contribution:.4f}" if c.contribution is not None else "null")
            for c in h.categories
        )
        for h in snapshot.horizons
    )
    contents = [
        f"Corte {snapshot.as_of.isoformat()}; modo {snapshot.mode}.\n{chronology}\n"
        f"{changes}\n{limitations}",
        _category_text(snapshot, "MACRO") + "\nPublicaciones de la semana:\n" + releases,
        fed + "\nExpectativas de futuros Fed Funds no aportadas: no se afirman probabilidades. "
        "FOMC/SEP/minutas no se infieren con NLP.\nReferencias publicadas, no pronosticos:\n"
        + fed_events,
        _category_text(snapshot, "RATES"),
        _category_text(snapshot, "FX"),
        _category_text(snapshot, "VOLATILITY"),
        _category_text(snapshot, "EQUITY"),
        _category_text(snapshot, "CREDIT"),
        _category_text(snapshot, "CROSS_ASSET") + "\n" + contradictions,
        summary + "\n" + contributions + "\n" + drivers,
        "\n".join(
            f"{h.horizon}: {h.transition_status}; previo={h.previous_regime}."
            for h in snapshot.horizons
        )
        + "\n"
        + changes,
        "\n".join(correction),
        upcoming + "\nNo se infiere impacto HIGH ni resultado de un evento sin metadatos. "
        "No se inventan fechas, horarios, consensos ni precios objetivo.\n" + conditions,
    ]
    sections = [
        ReportSection(number=i, title=title, text=text or "SIN_DATOS.")
        for i, (title, text) in enumerate(zip(SECTION_TITLES, contents), 1)
    ]
    title = f"Regimen de mercado | semana {week_key}"
    brief = (
        summary
        + "\nDrivers: "
        + drivers
        + "\nMayor riesgo/contradicciones: "
        + contradictions
        + "\nQue cambiaria la lectura: "
        + conditions
        + "\nHeuristica no validada: no es probabilidad de ganar ni recomendacion."
    )
    text = (
        title
        + "\n\n"
        + brief
        + "\n\n"
        + "\n\n".join(f"{x.number}. {x.title}\n{x.text}" for x in sections)
    )
    text += "\n\nMatriz de evidencia\n" + "\n".join(
        f"{x.series_id} | {x.value} {x.unit} | {x.direction} | {x.reading} | "
        f"observado={x.observed_at} | disponible={x.available_at} | "
        f"ids={x.observation_ids} | {x.source_url}"
        for x in matrix
    )
    html = (
        '<!doctype html><html lang="es"><head><meta charset="utf-8"><title>'
        + escape(title)
        + "</title></head><body><h1>"
        + escape(title)
        + "</h1><div>"
        + escape(brief).replace("\n", "<br>")
        + "</div>"
    )
    html += "".join(
        f"<section><h2>{x.number}. {escape(x.title)}</h2><p>"
        + escape(x.text).replace("\n", "<br>")
        + "</p></section>"
        for x in sections
    )
    html += (
        "<h2>Matriz de evidencia</h2><table><thead><tr><th>Serie</th><th>Dato</th>"
        "<th>Estado y lectura</th><th>Fechas</th><th>Fuente</th></tr></thead><tbody>"
    )
    html += "".join(
        "<tr><td>"
        + escape(x.series_id)
        + "</td><td>"
        + escape(f"{x.value} {x.unit}")
        + "</td><td>"
        + escape(f"{x.direction}: {x.reading}")
        + "</td><td>"
        + escape(f"observado={x.observed_at}; disponible={x.available_at}")
        + "</td><td>"
        + _safe_link(x.source_url)
        + "</td></tr>"
        for x in matrix
    )
    html += "</tbody></table></body></html>"
    return ReportData(
        title=title,
        brief=brief,
        sections=sections,
        matrix=matrix,
        html=html,
        text=text,
    )
