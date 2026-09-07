"""Persistencia append-only: una revision nunca sustituye evidencia anterior."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import zlib
from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import (
    RegimeEvent,
    RegimeModelVersion,
    RegimeObservation,
    RegimePayloadLicense,
    RegimeRawPayload,
)
from .schemas import Observation, OfficialEvent


def content_hash(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def evidence_ids(data) -> set[int]:
    result: set[int] = set()
    if isinstance(data, dict):
        ids = data.get("observation_ids", [])
        if not isinstance(ids, list) or any(type(value) is not int or value <= 0 for value in ids):
            raise ValueError("Identificador de evidencia invalido.")
        if data.get("series_id") and data.get("value") is not None and not ids:
            raise ValueError("Evidencia numerica sin identificadores persistidos.")
        result.update(ids)
        for value in data.values():
            result.update(evidence_ids(value))
    elif isinstance(data, list):
        for value in data:
            result.update(evidence_ids(value))
    return result


def freeze_model(db: Session, config: dict) -> str:
    identifier = content_hash(config)
    if db.get(RegimeModelVersion, identifier) is None:
        db.add(RegimeModelVersion(id=identifier, data=config))
        db.flush()
    return identifier


def persist_payload(
    db: Session,
    *,
    source_id: str,
    source_url: str,
    raw: bytes,
    observations: Sequence[Observation],
    ingested_at: dt.datetime,
    events: Sequence[OfficialEvent] = (),
    license_id: str | None = None,
) -> int:
    if len(raw) > 20 * 1024 * 1024:
        raise ValueError("El payload excede el limite de 20 MiB.")
    if source_id == "authorized_import" and license_id is None:
        raise ValueError("La importacion requiere una licencia exacta vinculada al payload.")
    digest = hashlib.sha256(raw).hexdigest()
    payload = db.scalar(
        select(RegimeRawPayload).where(
            RegimeRawPayload.source_id == source_id, RegimeRawPayload.sha256 == digest
        )
    )
    if payload is None:
        payload = RegimeRawPayload(
            source_id=source_id,
            source_url=source_url,
            sha256=digest,
            compressed=zlib.compress(raw),
            ingested_at=ingested_at,
        )
        db.add(payload)
        db.flush()
    if license_id is not None:
        binding = db.get(RegimePayloadLicense, payload.id)
        if binding is not None and binding.license_id != license_id:
            raise ValueError("No se puede sustituir la licencia original de un payload.")
        if binding is None:
            db.add(RegimePayloadLicense(raw_id=payload.id, license_id=license_id))
    added = 0
    for item in observations:
        if item.source_id != source_id:
            raise ValueError("La observacion no pertenece al proveedor del payload.")
        existing = db.scalar(
            select(RegimeObservation.id).where(
                RegimeObservation.source_id == source_id,
                RegimeObservation.series_id == item.series_id,
                RegimeObservation.period == item.period,
                RegimeObservation.vintage == item.vintage,
                RegimeObservation.raw_hash == digest,
            )
        )
        if existing is not None:
            continue
        values = item.model_dump(exclude={"id", "value", "ingested_at", "raw_hash"})
        db.add(
            RegimeObservation(
                **values,
                value=str(item.value),
                raw_id=payload.id,
                raw_hash=digest,
                ingested_at=ingested_at,
            )
        )
        added += 1
    db.flush()
    for event in events:
        if event.source_id != source_id:
            raise ValueError("El evento no pertenece al proveedor del payload.")
        existing = db.scalar(
            select(RegimeEvent.id).where(
                RegimeEvent.source_id == source_id,
                RegimeEvent.event_id == event.event_id,
                RegimeEvent.raw_hash == digest,
            )
        )
        if existing is None:
            db.add(
                RegimeEvent(
                    source_id=source_id,
                    event_id=event.event_id,
                    raw_id=payload.id,
                    raw_hash=digest,
                    available_at=event.available_at,
                    ingested_at=ingested_at,
                    data=event.model_dump(mode="json"),
                )
            )
    db.flush()
    return added


def events_as_of(db: Session, as_of: dt.datetime) -> list[OfficialEvent]:
    rows = db.scalars(
        select(RegimeEvent)
        .where(
            RegimeEvent.available_at <= as_of,
            RegimeEvent.ingested_at <= as_of,
        )
        .order_by(RegimeEvent.available_at.desc(), RegimeEvent.id.desc())
    )
    seen: set[tuple[str, str]] = set()
    result = []
    for row in rows:
        key = (row.source_id, row.event_id)
        if key not in seen:
            seen.add(key)
            result.append(OfficialEvent.model_validate(row.data))
    return sorted(result, key=lambda event: event.event_at)


def observations_as_of(
    db: Session,
    as_of: dt.datetime,
    *,
    reconstructed: bool = False,
) -> list[Observation]:
    clauses = [
        RegimeObservation.available_at <= as_of,
        RegimeObservation.observed_at <= as_of,
        RegimeObservation.quality == "OK",
    ]
    if reconstructed:
        # Fecha economica e ingestion actual no prueban disponibilidad historica.
        clauses += [
            RegimeObservation.published_at.is_not(None),
            RegimeObservation.published_at <= as_of,
            RegimeObservation.timestamp_precision.in_(["exact", "date"]),
            RegimeObservation.vintage != "unknown",
        ]
    else:
        clauses.append(RegimeObservation.ingested_at <= as_of)
    ranked = (
        select(
            RegimeObservation.id,
            func.row_number()
            .over(
                partition_by=(
                    RegimeObservation.source_id,
                    RegimeObservation.series_id,
                    RegimeObservation.period,
                ),
                order_by=(
                    RegimeObservation.available_at.desc(),
                    RegimeObservation.ingested_at.desc(),
                    RegimeObservation.id.desc(),
                ),
            )
            .label("position"),
        )
        .where(*clauses)
        .subquery()
    )
    rows = db.scalars(
        select(RegimeObservation)
        .join(ranked, ranked.c.id == RegimeObservation.id)
        .where(ranked.c.position == 1)
        .order_by(
            RegimeObservation.observed_at,
            RegimeObservation.series_id,
            RegimeObservation.id.desc(),
        )
        .execution_options(yield_per=500)
    )
    return [_observation(row) for row in rows]


def _observation(row: RegimeObservation) -> Observation:
    return Observation(
        id=row.id,
        source_id=row.source_id,
        series_id=row.series_id,
        period=row.period,
        value=Decimal(row.value),
        unit=row.unit,
        frequency=row.frequency,
        observed_at=row.observed_at,
        published_at=row.published_at,
        available_at=row.available_at,
        ingested_at=row.ingested_at,
        vintage=row.vintage,
        timestamp_precision=row.timestamp_precision,
        source_url=row.source_url,
        raw_hash=row.raw_hash,
        quality=row.quality,
    )


def observations_for_validation(db: Session) -> list[Observation]:
    """Mantiene todas las vintages, no solo la revision conocida hoy."""
    rows = db.scalars(
        select(RegimeObservation)
        .where(
            RegimeObservation.quality == "OK",
            RegimeObservation.vintage != "unknown",
            RegimeObservation.published_at.is_not(None),
            RegimeObservation.timestamp_precision.in_(["exact", "date"]),
        )
        .order_by(RegimeObservation.available_at, RegimeObservation.id)
    )
    return [_observation(row) for row in rows]
