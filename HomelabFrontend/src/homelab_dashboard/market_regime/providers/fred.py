"""Mirrors oficiales allowlisted. Nunca consulta ICE, indices o proxies de mercado."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlsplit

from .base import ParseError, observation, utc_date

URL = "https://api.stlouisfed.org/fred/series/observations"
ALLOWLIST = {
    "CPIAUCSL": "CPI",
    "CPILFESL": "CORE_CPI",
    "PAYEMS": "NFP",
    "UNRATE": "UNEMPLOYMENT",
    "CES0500000003": "AHE",
    "JTSJOL": "JOLTS",
    "PCEPI": "PCE",
    "PCEPILFE": "CORE_PCE",
    "GDPC1": "GDP",
    "DFF": "FED_FUNDS",
    "WALCL": "FED_BALANCE",
}


def requests(now: datetime, key: str) -> list[tuple[str, dict]]:
    today = now.date().isoformat()
    return [
        (
            URL,
            {
                "series_id": official,
                "api_key": key,
                "file_type": "json",
                "observation_start": (now - timedelta(days=731)).date().isoformat(),
                "observation_end": today,
                "realtime_start": today,
                "realtime_end": today,
                "units": "lin",
                "sort_order": "asc",
                "limit": "1000",
                "offset": "0",
                "output_type": "1",
            },
        )
        for official in ALLOWLIST
    ]


def parse(raw: bytes, url: str, now: datetime) -> list:
    try:
        body = json.loads(raw)
        if "error_code" in body:
            raise ParseError("FRED devolvio error; comprobar clave/cuota/parametros.")
        if int(body["count"]) > 1000 or int(body.get("offset", 0)) != 0:
            raise ParseError("FRED: respuesta paginada excede el presupuesto.")
        official = parse_qs(urlsplit(url).query)["series_id"][0]
        if official not in ALLOWLIST:
            raise ParseError("FRED: serie fuera de la lista oficial permitida.")
        series_id = ALLOWLIST[official]
        rows = []
        for point in body["observations"]:
            if point["value"] == ".":
                continue
            observed = utc_date(point["date"])
            if observed < now - timedelta(days=731):
                continue
            # La API fue consultada para hoy: no prueba la disponibilidad de revisiones
            # en la fecha economica ni en realtime_start de una observacion individual.
            rows.append(
                observation(
                    "fred",
                    series_id,
                    point["date"],
                    point["value"],
                    observed,
                    now,
                    url,
                    vintage=f"current_snapshot:{now.date().isoformat()}",
                )
            )
        if not rows:
            raise ParseError("FRED: serie sin observaciones numericas.")
        return rows
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ParseError("FRED: estructura JSON invalida.") from exc
