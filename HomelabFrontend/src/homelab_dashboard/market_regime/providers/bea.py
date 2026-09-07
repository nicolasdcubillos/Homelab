"""BEA NIPA resuelto por codigo oficial, descripcion y unidad, no offsets de filas."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlsplit

from .base import ParseError, observation, utc_date

URL = "https://apps.bea.gov/api/data/"
_CONCEPTS = {
    "T20804": {
        "DPCERG": ("PCE", "personal consumption expenditures"),
        "DPCCRG": ("CORE_PCE", "pce excluding food and energy"),
    },
    "T10106": {"A191RX": ("GDP", "gross domestic product")},
}


def requests(now: datetime, key: str) -> list[tuple[str, dict]]:
    return [
        (
            URL,
            {
                "UserID": key,
                "method": "GetData",
                "datasetname": "NIPA",
                "TableName": table,
                "Frequency": "M" if table == "T20804" else "Q",
                "Year": ",".join(str(y) for y in range(now.year - 2, now.year + 1)),
                "ResultFormat": "JSON",
            },
        )
        for table in _CONCEPTS
    ]


def parse(raw: bytes, url: str, now: datetime) -> list:
    try:
        body = json.loads(raw)["BEAAPI"]
        results = body.get("Results", {})
        if "Error" in body or "Error" in results:
            raise ParseError("BEA devolvio Error JSON; comprobar clave/cuota/parametros.")
        table = parse_qs(urlsplit(url).query)["TableName"][0]
        expected = _CONCEPTS[table]
        rows = []
        for point in results["Data"]:
            code = point["SeriesCode"]
            if code not in expected:
                continue
            series_id, description = expected[code]
            actual = " ".join(point["LineDescription"].lower().split()).rstrip(".")
            if actual != description:
                raise ParseError(f"BEA: cambio de descripcion en {series_id}; revisar metadata.")
            if point.get("TableName", table) != table:
                raise ParseError("BEA: tabla distinta de la solicitada.")
            metric = point["METRIC_NAME"].lower()
            multiplier = str(point["UNIT_MULT"])
            unit_evidence = " ".join(
                [
                    metric,
                    point.get("CL_UNIT", "").lower(),
                    json.dumps(results.get("Notes", [])).lower(),
                ]
            )
            base_2017 = bool(
                re.search(
                    r"(?:2017\s*=\s*100|(?:chained|index)[^.;]{0,50}2017)",
                    unit_evidence,
                )
            )
            if series_id == "GDP":
                if "chained" not in metric or not base_2017 or multiplier != "9":
                    raise ParseError("BEA: unidad/base GDP no coincide con catalogo.")
            elif "index" not in metric or not base_2017 or multiplier != "0":
                raise ParseError("BEA: unidad/base PCE no coincide con catalogo.")
            period = point["TimePeriod"]
            match = re.fullmatch(r"(\d{4})([MQ])(\d{1,2})", period)
            if not match:
                raise ParseError("BEA: periodo no reconocido.")
            year, frequency, part = int(match[1]), match[2], int(match[3])
            if (series_id == "GDP" and (frequency != "Q" or not 1 <= part <= 4)) or (
                series_id != "GDP" and (frequency != "M" or not 1 <= part <= 12)
            ):
                raise ParseError("BEA: frecuencia no coincide con catalogo.")
            month = part if frequency == "M" else (part - 1) * 3 + 1
            observed = utc_date(f"{year}-{month:02d}-01")
            if observed < now - timedelta(days=731):
                continue
            value = point["DataValue"]
            if value in {"", "---", "(NA)"}:
                continue
            rows.append(observation("bea", series_id, period, value, observed, now, url))
        if {row.series_id for row in rows} != {item[0] for item in expected.values()}:
            raise ParseError("BEA: no se recibieron todas las lineas requeridas.")
        return rows
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ParseError("BEA: estructura JSON invalida.") from exc
