"""Resultados sin acceso a BD: el coordinador conserva raw y observaciones."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from ..catalog import SERIES
from ..schemas import Observation, OfficialEvent, SourceStatus


class ProviderError(Exception):
    """Error saneado que puede mostrarse sin URLs con claves ni cuerpos remotos."""


class ParseError(ProviderError):
    pass


class QuotaError(ProviderError):
    pass


@dataclass
class CollectedPayload:
    source_id: str
    source_url: str
    raw: bytes
    observations: list[Observation]
    events: list[OfficialEvent] = field(default_factory=list)

    @property
    def raw_hash(self) -> str:
        return hashlib.sha256(self.raw).hexdigest()


@dataclass
class CollectionResult:
    source_id: str
    status: SourceStatus
    detail: str
    payloads: list[CollectedPayload] = field(default_factory=list)


def observation(
    source_id: str,
    series_id: str,
    period: str,
    value: str,
    observed_at: datetime,
    now: datetime,
    source_url: str,
    *,
    vintage: str = "unknown",
) -> Observation:
    try:
        number = Decimal(value.replace(",", "").strip())
    except InvalidOperation as exc:
        raise ParseError(f"Valor numerico invalido en {series_id}.") from exc
    if not number.is_finite():
        raise ParseError(f"Valor no finito en {series_id}.")
    if observed_at > now:
        raise ParseError(f"Periodo futuro inesperado en {series_id}.")
    metadata = SERIES[series_id]
    return Observation(
        source_id=source_id,
        series_id=series_id,
        period=period,
        value=number,
        unit=metadata["unit"],
        frequency=metadata["frequency"],
        observed_at=observed_at,
        published_at=None,
        available_at=now,
        ingested_at=now,
        vintage=vintage,
        timestamp_precision="observed",
        source_url=source_url,
    )


def utc_date(value: str, format: str = "%Y-%m-%d") -> datetime:
    try:
        return datetime.strptime(value.strip(), format).replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ParseError("Fecha oficial con formato no reconocido.") from exc


def payload(
    source_id: str,
    url: str,
    raw: bytes,
    rows: list[Observation],
    events: list[OfficialEvent] | None = None,
) -> CollectedPayload:
    digest = hashlib.sha256(raw).hexdigest()
    for row in rows:
        row.raw_hash = digest
    return CollectedPayload(source_id, url, raw, rows, events or [])
