"""Interfaz publica de ingestion sin red al importar y sin escritura de BD."""

from __future__ import annotations

from datetime import datetime, timezone

import httpx

from ..catalog import credential, source_infos
from . import bea, bea_calendar, bls, census, dol, fed, fred, treasury
from .base import CollectedPayload, CollectionResult, ProviderError, payload
from .http import PublicHTTP

__all__ = ["CollectedPayload", "CollectionResult", "collect_source"]
_CONNECTORS = {
    "treasury": treasury,
    "fed": fed,
    "bls": bls,
    "bea": bea,
    "fred": fred,
    "bea_calendar": bea_calendar,
}


def collect_source(
    source_id: str,
    credentials: dict[str, str],
    *,
    now: datetime,
    transport: httpx.BaseTransport | None = None,
) -> CollectionResult:
    if now.tzinfo is None or now.utcoffset() is None:
        return CollectionResult(source_id, "ERROR", "now requiere zona horaria.")
    now = now.astimezone(timezone.utc)
    source = next((item for item in source_infos(credentials) if item.id == source_id), None)
    if source is None:
        return CollectionResult(source_id, "ERROR", "Fuente fuera del catalogo permitido.")
    if source.id == "census":
        return census.collect()
    if source.id == "dol":
        return dol.collect()
    if source.status != "DISPONIBLE":
        return CollectionResult(source_id, source.status, source.detail)
    connector = _CONNECTORS[source_id]
    result = CollectionResult(source_id, "DISPONIBLE", "")
    errors = []
    key = credential(credentials, source_id)
    with PublicHTTP(source_id, transport) as client:
        for url, parameters in connector.requests(now, key):
            try:
                clean_url, raw = client.fetch(
                    url,
                    **({"json": parameters} if source_id == "bls" else {"params": parameters}),
                )
                # BEA incluye UserID en RequestParam. Nunca conservar secretos reflejados.
                if key:
                    raw = raw.replace(key.encode(), b"[REDACTED]")
                try:
                    rows = connector.parse(raw, clean_url, now)
                    parse_events = getattr(connector, "parse_events", None)
                    events = parse_events(raw, clean_url, now) if parse_events is not None else []
                except ProviderError:
                    result.payloads.append(payload(source_id, clean_url, raw, []))
                    raise
                result.payloads.append(payload(source_id, clean_url, raw, rows, events))
            except ProviderError as exc:
                errors.append(str(exc))
    count = sum(len(item.observations) for item in result.payloads)
    event_count = sum(len(item.events) for item in result.payloads)
    if errors:
        result.status = "ERROR"
        result.detail = f"{count} observaciones recuperadas; " + " ".join(dict.fromkeys(errors))
    else:
        result.detail = (
            f"{count} observaciones y {event_count} eventos oficiales; "
            "disponibilidad desde ingestion, "
            "sin reconstruccion de vintages."
        )
        if source_id == "fed":
            result.detail += " H.15/H.4.1 actuales; FOMC fechas/enlaces sin hora inferida."
    return result
