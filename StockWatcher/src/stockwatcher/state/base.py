"""State storage interface + the transition logic that suppresses repeat alerts.

The user must hear about a restock exactly once: only the transition
``unavailable -> available`` fires a notification.  A variant that stays in
stock for six hours must not produce six WhatsApp messages.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from types import TracebackType

from ..models import Hit, StoreRecord

#: Key used to persist the monotonically increasing run counter.
RUN_COUNTER_KEY = "run_counter"


@dataclass
class TransitionResult:
    """Outcome of comparing this run's observations against stored state."""

    new_hits: list[Hit] = field(default_factory=list)
    updates: dict[str, bool] = field(default_factory=dict)
    still_available: int = 0

    @property
    def has_new(self) -> bool:
        return bool(self.new_hits)


def detect_transitions(
    observations: Iterable[tuple[Hit, bool]],
    previous: Mapping[str, bool],
) -> TransitionResult:
    """Return the hits that just became available, plus the new state map.

    ``previous`` maps state key -> last known availability.  A key that has
    never been seen and is available *does* alert: from the user's point of
    view it appeared out of nowhere, which is exactly what they want to know.
    """
    result = TransitionResult()
    seen: dict[str, tuple[Hit, bool]] = {}
    for hit, available in observations:
        key = hit.key
        # Same variant reported twice in one run (e.g. two search queries hit
        # the same product): available wins.
        existing = seen.get(key)
        if existing is None or (available and not existing[1]):
            seen[key] = (hit, available)

    for key, (hit, available) in seen.items():
        result.updates[key] = available
        if not available:
            continue
        if previous.get(key) is True:
            result.still_available += 1
            continue
        result.new_hits.append(hit)
    return result


class StateStore(ABC):
    """Persistence for availability state, the store registry and run metadata."""

    @abstractmethod
    async def open(self) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...

    @abstractmethod
    async def get_states(self, keys: Iterable[str]) -> dict[str, bool]: ...

    @abstractmethod
    async def set_states(self, updates: Mapping[str, bool]) -> None: ...

    @abstractmethod
    async def list_stores(self) -> list[StoreRecord]: ...

    @abstractmethod
    async def upsert_store(self, record: StoreRecord) -> None: ...

    @abstractmethod
    async def get_meta(self, key: str) -> str | None: ...

    @abstractmethod
    async def set_meta(self, key: str, value: str) -> None: ...

    async def next_run_number(self) -> int:
        """Increment and return the run counter (used to schedule discovery)."""
        raw = await self.get_meta(RUN_COUNTER_KEY)
        try:
            current = int(raw) if raw is not None else 0
        except ValueError:  # pragma: no cover - defensive
            current = 0
        current += 1
        await self.set_meta(RUN_COUNTER_KEY, str(current))
        return current

    async def __aenter__(self) -> StateStore:
        await self.open()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()


class NullStateStore(StateStore):
    """In-memory store used by ``--no-state`` and tests."""

    def __init__(self) -> None:
        self._states: dict[str, bool] = {}
        self._stores: dict[str, StoreRecord] = {}
        self._meta: dict[str, str] = {}

    async def open(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def get_states(self, keys: Iterable[str]) -> dict[str, bool]:
        keys = list(keys)
        return {k: v for k, v in self._states.items() if k in set(keys)}

    async def set_states(self, updates: Mapping[str, bool]) -> None:
        self._states.update(updates)

    async def list_stores(self) -> list[StoreRecord]:
        return list(self._stores.values())

    async def upsert_store(self, record: StoreRecord) -> None:
        self._stores[record.host] = record

    async def get_meta(self, key: str) -> str | None:
        return self._meta.get(key)

    async def set_meta(self, key: str, value: str) -> None:
        self._meta[key] = value
