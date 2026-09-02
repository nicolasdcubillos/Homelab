"""SQLite-backed state store for local development and testing."""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path

from ..models import StoreRecord
from .base import StateStore

_SCHEMA = """
CREATE TABLE IF NOT EXISTS availability (
    key         TEXT PRIMARY KEY,
    available   INTEGER NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS stores (
    host        TEXT PRIMARY KEY,
    provider    TEXT NOT NULL,
    country     TEXT NOT NULL,
    enabled     INTEGER NOT NULL,
    first_seen  TEXT NOT NULL,
    last_ok     TEXT,
    fail_count  INTEGER NOT NULL DEFAULT 0,
    source      TEXT NOT NULL DEFAULT 'discovery',
    note        TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value else None


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:  # pragma: no cover - defensive
        return None


class SqliteStateStore(StateStore):
    """Small synchronous SQLite database driven from a worker thread."""

    def __init__(self, path: str | Path = "data/stockwatcher.db") -> None:
        self.path = Path(path)
        self._conn: sqlite3.Connection | None = None

    def _connect(self) -> sqlite3.Connection:
        if self.path.parent and str(self.path.parent) not in ("", "."):
            self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.executescript(_SCHEMA)
        conn.commit()
        return conn

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("SqliteStateStore used before open()")
        return self._conn

    async def open(self) -> None:
        if self._conn is None:
            self._conn = await asyncio.to_thread(self._connect)

    async def close(self) -> None:
        if self._conn is not None:
            conn, self._conn = self._conn, None
            await asyncio.to_thread(conn.close)

    async def get_states(self, keys: Iterable[str]) -> dict[str, bool]:
        key_list = list(dict.fromkeys(keys))
        if not key_list:
            return {}

        def _run() -> dict[str, bool]:
            out: dict[str, bool] = {}
            for chunk_start in range(0, len(key_list), 500):
                chunk = key_list[chunk_start : chunk_start + 500]
                placeholders = ",".join("?" * len(chunk))
                rows = self.conn.execute(
                    f"SELECT key, available FROM availability WHERE key IN ({placeholders})",
                    chunk,
                ).fetchall()
                out.update({row["key"]: bool(row["available"]) for row in rows})
            return out

        return await asyncio.to_thread(_run)

    async def set_states(self, updates: Mapping[str, bool]) -> None:
        if not updates:
            return
        now = datetime.now(UTC).isoformat()
        rows = [(key, int(value), now) for key, value in updates.items()]

        def _run() -> None:
            self.conn.executemany(
                "INSERT INTO availability (key, available, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET available=excluded.available, "
                "updated_at=excluded.updated_at",
                rows,
            )
            self.conn.commit()

        await asyncio.to_thread(_run)

    async def list_stores(self) -> list[StoreRecord]:
        def _run() -> list[StoreRecord]:
            rows = self.conn.execute("SELECT * FROM stores").fetchall()
            return [
                StoreRecord(
                    host=row["host"],
                    provider=row["provider"],
                    country=row["country"],
                    enabled=bool(row["enabled"]),
                    first_seen=_parse(row["first_seen"]) or datetime.now(UTC),
                    last_ok=_parse(row["last_ok"]),
                    fail_count=int(row["fail_count"]),
                    source=row["source"],
                    note=row["note"] or "",
                )
                for row in rows
            ]

        return await asyncio.to_thread(_run)

    async def upsert_store(self, record: StoreRecord) -> None:
        def _run() -> None:
            self.conn.execute(
                "INSERT INTO stores "
                "(host, provider, country, enabled, first_seen, last_ok, fail_count, source, note) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(host) DO UPDATE SET provider=excluded.provider, "
                "country=excluded.country, enabled=excluded.enabled, last_ok=excluded.last_ok, "
                "fail_count=excluded.fail_count, source=excluded.source, note=excluded.note",
                (
                    record.host,
                    record.provider,
                    record.country,
                    int(record.enabled),
                    _iso(record.first_seen),
                    _iso(record.last_ok),
                    record.fail_count,
                    record.source,
                    record.note,
                ),
            )
            self.conn.commit()

        await asyncio.to_thread(_run)

    async def get_meta(self, key: str) -> str | None:
        def _run() -> str | None:
            row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
            return row["value"] if row else None

        return await asyncio.to_thread(_run)

    async def set_meta(self, key: str, value: str) -> None:
        def _run() -> None:
            self.conn.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
            self.conn.commit()

        await asyncio.to_thread(_run)
