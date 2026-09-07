"""Eventos del HTML primario FOMC; una fecha no demuestra la hora de publicacion."""

from __future__ import annotations

import re
from datetime import datetime
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

from ..schemas import OfficialEvent
from .base import ParseError, utc_date

URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
_MONTHS = {
    name: month
    for month, name in enumerate(
        (
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ),
        start=1,
    )
}


class CalendarHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meetings: list[dict] = []
        self.links: list[str] = []
        self.year: int | None = None
        self._heading: list[str] | None = None
        self._depth = 0
        self._meeting_depth: int | None = None
        self._meeting: dict | None = None
        self._field: str | None = None
        self._field_depth: int | None = None

    def handle_starttag(self, tag: str, attrs: list) -> None:
        attributes = dict(attrs)
        if tag == "h4":
            self._heading = []
        if tag == "div":
            self._depth += 1
            classes = attributes.get("class", "").split()
            if "fomc-meeting" in classes:
                self._meeting_depth = self._depth
                self._meeting = {
                    "year": self.year,
                    "month": "",
                    "date": "",
                    "minutes": "",
                    "links": [],
                }
            if self._meeting is not None:
                for field in ("month", "date", "minutes"):
                    if f"fomc-meeting__{field}" in classes:
                        self._field, self._field_depth = field, self._depth
        if tag == "a" and attributes.get("href"):
            url = urljoin(URL, attributes["href"])
            if (
                urlsplit(url).scheme != "https"
                or urlsplit(url).hostname != "www.federalreserve.gov"
            ):
                return
            self.links.append(url)
            if self._meeting is not None:
                self._meeting["links"].append(url)

    def handle_data(self, text: str) -> None:
        if self._heading is not None:
            self._heading.append(text)
        if self._meeting is not None and self._field is not None:
            self._meeting[self._field] += text

    def handle_endtag(self, tag: str) -> None:
        if tag == "h4" and self._heading is not None:
            match = re.search(r"\b(20\d{2})\s+FOMC Meetings\b", "".join(self._heading))
            if match:
                self.year = int(match[1])
            self._heading = None
        if tag == "div":
            if self._depth == self._field_depth:
                self._field = self._field_depth = None
            if self._depth == self._meeting_depth and self._meeting is not None:
                self.meetings.append(self._meeting)
                self._meeting, self._meeting_depth = None, None
            self._depth -= 1


def _date_only(date: datetime) -> datetime:
    # Medianoche LOCAL solo codifica la fecha; timestamp_precision=date impide
    # presentarla como hora real de reunion, decision o publicacion.
    return date.replace(tzinfo=ZoneInfo("America/New_York"))


def _meeting_end(meeting: dict) -> datetime:
    month_text = " ".join(meeting["month"].split())
    month = _MONTHS.get(month_text.split("/")[-1].strip())
    days = re.sub(r"\([^)]*\)", "", meeting["date"]).strip().replace("*", "")
    match = re.fullmatch(r"\s*(\d{1,2})(?:\s*[-–]\s*(\d{1,2}))?\s*", days)
    if month is None or match is None:
        raise ParseError("FOMC: fecha de reunion no reconocida; no se infiere del calendario.")
    day = int(match[2] or match[1])
    return _date_only(utc_date(f"{meeting['year']}-{month:02d}-{day:02d}"))


def _document(url: str) -> tuple[str, datetime] | None:
    match = re.search(r"/newsevents/pressreleases/monetary(\d{8})a\.htm$", url)
    if match:
        return "release", _date_only(utc_date(match[1], "%Y%m%d"))
    match = re.search(r"/monetarypolicy/(?:files/)?fomcprojtabl(\d{8})\.(?:htm|pdf)$", url)
    if match:
        return "projection", _date_only(utc_date(match[1], "%Y%m%d"))
    return None


def parse_calendar(raw: bytes, now: datetime) -> list[OfficialEvent]:
    try:
        html = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ParseError("Calendario FOMC no codificado en UTF-8.") from exc
    parser = CalendarHTML()
    parser.feed(html)
    events: dict[str, OfficialEvent] = {}
    for url in parser.links:
        document = _document(url)
        if document is None:
            continue
        kind, date = document
        if date.year < now.year - 2 or date > now:
            continue
        identity = f"fomc-{kind}:{date.date().isoformat()}"
        if identity in events and not url.endswith(".htm"):
            continue
        events[identity] = OfficialEvent(
            source_id="fed",
            event_id=identity,
            title=("Comunicado FOMC" if kind == "release" else "Proyecciones economicas FOMC")
            + " (fecha documental; hora no verificada)",
            source_url=url,
            event_at=date,
            published_at=None,
            available_at=now,
            kind=kind,
            scheduled=False,
            timestamp_precision="date",
        )
    sep_annotation = "Meeting associated with a Summary of Economic Projections" in html
    for meeting in parser.meetings:
        year = meeting["year"]
        if year is None or not now.year - 1 <= year <= now.year + 2:
            continue
        date = _meeting_end(meeting)
        identity = f"fomc-meeting:{date.date().isoformat()}"
        date_label = " ".join(meeting["date"].split()).replace("*", "")
        events[identity] = OfficialEvent(
            source_id="fed",
            event_id=identity,
            title=f"Fin de reunion FOMC {meeting['month'].strip()} {date_label}, {year}"
            " (programada; hora no publicada)",
            source_url=URL,
            event_at=date,
            published_at=None,
            available_at=now,
            kind="meeting",
            scheduled=True,
            timestamp_precision="date",
        )
        minutes_urls = [
            url
            for url in meeting["links"]
            if re.search(
                r"/monetarypolicy/(?:files/)?fomcminutes\d{8}\.(?:htm|pdf)$",
                url,
            )
        ]
        minutes_date = re.search(
            r"Released\s+([A-Za-z]+\s+\d{1,2},\s*\d{4})",
            meeting["minutes"],
        )
        if minutes_urls and minutes_date:
            released = _date_only(utc_date(minutes_date[1], "%B %d, %Y"))
            if released > now:
                raise ParseError("FOMC: actas marcadas Released en fecha futura.")
            identity = f"fomc-minutes:{date.date().isoformat()}"
            events[identity] = OfficialEvent(
                source_id="fed",
                event_id=identity,
                title=f"Actas de reunion FOMC {date.date().isoformat()}"
                " (fecha de publicacion; hora no verificada)",
                source_url=next(
                    (url for url in minutes_urls if url.endswith(".htm")), minutes_urls[0]
                ),
                event_at=released,
                published_at=None,
                available_at=now,
                kind="minutes",
                scheduled=False,
                timestamp_precision="date",
            )
        if "*" in meeting["date"] and sep_annotation and date > now:
            identity = f"fomc-projection:{date.date().isoformat()}"
            events[identity] = OfficialEvent(
                source_id="fed",
                event_id=identity,
                title="Proyecciones economicas FOMC programadas (asterisco calendario oficial)",
                source_url=URL,
                event_at=date,
                published_at=None,
                available_at=now,
                kind="projection",
                scheduled=True,
                timestamp_precision="date",
            )
    if not events:
        raise ParseError("FOMC: no se reconocieron reuniones o documentos fechados oficiales.")
    return sorted(events.values(), key=lambda event: (event.event_at, event.event_id))
