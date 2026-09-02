"""State store implementations and the factory that picks one."""

from __future__ import annotations

from ..config import StateConfig
from .base import (
    RUN_COUNTER_KEY,
    NullStateStore,
    StateStore,
    TransitionResult,
    detect_transitions,
)
from .sqlite_store import SqliteStateStore

__all__ = [
    "RUN_COUNTER_KEY",
    "NullStateStore",
    "SqliteStateStore",
    "StateStore",
    "TransitionResult",
    "build_state_store",
    "detect_transitions",
]


def build_state_store(config: StateConfig) -> StateStore:
    backend = (config.backend or "sqlite").lower()
    if backend in ("sqlite", "local"):
        return SqliteStateStore(config.path)
    if backend in ("azure_table", "azure", "table"):
        from .azure_table import AzureTableStateStore

        return AzureTableStateStore(
            table_name=config.table_name,
            connection_string_env=config.connection_string_env,
        )
    if backend in ("none", "memory", "null"):
        return NullStateStore()
    raise ValueError(f"unknown state backend {config.backend!r}")
