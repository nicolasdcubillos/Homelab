"""SQLite state store: news dedupe, signal history, and price snapshots.

A synchronous ``sqlite3`` connection is enough here — the CLI runs at most
twice a day and once a week, so there is no concurrency pressure that would
justify async I/O (unlike StockWatcher, which polls many stores per minute).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS seen_news (
    guid        TEXT PRIMARY KEY,
    ticker      TEXT NOT NULL,
    source      TEXT NOT NULL,
    first_seen  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS llm_signals (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at   TEXT NOT NULL,
    ticker       TEXT NOT NULL,
    signal_type  TEXT NOT NULL,     -- riesgo | oportunidad | ruido
    severity     TEXT NOT NULL,     -- low | medium | high
    thesis       TEXT NOT NULL,
    news_guid    TEXT,
    prompt       TEXT NOT NULL,
    response     TEXT NOT NULL,
    model        TEXT NOT NULL,
    outcome_30d  TEXT,              -- filled in later, manually or by a follow-up script
    outcome_90d  TEXT
);

CREATE TABLE IF NOT EXISTS price_snapshots (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker       TEXT NOT NULL,
    price        REAL,
    previous_close REAL,
    sector       TEXT,
    captured_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


@dataclass
class SignalRecord:
    ticker: str
    signal_type: str
    severity: str
    thesis: str
    prompt: str
    response: str
    model: str
    news_guid: str | None = None
    created_at: datetime | None = None


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class StateStore:
    """Owns the SQLite file used to dedupe news and log signal history."""

    def __init__(self, path: str | Path = "data/portfoliowatcher.db") -> None:
        self.path = Path(path)
        self._conn: sqlite3.Connection | None = None

    def open(self) -> None:
        if self._conn is not None:
            return
        if self.path.parent and str(self.path.parent) not in ("", "."):
            self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.executescript(_SCHEMA)
        conn.commit()
        self._conn = conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> StateStore:
        self.open()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("StateStore used before open()")
        return self._conn

    # ------------------------------------------------------------- dedupe

    def is_seen(self, guid: str) -> bool:
        row = self.conn.execute("SELECT 1 FROM seen_news WHERE guid = ?", (guid,)).fetchone()
        return row is not None

    def mark_seen(self, guid: str, ticker: str, source: str) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO seen_news (guid, ticker, source, first_seen) "
            "VALUES (?, ?, ?, ?)",
            (guid, ticker, source, _now_iso()),
        )
        self.conn.commit()

    def filter_unseen(self, items: list[tuple[str, str, str]]) -> list[tuple[str, str, str]]:
        """Given ``(guid, ticker, source)`` tuples, return only the unseen ones."""
        return [item for item in items if not self.is_seen(item[0])]

    # -------------------------------------------------------------- signals

    def record_signal(self, signal: SignalRecord) -> int:
        created_at = (signal.created_at or datetime.now(UTC)).isoformat()
        cursor = self.conn.execute(
            "INSERT INTO llm_signals "
            "(created_at, ticker, signal_type, severity, thesis, news_guid, "
            "prompt, response, model) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                created_at,
                signal.ticker,
                signal.signal_type,
                signal.severity,
                signal.thesis,
                signal.news_guid,
                signal.prompt,
                signal.response,
                signal.model,
            ),
        )
        self.conn.commit()
        return int(cursor.lastrowid)

    def recent_signals(self, ticker: str | None = None, limit: int = 50) -> list[sqlite3.Row]:
        if ticker:
            rows = self.conn.execute(
                "SELECT * FROM llm_signals WHERE ticker = ? ORDER BY created_at DESC LIMIT ?",
                (ticker, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM llm_signals ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return rows

    def set_outcome(
        self,
        signal_id: int,
        *,
        outcome_30d: str | None = None,
        outcome_90d: str | None = None,
    ) -> None:
        if outcome_30d is not None:
            self.conn.execute(
                "UPDATE llm_signals SET outcome_30d = ? WHERE id = ?", (outcome_30d, signal_id)
            )
        if outcome_90d is not None:
            self.conn.execute(
                "UPDATE llm_signals SET outcome_90d = ? WHERE id = ?", (outcome_90d, signal_id)
            )
        self.conn.commit()

    # ------------------------------------------------------- price snapshots

    def record_price_snapshot(
        self, ticker: str, price: float | None, previous_close: float | None, sector: str | None
    ) -> None:
        self.conn.execute(
            "INSERT INTO price_snapshots (ticker, price, previous_close, sector, captured_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (ticker, price, previous_close, sector, _now_iso()),
        )
        self.conn.commit()

    def last_price_snapshot(self, ticker: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM price_snapshots WHERE ticker = ? ORDER BY captured_at DESC LIMIT 1",
            (ticker,),
        ).fetchone()

    # -------------------------------------------------------------------- meta

    def get_meta(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        self.conn.commit()

    def last_full_analysis_at(self) -> datetime | None:
        value = self.get_meta("last_full_analysis_at")
        return datetime.fromisoformat(value) if value else None

    def mark_full_analysis_run(self, when: datetime | None = None) -> None:
        self.set_meta("last_full_analysis_at", (when or datetime.now(UTC)).isoformat())
