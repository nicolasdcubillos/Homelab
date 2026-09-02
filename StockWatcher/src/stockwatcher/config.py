"""YAML configuration loading.

The vocabulary is intentionally generic (``variants``, not ``sizes``) so the
same engine watches sneakers today and GPUs or concert tickets tomorrow.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml

from .models import Store
from .sizes import Gender


class ConfigError(ValueError):
    """Raised when the YAML config is malformed."""


@dataclass
class Watch:
    """One thing the user wants to be told about."""

    name: str
    match: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    variants: list[str] = field(default_factory=list)
    gender: Gender = Gender.UNISEX
    colors: list[str] = field(default_factory=list)
    max_price: Decimal | None = None
    currency: str = "USD"
    countries: list[str] = field(default_factory=lambda: ["US"])
    notify: list[str] = field(default_factory=lambda: ["whatsapp"])
    stores: list[str] = field(default_factory=list)
    queries: list[str] = field(default_factory=list)
    enabled: bool = True

    @property
    def search_queries(self) -> list[str]:
        """Terms fed to store search endpoints.

        Store search is fuzzy and *narrow* queries hurt recall badly: on
        kith.com ``"mind 002 flyknit"`` returns knitwear and misses the shoe
        entirely, while ``"mind 002"`` finds it.  So every match term longer
        than two words also contributes a two-word prefix.  Precision is
        recovered later by :mod:`stockwatcher.matching`, which re-checks the
        full match groups against the real product title.
        """
        if self.queries:
            return self.queries
        out: list[str] = []
        for term in self.match:
            out.append(term)
            tokens = term.split()
            if len(tokens) > 2:
                out.append(" ".join(tokens[:2]))
        return list(dict.fromkeys(out))

    @property
    def match_groups(self) -> list[list[str]]:
        """``["mind 002 flyknit"]`` -> ``[["mind", "002", "flyknit"]]``.

        A product matches when *every* token of *any* group is present.
        """
        groups = []
        for term in self.match:
            tokens = [t for t in str(term).lower().split() if t]
            if tokens:
                groups.append(tokens)
        return groups


@dataclass
class DiscoveryConfig:
    enabled: bool = True
    every_n_runs: int = 3
    backend: str = "auto"
    max_candidates: int = 25
    max_promotions_per_run: int = 10
    retire_after_failures: int = 5
    timeout: float = 8.0


@dataclass
class NotifyConfig:
    max_hits_per_message: int = 6
    max_messages_per_run: int = 5


@dataclass
class RuntimeConfig:
    concurrency: int = 18
    timeout: float = 20.0
    default_delay: float = 0.0
    max_products_per_query: int = 8
    max_queries_per_store: int = 4
    user_agent: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    )


@dataclass
class StateConfig:
    backend: str = "sqlite"
    path: str = "data/stockwatcher.db"
    table_name: str = "stockwatcher"
    connection_string_env: str = "AZURE_STORAGE_CONNECTION_STRING"


@dataclass
class Config:
    watches: list[Watch] = field(default_factory=list)
    stores: list[Store] = field(default_factory=list)
    discovery: DiscoveryConfig = field(default_factory=DiscoveryConfig)
    notify: NotifyConfig = field(default_factory=NotifyConfig)
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    state: StateConfig = field(default_factory=StateConfig)

    def enabled_watches(self) -> list[Watch]:
        return [w for w in self.watches if w.enabled]

    def enabled_stores(self) -> list[Store]:
        return [s for s in self.stores if s.enabled]


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value]
    raise ConfigError(f"expected a string or list, got {value!r}")


def _as_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError) as exc:
        raise ConfigError(f"invalid decimal: {value!r}") from exc


def _as_gender(value: Any) -> Gender:
    if value is None:
        return Gender.UNISEX
    text = str(value).strip().lower()
    aliases = {
        "m": Gender.MENS,
        "men": Gender.MENS,
        "mens": Gender.MENS,
        "men's": Gender.MENS,
        "w": Gender.WOMENS,
        "women": Gender.WOMENS,
        "womens": Gender.WOMENS,
        "women's": Gender.WOMENS,
        "unisex": Gender.UNISEX,
        "any": Gender.UNISEX,
        "": Gender.UNISEX,
    }
    if text not in aliases:
        raise ConfigError(f"unknown gender {value!r} (use mens/womens/unisex)")
    return aliases[text]


def _watch_from_dict(raw: dict, defaults: dict) -> Watch:
    if not isinstance(raw, dict):
        raise ConfigError(f"each watch must be a mapping, got {raw!r}")
    merged = {**defaults, **raw}
    name = merged.get("name")
    if not name:
        raise ConfigError("every watch needs a 'name'")
    match = _as_list(merged.get("match"))
    if not match:
        raise ConfigError(f"watch {name!r} needs at least one 'match' term")
    return Watch(
        name=str(name),
        match=[m.lower() for m in match],
        exclude=[e.lower() for e in _as_list(merged.get("exclude"))],
        variants=_as_list(merged.get("variants") or merged.get("sizes")),
        gender=_as_gender(merged.get("gender")),
        colors=[c.lower() for c in _as_list(merged.get("colors"))],
        max_price=_as_decimal(merged.get("max_price")),
        currency=str(merged.get("currency") or "USD").upper(),
        countries=[c.upper() for c in _as_list(merged.get("countries")) or ["US"]],
        notify=_as_list(merged.get("notify")) or ["whatsapp"],
        stores=[s.lower() for s in _as_list(merged.get("stores"))],
        queries=_as_list(merged.get("queries")),
        enabled=bool(merged.get("enabled", True)),
    )


def _store_from_dict(raw: dict | str) -> Store:
    if isinstance(raw, str):
        return Store(host=raw.strip().lower())
    if not isinstance(raw, dict):
        raise ConfigError(f"each store must be a mapping or host string, got {raw!r}")
    host = raw.get("host")
    if not host:
        raise ConfigError("every store needs a 'host'")
    delay = raw.get("delay")
    return Store(
        host=str(host).strip().lower(),
        provider=str(raw.get("provider") or "shopify").strip().lower(),
        country=str(raw.get("country") or "US").upper(),
        name=raw.get("name"),
        enabled=bool(raw.get("enabled", True)),
        delay=float(delay) if delay is not None else None,
        options=dict(raw.get("options") or {}),
        source=str(raw.get("source") or "seed"),
    )


def _dataclass_from_dict(cls, raw: Any):
    if not raw:
        return cls()
    if not isinstance(raw, dict):
        raise ConfigError(f"expected a mapping for {cls.__name__}, got {raw!r}")
    known = {f.name for f in cls.__dataclass_fields__.values()}
    unknown = set(raw) - known
    if unknown:
        raise ConfigError(f"unknown {cls.__name__} keys: {sorted(unknown)}")
    return cls(**raw)


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        raise ConfigError(f"config file not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must contain a YAML mapping at the top level")
    return data


def load_config(
    watches_path: str | os.PathLike[str],
    stores_path: str | os.PathLike[str] | None = None,
) -> Config:
    """Load ``watches.yaml`` (and optionally ``stores.yaml``) into a :class:`Config`."""
    watches_file = Path(watches_path)
    data = _read_yaml(watches_file)

    defaults = data.get("defaults") or {}
    if not isinstance(defaults, dict):
        raise ConfigError("'defaults' must be a mapping")

    raw_watches = data.get("watches")
    if not raw_watches:
        raise ConfigError(f"{watches_file} defines no watches")
    watches = [_watch_from_dict(w, defaults) for w in raw_watches]

    stores_data: dict = {}
    if stores_path:
        stores_file = Path(stores_path)
        if stores_file.exists():
            stores_data = _read_yaml(stores_file)

    raw_stores = data.get("stores") or stores_data.get("stores") or []
    stores = [_store_from_dict(s) for s in raw_stores]
    seen: set[str] = set()
    deduped: list[Store] = []
    for store in stores:
        if store.host in seen:
            continue
        seen.add(store.host)
        deduped.append(store)

    return Config(
        watches=watches,
        stores=deduped,
        discovery=_dataclass_from_dict(
            DiscoveryConfig, data.get("discovery") or stores_data.get("discovery")
        ),
        notify=_dataclass_from_dict(NotifyConfig, data.get("notify_options")),
        runtime=_dataclass_from_dict(RuntimeConfig, data.get("runtime")),
        state=_dataclass_from_dict(StateConfig, data.get("state")),
    )
