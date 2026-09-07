"""Persistencia append-only: una revision nunca sustituye evidencia anterior."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import zlib
from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import RegimeModelVersion, RegimeObservation, RegimeRawPayload
from .schemas import Observation


def content_hash(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


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
) -> int:
    if len(raw) > 20 * 1024 * 1024:
        raise ValueError("El payload excede el limite de 20 MiB.")
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
    return added


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
    rows = db.scalars(
        select(RegimeObservation)
        .where(*clauses)
        .order_by(
            RegimeObservation.available_at.desc(),
            RegimeObservation.ingested_at.desc(),
            RegimeObservation.id.desc(),
        )
    )
    seen: set[tuple[str, str, str]] = set()
    result: list[Observation] = []
    for row in rows:
        key = (row.source_id, row.series_id, row.period)
        if key in seen:
            continue
        seen.add(key)
        result.append(
            Observation(
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
        )
    return sorted(result, key=lambda value: (value.observed_at, value.series_id))
