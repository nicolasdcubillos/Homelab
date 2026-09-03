"""Where discovery puts the stores it promotes.

Discovery used to write straight into the active :class:`StateStore`, which was
free when one person ran the watcher: the store registry and the "already seen
this variant" bookkeeping could share one database.

That stopped being free once the same checkout is invoked once per user, each
with their own ``--state-path``.  A store registry that lives in per-user state
means every user re-runs the same web searches and re-probes the same hosts to
rediscover what somebody else already found — pure waste of the search API
quota and of HTTP requests against shops that did nothing to deserve them.

So the write target is now pluggable:

* :class:`StateStoreRegistry` keeps the original single-user behaviour and is
  still the default.
* :class:`YamlStoreRegistry` writes to a **shared, append-only** YAML file (the
  same shape as ``config/stores.yaml``), named with ``--discovery-registry``.
  Every user reads the whole file as known hosts, so a host is discovered once
  for the whole fleet.

Append-only is what makes sharing safe: entries are added under an exclusive
file lock and never rewritten or removed, so concurrent runs cannot clobber
each other, and a store retired for one user (which stays in that user's
private state) is not retired for everybody.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import yaml

from ..config import DiscoveryConfig
from ..models import StoreRecord
from ..state import StateStore

try:  # pragma: no cover - POSIX everywhere we deploy
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None

log = logging.getLogger(__name__)

HEADER = """\
# StockWatcher discovery registry — managed file, append-only.
#
# `stockwatcher discover` adds every store it promotes here instead of into a
# user's private state, so several users sharing this checkout only pay for
# each discovery once.  Entries are never rewritten or removed; delete the
# file to start over.  Same shape as config/stores.yaml.
stores:
"""


class StoreRegistry(ABC):
    """The registry discovery promotes into."""

    @abstractmethod
    async def known_hosts(self) -> set[str]:
        """Hosts already in the registry, which must not be probed again."""

    @abstractmethod
    async def add(self, record: StoreRecord) -> None:
        """Record a newly promoted store."""

    @abstractmethod
    async def list_stores(self) -> list[StoreRecord]:
        """Every record in the registry."""


class StateStoreRegistry(StoreRegistry):
    """Legacy single-user target: the run's own state store."""

    def __init__(self, state: StateStore) -> None:
        self.state = state

    async def known_hosts(self) -> set[str]:
        # Only *enabled* records count as known, so a store the runner
        # auto-retired can still be rediscovered later — the behaviour this
        # class exists to preserve.
        return {r.host for r in await self.state.list_stores() if r.enabled}

    async def add(self, record: StoreRecord) -> None:
        await self.state.upsert_store(record)

    async def list_stores(self) -> list[StoreRecord]:
        return await self.state.list_stores()


class YamlStoreRegistry(StoreRegistry):
    """Shared, append-only YAML file, safe for concurrent users."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    async def known_hosts(self) -> set[str]:
        return {r.host for r in await self.list_stores()}

    async def list_stores(self) -> list[StoreRecord]:
        return await asyncio.to_thread(self._read)

    async def add(self, record: StoreRecord) -> None:
        await asyncio.to_thread(self._append, record)

    # ------------------------------------------------------------------ file

    def _read(self) -> list[StoreRecord]:
        if not self.path.exists():
            return []
        try:
            data = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            log.warning("discovery registry %s is unreadable: %s", self.path, exc)
            return []
        if not isinstance(data, dict):
            return []
        return [_record_from_dict(raw) for raw in data.get("stores") or [] if raw]

    def _append(self, record: StoreRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # "a+" so every write goes to the end regardless of what another
        # process appended meanwhile; the lock only has to protect the
        # read-then-decide, and a single small append is atomic under it.
        with self.path.open("a+", encoding="utf-8") as fh, _locked(fh):
            fh.seek(0)
            text = fh.read()
            if not text.strip():
                fh.write(HEADER)
            elif record.host in _hosts_in(text):
                return
            elif not text.endswith("\n"):
                fh.write("\n")
            fh.write(_entry_text(record))
            fh.flush()


def build_store_registry(config: DiscoveryConfig, state: StateStore) -> StoreRegistry:
    """Pick the registry ``config`` asks for, defaulting to the state store."""
    if config.registry_path:
        return YamlStoreRegistry(config.registry_path)
    return StateStoreRegistry(state)


# --------------------------------------------------------------------------
# YAML plumbing
# --------------------------------------------------------------------------


@contextmanager
def _locked(fh):
    """Exclusive advisory lock, so two users never interleave an append."""
    if fcntl is None:  # pragma: no cover - Windows
        yield
        return
    fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
    try:
        yield
    finally:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _hosts_in(text: str) -> set[str]:
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError:  # pragma: no cover - defensive
        return set()
    if not isinstance(data, dict):  # pragma: no cover - defensive
        return set()
    return {
        str(raw["host"]).strip().lower()
        for raw in data.get("stores") or []
        if isinstance(raw, dict) and raw.get("host")
    }


def _entry_text(record: StoreRecord) -> str:
    payload = {
        "host": record.host,
        "provider": record.provider,
        "country": record.country,
        "enabled": True,
        "source": record.source,
        "first_seen": (record.first_seen or datetime.now(UTC)).isoformat(),
        "note": record.note,
    }
    dumped = yaml.safe_dump(
        payload, default_flow_style=True, sort_keys=False, width=10**6, allow_unicode=True
    ).strip()
    return f"  - {dumped}\n"


def _record_from_dict(raw: dict) -> StoreRecord:
    first_seen = _as_datetime(raw.get("first_seen"))
    return StoreRecord(
        host=str(raw.get("host", "")).strip().lower(),
        provider=str(raw.get("provider") or "shopify").strip().lower(),
        country=str(raw.get("country") or "US").upper(),
        enabled=bool(raw.get("enabled", True)),
        first_seen=first_seen or datetime.now(UTC),
        last_ok=_as_datetime(raw.get("last_ok")),
        fail_count=int(raw.get("fail_count") or 0),
        source=str(raw.get("source") or "discovery"),
        note=str(raw.get("note") or ""),
    )


def _as_datetime(value) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:  # pragma: no cover - defensive
        return None


__all__ = [
    "StateStoreRegistry",
    "StoreRegistry",
    "YamlStoreRegistry",
    "build_store_registry",
]
