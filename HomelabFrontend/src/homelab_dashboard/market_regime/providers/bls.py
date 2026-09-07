"""BLS agrupado, sin registro por defecto y sin transformar niveles en sorpresas."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta

from ..catalog import SERIES
from .base import ParseError, observation, utc_date

URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
SERIES_IDS = {
    value["official_id"]: key for key, value in SERIES.items() if value["source_id"] == "bls"
}


def requests(now: datetime, key: str) -> list[tuple[str, dict]]:
    body = {"seriesid": list(SERIES_IDS), "startyear": str(now.year - 2), "endyear": str(now.year)}
    if key:
        body["registrationkey"] = key
    return [(URL, body)]


def parse(raw: bytes, url: str, now: datetime) -> list:
    try:
        body = json.loads(raw)
        if body.get("status") != "REQUEST_SUCCEEDED":
            raise ParseError("BLS rechazo la solicitud; consultar cuota/parametros oficiales.")
        series = body["Results"]["series"]
        if {s["seriesID"] for s in series} != set(SERIES_IDS):
            raise ParseError("BLS: lista de series incompleta o no solicitada.")
        rows = []
        for item in series:
            series_id = SERIES_IDS[item["seriesID"]]
            for point in item["data"]:
                period = point["period"]
                if period == "M13":
                    continue
                if not re.fullmatch(r"M(?:0[1-9]|1[0-2])", period):
                    raise ParseError("BLS: periodo mensual no reconocido.")
                economic_period = f"{point['year']}-{period[1:]}"
                observed = utc_date(economic_period + "-01")
                if observed < now - timedelta(days=731):
                    continue
                if point["value"] in {"-", "NA", ""}:
                    continue
                rows.append(
                    observation(
                        "bls",
                        series_id,
                        economic_period,
                        point["value"],
                        observed,
                        now,
                        url,
                    )
                )
        if set(row.series_id for row in rows) != set(SERIES_IDS.values()):
            raise ParseError("BLS: una serie solicitada no contiene observaciones validas.")
        return rows
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ParseError("BLS: estructura JSON invalida.") from exc
