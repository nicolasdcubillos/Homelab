"""Curva par nominal diaria publicada por Treasury (no precios negociables)."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

from .base import ParseError, observation, utc_date

URL = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"


def requests(now: datetime, key: str) -> list[tuple[str, dict]]:
    return [
        (URL, {"data": "daily_treasury_yield_curve", "field_tdr_date_value": str(year)})
        for year in range(now.year - 2, now.year + 1)
    ]


def parse(raw: bytes, url: str, now: datetime) -> list:
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ParseError("Declaraciones XML no permitidas.")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ParseError("Treasury no devolvio XML valido.") from exc
    rows = []
    found = False
    for properties in root.iter():
        if properties.tag.rsplit("}", 1)[-1] != "properties":
            continue
        found = True
        cells = {node.tag.rsplit("}", 1)[-1]: node.text for node in properties}
        date = cells.get("NEW_DATE")
        if not date:
            raise ParseError("Treasury: falta NEW_DATE.")
        if not {"BC_2YEAR", "BC_10YEAR"} <= cells.keys():
            raise ParseError("Treasury: faltan columnas de 2 y 10 anos.")
        observed = utc_date(date[:10])
        if observed < now - timedelta(days=731):
            continue
        for series_id, field in (("US02Y", "BC_2YEAR"), ("US10Y", "BC_10YEAR")):
            value = cells.get(field)
            if value is None or value.strip() in {"", "N/A"}:
                continue
            rows.append(
                observation(
                    "treasury",
                    series_id,
                    date[:10],
                    value,
                    observed,
                    now,
                    url,
                )
            )
    if not found:
        raise ParseError("Treasury: respuesta sin registros de curva.")
    return rows
