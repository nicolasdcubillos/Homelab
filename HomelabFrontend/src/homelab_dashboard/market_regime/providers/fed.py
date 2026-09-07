"""Tablas oficiales H.10/H.15/H.4.1 y enlaces FOMC; sin clasificador de texto."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from .base import ParseError, observation, utc_date

H10 = "https://www.federalreserve.gov/releases/h10/hist/dat00_ja.htm"
H15 = "https://www.federalreserve.gov/releases/h15/"
H41 = "https://www.federalreserve.gov/releases/h41/current/h41.htm"
FOMC = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"


class Tables(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self.links: list[tuple[str, str]] = []
        self._row: list[str] = []
        self._cell: list[str] | None = None
        self._href = ""
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag == "tr":
            self._row = []
        if tag in {"td", "th"}:
            self._cell = []
        if tag == "a":
            self._href = dict(attrs).get("href", "")
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)
        if self._href:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._cell is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        if tag == "tr" and self._row:
            self.rows.append(self._row)
        if tag == "a" and self._href:
            self.links.append((self._href, " ".join("".join(self._text).split())))
            self._href = ""


def _tables(raw: bytes) -> Tables:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ParseError("Fed: HTML no codificado en UTF-8.") from exc
    result = Tables()
    result.feed(text)
    return result


def parse_h10(raw: bytes, url: str, now: datetime) -> list:
    rows = []
    for cells in _tables(raw).rows:
        if len(cells) != 2 or not re.fullmatch(r"\d{1,2}-[A-Z]{3}-\d{2}", cells[0]):
            continue
        observed = utc_date(cells[0], "%d-%b-%y")
        if observed < now - timedelta(days=731):
            continue
        if cells[1].lower() in {"nd", "n.a.", "n.a", "na", ""}:
            continue
        row = observation(
            "fed",
            "USDJPY",
            observed.date().isoformat(),
            cells[1],
            observed,
            now,
            url,
        )
        if row.value <= 0:
            raise ParseError("H.10: tipo de cambio no positivo.")
        rows.append(row)
    if not rows:
        raise ParseError("H.10: no se reconocieron tasas JPY por USD.")
    return rows


def parse_h15(raw: bytes, url: str, now: datetime) -> list:
    dates: list[datetime] = []
    for cells in _tables(raw).rows:
        if cells[0] == "Instruments":
            dates = [utc_date(re.sub(r"\s+", "", c), "%Y%b%d") for c in cells[1:]]
        if cells[0].startswith("Federal funds (effective)") and dates:
            if len(cells) != len(dates) + 1:
                raise ParseError("H.15: columnas de tasa y fecha inconsistentes.")
            result = [
                observation("fed", "FED_FUNDS", date.date().isoformat(), value, date, now, url)
                for date, value in zip(dates, cells[1:])
                if value.lower() not in {"n.a.", "nd", ""}
            ]
            if not result:
                raise ParseError("H.15: tasa efectiva sin valores numericos.")
            return result
    raise ParseError("H.15: no se encontro la tasa efectiva y sus fechas.")


def parse_h41(raw: bytes, url: str, now: datetime) -> list:
    date = None
    value_column = None
    for cells in _tables(raw).rows:
        if cells[0] == "Assets, liabilities, and capital":
            # La tabla consolidada identifica su columna por encabezado, no por fila fija.
            if "Eliminations from consolidation" not in cells:
                continue
            for index, cell in enumerate(cells):
                match = re.search(r"Wednesday\s*([A-Za-z]{3}\s+\d{1,2},\s*\d{4})", cell)
                if match:
                    date = utc_date(match[1], "%b %d, %Y")
                    value_column = index
        if cells[0] == "Total assets" and date is not None and value_column is not None:
            if value_column >= len(cells):
                raise ParseError("H.4.1: columna consolidada ausente.")
            return [
                observation(
                    "fed",
                    "FED_BALANCE",
                    date.date().isoformat(),
                    cells[value_column],
                    date,
                    now,
                    url,
                )
            ]
    raise ParseError("H.4.1: faltan activos consolidados o fecha de miercoles.")


def parse_fomc_documents(raw: bytes) -> list[dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for href, title in _tables(raw).links:
        url = urljoin(FOMC, href)
        if urlsplit(url).hostname != "www.federalreserve.gov":
            continue
        match = re.search(
            r"/(?:newsevents/pressreleases/monetary|monetarypolicy/fomcminutes"
            r"|monetarypolicy/fomcprojtabl|monetarypolicy/files/fomcprojtabl)"
            r"(\d{8})[^/]*\.(?:htm|pdf)$",
            url,
        )
        if not match:
            continue
        date = utc_date(match[1], "%Y%m%d").date().isoformat()
        kind = (
            "minutes" if "minutes" in url else "projections" if "projtabl" in url else "statement"
        )
        result[url] = {
            "url": url,
            "title": title[:200],
            "kind": kind,
            "document_date": date,
            "date_semantics": (
                "meeting_date_in_url" if kind == "minutes" else "document_date_in_url"
            ),
            "timestamp_precision": "date",
            "limitation": "Enlace oficial; sin parser de expectativas ni probabilidad de mercado.",
        }
    if not result:
        raise ParseError("FOMC: no se reconocieron enlaces oficiales de documentos.")
    return list(result.values())


def parse_fomc(raw: bytes, url: str, now: datetime) -> list:
    # La validacion de este payload ocurre en parse_events: un calendario futuro
    # valido puede no tener todavia enlaces de comunicados.
    return []


def parse_events(raw: bytes, url: str, now: datetime) -> list:
    if url != FOMC:
        return []
    from .fed_calendar import parse_calendar

    return parse_calendar(raw, now)


def requests(now: datetime, key: str) -> list[tuple[str, dict]]:
    return [(url, {}) for url in (H10, H15, H41, FOMC)]


def parse(raw: bytes, url: str, now: datetime) -> list:
    parsers = {H10: parse_h10, H15: parse_h15, H41: parse_h41, FOMC: parse_fomc}
    return parsers[url](raw, url, now)
