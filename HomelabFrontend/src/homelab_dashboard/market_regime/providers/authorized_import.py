"""Parseo local estricto. Validar NO concede licencia: la aprobacion vive en el servicio.

JSON: {"manifest": {...}, "observations": [{...}]}.
CSV: manifest se entrega separado; columnas iguales a ImportRow, vacios solo opcionales.
No se lee un path ni se descarga source_url. El llamador conserva la evidencia/admin.
"""

from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime, time, timedelta
from decimal import Decimal
from typing import Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from ..catalog import SERIES
from ..schemas import Observation
from .base import CollectedPayload, ParseError, payload, utc_date
from .http import MAX_PAYLOAD_BYTES, sanitized_url


class ImportManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal["1"]
    provider: str = Field(min_length=1, max_length=120)
    source_url: str
    terms_url: str
    license_id: str = Field(min_length=1, max_length=120)
    license_evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    attribution: str = Field(min_length=1, max_length=500)
    permissions: list[
        Literal[
            "storage",
            "processing",
            "shared_display",
            "derivatives",
            "external_notification",
        ]
    ]

    @field_validator("source_url", "terms_url")
    @classmethod
    def public_link(cls, value: str) -> str:
        parts = urlsplit(value)
        if (
            parts.scheme != "https"
            or not parts.hostname
            or parts.username
            or parts.password
            or parts.fragment
            or parts.query
            or parts.port not in (None, 443)
        ):
            raise ValueError("Solo enlace HTTPS sin credenciales, consulta o fragmento.")
        return value


class ImportRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    series_id: str
    period: str = Field(min_length=1, max_length=40)
    value: Decimal
    unit: str
    frequency: Literal["daily", "weekly", "monthly", "quarterly", "event"]
    observed_at: datetime
    published_at: datetime | None = None
    available_at: datetime | None = None
    vintage: str = Field(default="unknown", max_length=80)
    timestamp_precision: Literal["exact", "date", "observed"] = "observed"
    publication_timezone: str | None = None
    contract: str | None = None
    roll_method: str | None = None
    bar_closed: bool
    quote_convention: str | None = None


def parse_authorized_import(
    raw: bytes,
    format: Literal["json", "csv"],
    *,
    now: datetime,
    manifest: dict | None = None,
) -> tuple[ImportManifest, CollectedPayload]:
    """Devuelve metadata declarada, NO aprobada, y payload; no persistir antes del gate."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ParseError("La ingestion requiere fecha con zona horaria.")
    if len(raw) > MAX_PAYLOAD_BYTES:
        raise ParseError("Archivo de importacion excede el limite de bytes.")
    try:
        if format == "json":
            body = json.loads(raw)
            if set(body) != {"manifest", "observations"} or manifest is not None:
                raise ParseError("JSON requiere exactamente manifest y observations.")
            metadata = ImportManifest.model_validate(body["manifest"])
            entries = body["observations"]
        elif format == "csv" and manifest is not None:
            metadata = ImportManifest.model_validate(manifest)
            reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
            headers = reader.fieldnames or []
            if len(headers) != len(set(headers)):
                raise ParseError("CSV con columnas duplicadas.")
            entries = []
            for row in reader:
                if None in row or any(v is None for v in row.values()):
                    raise ParseError("CSV con cantidad incorrecta de columnas.")
                entries.append({key: value for key, value in row.items() if value != ""})
        else:
            raise ParseError("Formato no soportado o manifest CSV ausente.")
        if not isinstance(entries, list) or not 1 <= len(entries) <= 10000:
            raise ParseError("Importacion requiere entre 1 y 10000 observaciones.")
        if not {"storage", "processing", "shared_display", "derivatives"} <= set(
            metadata.permissions
        ):
            raise ParseError("Manifest no declara los permisos minimos; no implica aprobacion.")
        rows = []
        identities = set()
        for entry in entries:
            row = ImportRow.model_validate(entry)
            catalog = SERIES.get(row.series_id)
            if (
                catalog is None
                or row.unit != catalog["unit"]
                or row.frequency != catalog["frequency"]
            ):
                raise ParseError("Serie, unidad o frecuencia no coincide con catalogo.")
            if not row.bar_closed or not row.value.is_finite():
                raise ParseError("Se requiere barra cerrada y valor finito.")
            if catalog.get("contract_required") and (not row.contract or not row.roll_method):
                raise ParseError("Futuros requieren contrato y metodo de roll explicitos.")
            if row.series_id == "USDJPY" and row.quote_convention != "JPY per USD":
                raise ParseError("USDJPY requiere convencion JPY per USD.")
            if row.observed_at.tzinfo is None or row.observed_at.utcoffset() is None:
                raise ParseError("observed_at requiere zona horaria.")
            if row.observed_at > now:
                raise ParseError("No se admiten observaciones futuras.")
            available = now
            published = None
            if row.timestamp_precision == "exact":
                if row.published_at is None or row.published_at.utcoffset() is None:
                    raise ParseError("Precision exact requiere published_at con zona horaria.")
                published = row.published_at
                available = max(now, published)
            elif row.timestamp_precision == "date":
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", row.vintage):
                    raise ParseError("Precision date requiere vintage YYYY-MM-DD.")
                if row.publication_timezone not in {"America/New_York", "UTC"}:
                    raise ParseError("Precision date requiere huso de publicacion admitido.")
                day = utc_date(row.vintage).date() + timedelta(days=1)
                conservative = datetime.combine(
                    day,
                    time.min,
                    tzinfo=ZoneInfo(row.publication_timezone),
                )
                available = max(now, conservative)
            # Un campo declarado no autoriza reconstruccion ni retrofecha una revision.
            if row.available_at is not None:
                if row.available_at.utcoffset() is None or row.available_at < available:
                    raise ParseError(
                        "available_at no puede preceder la disponibilidad conservadora."
                    )
                available = row.available_at
            identity = (row.series_id, row.period, row.vintage, row.contract)
            if identity in identities:
                raise ParseError("Observaciones duplicadas dentro del archivo.")
            identities.add(identity)
            rows.append(
                Observation(
                    source_id="authorized_import",
                    series_id=row.series_id,
                    period=row.period,
                    value=row.value,
                    unit=row.unit,
                    frequency=row.frequency,
                    observed_at=row.observed_at,
                    published_at=published,
                    available_at=available,
                    ingested_at=now,
                    vintage=row.vintage,
                    timestamp_precision=row.timestamp_precision,
                    source_url=sanitized_url(metadata.source_url),
                )
            )
        return metadata, payload("authorized_import", metadata.source_url, raw, rows)
    except (ValidationError, ValueError, KeyError, TypeError, UnicodeDecodeError) as exc:
        raise ParseError("Importacion no valida; comprobar esquema y metadata.") from exc
