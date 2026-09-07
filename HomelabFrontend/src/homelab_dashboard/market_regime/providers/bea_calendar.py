"""Calendario JSON sin clave enlazado por https://www.bea.gov/news/schedule."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from ..schemas import OfficialEvent
from .base import ParseError

URL = "https://apps.bea.gov/API/signup/release_dates.json"


def requests(now: datetime, key: str) -> list[tuple[str, dict]]:
    return [(URL, {})]


def parse(raw: bytes, url: str, now: datetime) -> list:
    return []


def parse_events(raw: bytes, url: str, now: datetime) -> list[OfficialEvent]:
    try:
        body = json.loads(raw)
        if not isinstance(body, dict) or not 1 <= len(body) <= 100:
            raise ParseError("BEA calendario: estructura o cantidad de publicaciones invalida.")
        events: dict[str, OfficialEvent] = {}
        count = 0
        for title, release in body.items():
            if title == "file_last_updated":
                # El archivo incluye metadata sin huso: no es la publicacion de eventos.
                if not isinstance(release, str):
                    raise ParseError("BEA calendario: metadata de archivo invalida.")
                datetime.fromisoformat(release.replace("Z", "+00:00"))
                continue
            if not isinstance(title, str) or not 1 <= len(title) <= 300:
                raise ParseError("BEA calendario: titulo invalido.")
            dates = release["release_dates"]
            if not isinstance(dates, list):
                raise ParseError("BEA calendario: lista de fechas invalida.")
            for date in dates:
                count += 1
                if count > 2000:
                    raise ParseError("BEA calendario: limite de eventos excedido.")
                scheduled = datetime.fromisoformat(date.replace("Z", "+00:00"))
                if scheduled.utcoffset() is None:
                    raise ParseError("BEA calendario: fecha sin huso; no se infiere la hora.")
                scheduled = scheduled.astimezone(timezone.utc)
                if not now.year - 1 <= scheduled.year <= now.year + 2:
                    continue
                topic = hashlib.sha256(title.encode()).hexdigest()[:16]
                identity = f"bea-release:{topic}:{scheduled.isoformat()}"
                events[identity] = OfficialEvent(
                    source_id="bea_calendar",
                    event_id=identity,
                    title=title + " (programado)",
                    source_url=URL,
                    event_at=scheduled,
                    published_at=None,
                    available_at=now,
                    kind="release",
                    scheduled=True,
                    timestamp_precision="exact",
                )
        if not events:
            raise ParseError("BEA calendario: sin eventos fechados reconocidos.")
        return sorted(events.values(), key=lambda event: (event.event_at, event.event_id))
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ParseError("BEA calendario: JSON/fechas invalidos.") from exc
