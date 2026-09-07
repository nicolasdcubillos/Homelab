"""Conjunctive macro hypotheses: the same yield/USD move can have opposite readings."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from .config import DEFAULT_CONFIG, MACRO_SERIES
from .features import closed_bars, evidence, evolution, inflation_rates, period_date, sign
from .schemas import Evidence, Observation


@dataclass
class MacroContext:
    name: str = "NO_EVALUABLE"
    value: float | None = None
    inflation: float | None = None
    employment: float | None = None
    growth: float | None = None
    policy: float | None = None
    evidence: list[Evidence] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    contradictions: list[str] = field(default_factory=list)


def decide_context(
    *,
    inflation: float,
    employment: float,
    growth: float,
    policy: float,
) -> str:
    """Axes: inflation pressure positive; employment/growth/policy support positive."""
    if employment < 0 and growth < 0:
        return "DETERIORO_ACTIVIDAD"
    if inflation > 0 and policy < 0:
        return "INFLACION_ENDURECIMIENTO"
    if employment >= 0 and growth > 0 and inflation < 0 and policy >= 0:
        return "RESILIENTE_DESINFLACION"
    return "MIXTO"


def build_context(
    data: dict[str, list[Observation]],
    errors: dict[str, str],
    horizon: dict,
    config: dict,
    as_of: dt.datetime,
) -> MacroContext:
    result = MacroContext()
    rules = config["rules"]
    count = horizon["macro_readings"]
    axes = {}
    for series in MACRO_SERIES:
        items = data.get(series, [])
        if series in errors or not items:
            reason = errors.get(series, "SIN_DATOS")
            result.missing.append(f"{series}: {reason}")
            result.evidence.append(evidence(series, items[-1:], reason, None))
            continue
        if series in ("FED_FUNDS", "FED_BALANCE"):
            items = closed_bars(
                items,
                horizon["bar_frequency"],
                as_of,
                rules["verified_sessions"],
            )
        if not items:
            result.missing.append(f"{series}: HISTORIA_INSUFICIENTE de cierres.")
            continue
        needed = horizon["gdp_readings"] if series == "GDP" else count
        raw = [float(x.value) for x in items]
        used = items[-needed:]
        if series in ("CPI", "CORE_CPI", "PCE", "CORE_PCE", "AHE"):
            raw, lineage = inflation_rates(items)
            used = lineage[-2 * needed :]
            if used and period_date(used[-1]) != period_date(items[-1]):
                result.missing.append(f"{series}: falta referencia interanual de ultima lectura.")
                continue
        elif series == "NFP":
            raw = [b - a for a, b in zip(raw, raw[1:])]
            used = items[-needed - 1 :]
        elif series == "GDP" and items[-1].unit == "billions of chained 2017 USD":
            if any(x <= 0 for x in raw):
                result.missing.append("GDP: nivel real no positivo.")
                continue
            raw = [100 * ((b / a) ** 4 - 1) for a, b in zip(raw, raw[1:])]
            used = items[-needed - 1 :]
        if len(raw) < needed:
            reason = f"HISTORIA_INSUFICIENTE: {needed} lecturas transformadas."
            result.missing.append(f"{series}: {reason}")
            result.evidence.append(evidence(series, used, reason, None))
            continue
        if series not in ("FED_FUNDS", "FED_BALANCE"):
            chronological = used[1::2] if series in rules["inflation_weights"] else used
            dates = [period_date(x) for x in chronological]
            step = 3 if series == "GDP" else 1
            if any(
                (b.year - a.year) * 12 + b.month - a.month != step for a, b in zip(dates, dates[1:])
            ):
                result.missing.append(f"{series}: HISTORIA_INSUFICIENTE, periodos faltantes.")
                continue
        transformed = raw[-needed:]
        feature = evolution(transformed, rules["direction_epsilon"])
        axis = feature.direction
        detail = (
            f"{needed} lecturas; cambio={feature.change:.4f}; "
            f"aceleracion={feature.acceleration:.4f}; "
            f"persistencia={feature.persistence:.2f}"
        )
        if series in ("CPI", "CORE_CPI", "PCE", "CORE_PCE", "AHE"):
            detail = (
                f"variacion interanual={raw[-1]:.4f}%; "
                f"meta contextual={rules['inflation_target']:g}%; " + detail
            )
            # Above-target level is context, never a standalone risk-off rule.
            if raw[-1] > rules["inflation_hot"] and axis == 0:
                axis = 0.5
        elif series in ("GDP", "NFP"):
            detail = (
                f"PIB real q/q anualizado={raw[-1]:.4f}%; "
                if series == "GDP"
                else f"creacion neta={raw[-1]:.4f} miles de personas; "
            ) + detail
            # Negative growth/job creation is deterioration even when less negative.
            if transformed[-1] < rules["growth_zero"]:
                axis = -1
            elif transformed[-1] > rules["growth_zero"] and axis >= 0:
                axis = max(0.5, axis)
        elif series == "UNEMPLOYMENT":
            axis *= -1
        elif series == "FED_FUNDS":
            axis *= -1
        axes[series] = axis
        favorable = -axis if series in rules["inflation_weights"] else axis
        result.evidence.append(evidence(series, used, detail, favorable))
    if result.missing:
        return result
    result.inflation = sum(axes[k] * w for k, w in rules["inflation_weights"].items())
    result.employment = sum(axes[k] * w for k, w in rules["employment_weights"].items())
    result.growth = axes["GDP"]
    result.policy = sum(axes[k] * w for k, w in rules["policy_weights"].items())
    result.name = decide_context(
        inflation=result.inflation,
        employment=result.employment,
        growth=result.growth,
        policy=result.policy,
    )
    parts = {
        "context": rules["context_values"][result.name],
        "employment": result.employment,
        "growth": result.growth,
        "policy": result.policy,
    }
    result.value = sum(parts[k] * w for k, w in rules["macro_weights"].items())
    if sign(result.growth) != sign(result.employment):
        result.contradictions.append("GDP frente a NFP/UNEMPLOYMENT/JOLTS: ejes discrepantes.")
    if result.name == "DETERIORO_ACTIVIDAD" and result.inflation < 0:
        result.contradictions.append(
            "CPI/PCE desinflan, pero GDP y empleo deterioran: desinflacion no implica risk-on."
        )
    return result


def conditional_rates(
    context: MacroContext,
    two_change: float,
    ten_change: float,
    rules: dict | None = None,
) -> float:
    if context.value is None:
        raise ValueError("CONTEXTO_NO_EVALUABLE")
    table = (rules or DEFAULT_CONFIG["rules"])["rates_values"]
    if context.name == "RESILIENTE_DESINFLACION":
        return (
            table["resilient_rising"]
            if two_change > 0 and ten_change > 0
            else table["resilient_falling_short"]
            if two_change < 0
            else table["unresolved"]
        )
    if context.name == "INFLACION_ENDURECIMIENTO":
        return (
            table["inflation_rising"] if two_change > 0 or ten_change > 0 else table["unresolved"]
        )
    if context.name == "DETERIORO_ACTIVIDAD":
        return (
            table["deterioration_falling"]
            if two_change < 0 and ten_change < 0
            else table["deterioration_other"]
        )
    return table["unresolved"]


def conditional_fx(
    context: MacroContext,
    dxy_direction: float,
    yen_direction: float,
    credit_direction: float | None,
    volatility_direction: float | None,
    rules: dict | None = None,
) -> float:
    if context.value is None:
        raise ValueError("CONTEXTO_NO_EVALUABLE")
    stress = (
        credit_direction is not None
        and credit_direction < 0
        and volatility_direction is not None
        and volatility_direction < 0
    )
    table = (rules or DEFAULT_CONFIG["rules"])["fx_values"]
    if stress and (dxy_direction > 0 or yen_direction < 0):
        return table["confirmed_stress"]
    if context.name == "INFLACION_ENDURECIMIENTO" and dxy_direction > 0:
        return table["inflation_strong_dollar"]
    if context.name == "RESILIENTE_DESINFLACION" and not stress:
        return (
            table["resilient_easing_or_carry"]
            if dxy_direction <= 0 or yen_direction > 0
            else table["unresolved"]
        )
    return table["unresolved"]
