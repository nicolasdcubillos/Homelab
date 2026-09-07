"""Sesiones XNYS declarativas y acotadas; no extrapola años desconocidos."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
UTC = dt.timezone.utc


class CalendarUnavailable(ValueError):
    def __init__(self) -> None:
        super().__init__("CALENDARIO_NO_DISPONIBLE: fecha fuera del rango verificado.")


def _local(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("La fecha debe incluir zona horaria.")
    return value.astimezone(NY)


def _week(day: dt.date) -> str:
    year, week, _ = day.isocalendar()
    return f"{year}-W{week:02d}"


@dataclass(frozen=True)
class NyseCalendar:
    data: dict
    sha256: str

    @property
    def version(self) -> str:
        return self.data["version"]

    def contains(self, day: dt.date) -> bool:
        return self.data["valid_from"] <= day.isoformat() <= self.data["valid_until"]

    def session_close(self, day: dt.date) -> dt.datetime | None:
        if not self.contains(day):
            raise CalendarUnavailable()
        key = day.isoformat()
        if (
            day.weekday() not in self.data["regular_weekdays"]
            or key in self.data["holidays"]
            or key in self.data["exceptional_closures"]
        ):
            return None
        closing = self.data["early_closes"].get(key, self.data["regular_close"])
        return dt.datetime.combine(day, dt.time.fromisoformat(closing), NY).astimezone(UTC)

    def last_close(self, start: dt.date, end: dt.date) -> dt.datetime:
        day = end
        while day >= start:
            closing = self.session_close(day)
            if closing is not None:
                return closing
            day -= dt.timedelta(days=1)
        raise CalendarUnavailable()

    def week_close(self, day: dt.date) -> dt.datetime:
        monday = day - dt.timedelta(days=day.weekday())
        return self.last_close(monday, monday + dt.timedelta(days=4))


@lru_cache(maxsize=1)
def load_calendar() -> NyseCalendar:
    raw = Path(__file__).with_name("data").joinpath("nyse-calendar.json").read_bytes()
    return NyseCalendar(json.loads(raw), hashlib.sha256(raw).hexdigest())


def session_close(day: dt.date) -> dt.datetime | None:
    return load_calendar().session_close(day)


def weekly_schedule(now: dt.datetime) -> tuple[str, dt.datetime]:
    """Próximo corte semanal (incluye el instante exacto del corte)."""
    local = _local(now)
    calendar = load_calendar()
    if not calendar.contains(local.date()):
        raise CalendarUnavailable()
    day = local.date()
    closing = calendar.week_close(day) + dt.timedelta(minutes=90)
    if closing < now:
        day += dt.timedelta(days=7)
        closing = calendar.week_close(day) + dt.timedelta(minutes=90)
    return _week(day), closing


def due_week(now: dt.datetime) -> tuple[str, dt.datetime] | None:
    """Solo el vencimiento más reciente, nunca una cola de semanas históricas."""
    local = _local(now)
    calendar = load_calendar()
    if not calendar.contains(local.date()):
        return None
    for day in (local.date(), local.date() - dt.timedelta(days=7)):
        try:
            cutoff = calendar.week_close(day) + dt.timedelta(minutes=90)
        except CalendarUnavailable:
            continue
        if cutoff <= now:
            return _week(day), cutoff
    return None


def bar_key(horizon: str, as_of: dt.datetime) -> str | None:
    """Identidad de la última barra completamente cerrada del horizonte."""
    local = _local(as_of)
    calendar = load_calendar()
    day = local.date()
    if not calendar.contains(day):
        return None
    try:
        if horizon == "SHORT":
            for offset in range(10):
                candidate = day - dt.timedelta(days=offset)
                closing = calendar.session_close(candidate)
                if closing is not None and closing <= as_of:
                    return candidate.isoformat()
        elif horizon == "MEDIUM":
            for offset in (0, 7):
                candidate = day - dt.timedelta(days=offset)
                if calendar.week_close(candidate) <= as_of:
                    return _week(candidate)
        elif horizon == "LONG":
            first = day.replace(day=1)
            for _ in range(2):
                next_month = (first.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
                closing = calendar.last_close(first, next_month - dt.timedelta(days=1))
                if closing <= as_of:
                    return first.strftime("%Y-%m")
                first = (first - dt.timedelta(days=1)).replace(day=1)
        else:
            raise ValueError("Horizonte desconocido.")
    except CalendarUnavailable:
        return None
    return None
