"""Causal transformations over closed observations, without indicator libraries."""

from __future__ import annotations

import datetime as dt
import math
import re
from dataclasses import dataclass
from statistics import median

from .schemas import Evidence, Observation

UTC = dt.timezone.utc


def utc(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("as_of debe incluir zona horaria.")
    return value.astimezone(UTC)


def period_date(item: Observation) -> dt.date:
    """Economic chronology, not lexicographic ordering (2024-9 precedes 2024-10)."""
    quarter = re.fullmatch(r"(\d{4})[- ]?Q([1-4])", item.period, re.IGNORECASE)
    if quarter:
        return dt.date(int(quarter[1]), 3 * int(quarter[2]) - 2, 1)
    month = re.fullmatch(r"(\d{4})-(\d{1,2})", item.period)
    if month:
        return dt.date(int(month[1]), int(month[2]), 1)
    try:
        return dt.date.fromisoformat(item.period)
    except ValueError:
        return item.observed_at.date()


def point_in_time(
    observations: list[Observation],
    as_of: dt.datetime,
    config: dict,
    *,
    reconstruction: bool = False,
) -> tuple[dict[str, list[Observation]], dict[str, str]]:
    """Latest known vintage per economic period; bad latest values never fall back."""
    cutoff = utc(as_of)
    grouped: dict[str, dict[dt.date, list[Observation]]] = {}
    errors: dict[str, str] = {}
    for item in observations:
        if item.series_id not in config["series"]:
            continue
        if reconstruction:
            if (
                item.vintage in ("", "unknown", "current", "revised")
                or item.published_at is None
                or item.timestamp_precision != "exact"
            ):
                continue
            # Official release evidence, not today's ingestion, defines reconstructed knowledge.
            item = item.model_copy(update={"available_at": item.published_at})
        elif item.ingested_at is not None and item.ingested_at > cutoff:
            continue
        if (
            item.available_at > cutoff
            or item.observed_at > cutoff
            or (item.published_at is not None and item.published_at > cutoff)
        ):
            continue
        try:
            day = period_date(item)
        except ValueError:
            errors[item.series_id] = "DATO_INVALIDO: periodo economico invalido."
            continue
        if day > cutoff.date():
            continue
        grouped.setdefault(item.series_id, {}).setdefault(day, []).append(item)
    result = {}
    for series, periods in grouped.items():
        rule = config["series"][series]
        selected = []
        for _, versions in sorted(periods.items()):
            versions.sort(
                key=lambda x: (
                    x.available_at,
                    x.published_at or x.available_at,
                    x.ingested_at or x.available_at,
                    x.vintage,
                    x.source_id,
                    x.raw_hash,
                    x.id or 0,
                )
            )
            latest = versions[-1]
            primary_values = {}
            for item in versions:
                primary_values[item.source_id] = (item.value, item.unit)
            if len(set(primary_values.values())) > 1:
                errors[series] = "FUENTES_DISCREPANTES: no se promedian primario y mirror."
            if latest.quality != "OK":
                errors[series] = "DATO_INVALIDO: ultima observacion en cuarentena."
            if not math.isfinite(float(latest.value)):
                errors[series] = "DATO_INVALIDO: fuera de rango numerico de calculo."
            if latest.value != 0 and float(latest.value) == 0:
                errors[series] = "DATO_INVALIDO: precision numerica insuficiente."
            if latest.unit not in rule["units"]:
                errors[series] = f"UNIDAD_INVALIDA: {latest.unit}."
            if rule["positive"] and latest.value <= 0:
                errors[series] = "DATO_INVALIDO: se requiere nivel positivo."
            selected.append(latest)
        if len({x.unit for x in selected}) > 1:
            errors[series] = "UNIDAD_CAMBIANTE: no mezclar niveles sin conversion explicita."
        if selected:
            age = (cutoff - selected[-1].observed_at).total_seconds() / 86400
            if age > rule["max_age_days"]:
                errors[series] = f"DATO_OBSOLETO: edad {age:.1f} dias."
            result[series] = selected
    return result, errors


def sign(value: float, epsilon: float = 1e-9) -> int:
    return 1 if value > epsilon else -1 if value < -epsilon else 0


def quantile(values: list[float], fraction: float) -> float:
    if not values:
        raise ValueError("HISTORIA_INSUFICIENTE")
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def percentile(reference: list[float], value: float, *, minimum: int = 252) -> float:
    if len(reference) < minimum:
        raise ValueError(f"HISTORIA_INSUFICIENTE: requiere {minimum} sesiones previas.")
    # Midrank avoids declaring a constant series to be at its extreme upper tail.
    return (
        100
        * (sum(x < value for x in reference) + 0.5 * sum(x == value for x in reference))
        / len(reference)
    )


def bucket(day: dt.date, frequency: str):
    if frequency == "weekly":
        return day.isocalendar()[:2]
    if frequency == "monthly":
        return day.year, day.month
    return day


def closed_bars(
    values: list[Observation],
    frequency: str,
    as_of: dt.datetime,
    sessions: list[str] | None = None,
) -> list[Observation]:
    """Use supplied closes, never manufacture OHLC from Treasury par yields.

    Without a verified session calendar, aggregate only previous complete calendar
    weeks/months. This deliberately forgoes a current Friday/month-end bar rather
    than assert a holiday or early-close schedule.
    """
    cutoff = utc(as_of)
    eligible = [x for x in values if x.observed_at <= cutoff and x.available_at <= cutoff]
    if frequency == "daily":
        return sorted(eligible, key=lambda x: (period_date(x), x.observed_at))
    groups = {}
    for item in eligible:
        key = bucket(period_date(item), frequency)
        if key not in groups or item.observed_at > groups[key].observed_at:
            groups[key] = item
    now_bucket = bucket(cutoff.date(), frequency)
    verified = [dt.date.fromisoformat(x) for x in (sessions or [])]
    output = []
    for key, last in sorted(groups.items()):
        if key < now_bucket:
            output.append(last)
        elif key == now_bucket and last.frequency == frequency:
            output.append(last)
        elif key == now_bucket and verified:
            later_bucket_known = any(bucket(x, frequency) > key for x in verified)
            days = [x for x in verified if bucket(x, frequency) == key]
            if later_bucket_known and days and period_date(last) == max(days):
                output.append(last)
    return output


def evidence(
    series: str,
    items: list[Observation],
    reading: str,
    value: float | None,
) -> Evidence:
    latest = items[-1] if items else None
    numeric = float(latest.value) if latest else None
    if numeric is not None and not math.isfinite(numeric):
        numeric = None
    direction = (
        "NO_EVALUABLE"
        if value is None
        else "FAVORABLE"
        if value > 0
        else "ADVERSA"
        if value < 0
        else "MIXTA"
    )
    return Evidence(
        series_id=series,
        observation_ids=sorted({x.id for x in items if x.id is not None}),
        reading=reading,
        direction=direction,
        value=numeric,
        unit=latest.unit if latest else "",
        source_url=latest.source_url if latest else "",
        observed_at=latest.observed_at if latest else None,
        available_at=max((x.available_at for x in items), default=None),
    )


@dataclass(frozen=True)
class Evolution:
    direction: float
    change: float
    acceleration: float
    persistence: float


def evolution(values: list[float], epsilon: float = 1e-9) -> Evolution:
    if len(values) < 3:
        raise ValueError("HISTORIA_INSUFICIENTE: requiere al menos tres lecturas.")
    changes = [b - a for a, b in zip(values, values[1:])]
    direction = sign(values[-1] - values[0], epsilon)
    persistence = sum(sign(x, epsilon) == direction for x in changes) / len(changes)
    acceleration = changes[-1] - changes[-2]
    # Full conviction requires every observed change and acceleration to agree.
    strength = 1 if persistence == 1 and sign(acceleration, epsilon) in (0, direction) else 0.5
    return Evolution(direction * strength, changes[-1], acceleration, persistence)


@dataclass(frozen=True)
class Pivot:
    kind: str
    value: float
    observed_at: dt.datetime
    confirmed_at: dt.datetime


def confirmed_pivots(items: list[Observation], side: int = 2) -> list[Pivot]:
    result = []
    for i in range(side, len(items) - side):
        value = float(items[i].value)
        neighbours = items[i - side : i] + items[i + 1 : i + side + 1]
        kind = (
            "HIGH"
            if all(value > float(x.value) for x in neighbours)
            else "LOW"
            if all(value < float(x.value) for x in neighbours)
            else None
        )
        if kind:
            result.append(
                Pivot(
                    kind,
                    value,
                    items[i].observed_at,
                    max(x.available_at for x in items[i - side : i + side + 1]),
                )
            )
    return result


def structure(items: list[Observation], *, side: int = 2) -> tuple[float, str]:
    if len(items) < 4 * side + 1:
        raise ValueError("HISTORIA_INSUFICIENTE: estructura/pivotes.")
    pivots = confirmed_pivots(items, side)
    highs = [x for x in pivots if x.kind == "HIGH"]
    lows = [x for x in pivots if x.kind == "LOW"]
    value = 0.0
    label = "sin secuencia HH/HL o LH/LL confirmada"
    if len(highs) >= 2 and len(lows) >= 2:
        high_sign = sign(highs[-1].value - highs[-2].value)
        low_sign = sign(lows[-1].value - lows[-2].value)
        if high_sign == low_sign and high_sign:
            value = 0.5 * high_sign
            label = "HH/HL" if high_sign > 0 else "LH/LL"
    close = float(items[-1].value)
    if value > 0 and highs and close > highs[-1].value:
        value = 1.0
        label += "; ruptura alcista de pivote confirmado"
    elif value < 0 and lows and close < lows[-1].value:
        value = -1.0
        label += "; ruptura bajista de pivote confirmado"
    confirmations = ", ".join(p.confirmed_at.isoformat() for p in pivots[-4:])
    return value, f"{label}; confirmaciones [{confirmations}]"


def drawdown(values: list[float]) -> tuple[float, int]:
    peak = values[0]
    peak_index = 0
    maximum = 0.0
    for i, value in enumerate(values):
        if value >= peak:
            peak, peak_index = value, i
        maximum = max(maximum, 1 - value / peak)
    return maximum, len(values) - 1 - peak_index


def inflation_rates(items: list[Observation]) -> tuple[list[float], list[Observation]]:
    """Twelve calendar-month changes, not twelve arbitrary rows or annualized CPI levels."""
    months = {(period_date(x).year, period_date(x).month): x for x in items}
    rates, used = [], []
    for item in items:
        day = period_date(item)
        base = months.get((day.year - 1, day.month))
        if base is not None and base.value > 0:
            rates.append(100 * (float(item.value / base.value) - 1))
            used.extend((base, item))
    return rates, used


def level_change(items: list[Observation], count: int) -> tuple[float, list[Observation]]:
    if len(items) <= count:
        raise ValueError("HISTORIA_INSUFICIENTE: referencia de cambio.")
    used = items[-count - 1 :]
    return float(used[-1].value - used[0].value), used


def safe_mean(values: list[float]) -> float:
    if not values or any(not math.isfinite(x) for x in values):
        raise ValueError("Valores no evaluables.")
    return sum(values) / len(values)


def median_return(values: list[float]) -> float | None:
    return median(values) if values else None
