"""YAML configuration loading.

The vocabulary is intentionally generic (``variants``, not ``sizes``) so the
same engine watches sneakers today and GPUs or concert tickets tomorrow.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field, replace
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml

from .models import Store
from .sizes import Gender


class ConfigError(ValueError):
    """Raised when the YAML config is malformed."""


#: Providers that need a real browser, and so a chromium install.
BROWSER_PROVIDERS = frozenset({"playwright", "nike"})

#: ``email:me@example.com`` — an explicit channel in front of a destination.
_CHANNEL_PREFIX = re.compile(r"^([a-z][a-z0-9_]*):(.+)$", re.IGNORECASE)


@dataclass(frozen=True)
class NotifyTarget:
    """A channel, plus optionally where that channel should deliver.

    ``notify: [whatsapp]`` yields ``NotifyTarget("whatsapp")`` and the
    destination comes from ``--notify-to`` or the environment;
    ``notify: ["email:me@example.com"]`` pins it in the YAML.  See
    :func:`stockwatcher.notifiers.base.resolve_destinations` for the full
    precedence, which is a security contract in a multi-user deployment.
    """

    channel: str
    to: tuple[str, ...] = ()


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
    notify: list[NotifyTarget] = field(default_factory=lambda: [NotifyTarget("whatsapp")])
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
    #: Optional path to a *shared*, append-only store registry.  Discovery
    #: writes promotions there instead of into the state store, so a fleet of
    #: users sharing this checkout only pays for each discovery once — see
    #: :mod:`stockwatcher.discovery.registry`.  Unset keeps the single-user
    #: behaviour (promotions land in the state store).
    registry_path: str | None = None


@dataclass
class NotifyConfig:
    max_hits_per_message: int = 6
    max_messages_per_run: int = 5
    #: channel -> destinations declared in the YAML (``notify_options.to``).
    #: Lowest precedence; the environment and ``--notify-to`` both win.
    to: dict[str, list[str]] = field(default_factory=dict)
    #: channel -> destinations passed with ``--notify-to``.  Highest
    #: precedence: an explicit per-invocation destination beats every global.
    override_to: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class RuntimeConfig:
    concurrency: int = 18
    timeout: float = 20.0
    default_delay: float = 0.0
    #: Global requests/second ceiling. Shopify rate-limits per client IP across
    #: every storefront it hosts, so this budget is shared by all stores.
    rate: float = 5.0
    max_products_per_query: int = 8
    max_queries_per_store: int = 3
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


def _split_destinations(value: Any) -> list[str]:
    """``"a@x.com, b@x.com"`` or ``["a@x.com", "b@x.com"]`` -> a flat list."""
    items = value if isinstance(value, (list, tuple)) else [value]
    out: list[str] = []
    for item in items:
        if item is None:
            continue
        for part in str(item).replace(";", ",").split(","):
            part = part.strip()
            if part and part not in out:
                out.append(part)
    return out


def _infer_channel(destination: str) -> str:
    """Route a destination with no explicit channel by its shape.

    An address goes to email, anything else (an E.164 number) to WhatsApp.
    This is what lets ``--notify-to me@example.com`` do the obvious thing.
    """
    return "email" if "@" in destination else "whatsapp"


def parse_notify_destinations(values: Any) -> dict[str, list[str]]:
    """Parse ``--notify-to`` / ``notify_options.to`` into channel -> destinations.

    Accepts, in any combination:

    * ``"email:me@example.com"``           explicit channel
    * ``"me@example.com"``                 channel inferred from the shape
    * ``"whatsapp:+57300,+57301"``         several destinations for one channel
    * ``{"email": ["me@example.com"]}``    a mapping (YAML only)
    """
    out: dict[str, list[str]] = {}

    def add(channel: str, destination: str) -> None:
        bucket = out.setdefault(channel, [])
        if destination not in bucket:
            bucket.append(destination)

    if not values:
        return out
    if isinstance(values, dict):
        for channel, raw in values.items():
            name = str(channel).strip().lower()
            if not name:
                raise ConfigError("a notify destination needs a channel name")
            for destination in _split_destinations(raw):
                add(name, destination)
        return out

    entries = values if isinstance(values, (list, tuple)) else [values]
    for entry in entries:
        text = str(entry).strip()
        if not text or text.endswith(":"):
            raise ConfigError(f"empty notify destination: {entry!r}")
        match = _CHANNEL_PREFIX.match(text)
        channel = match.group(1).lower() if match else None
        destinations = _split_destinations(match.group(2) if match else text)
        if not destinations:
            raise ConfigError(f"empty notify destination: {entry!r}")
        for destination in destinations:
            add(channel or _infer_channel(destination), destination)
    return out


def _notify_target(raw: Any) -> NotifyTarget:
    """``"whatsapp"`` or ``"email:me@example.com"`` -> a :class:`NotifyTarget`."""
    text = str(raw).strip()
    if not text or text.endswith(":"):
        raise ConfigError(f"empty 'notify' entry: {raw!r}")
    match = _CHANNEL_PREFIX.match(text)
    if match:
        return NotifyTarget(
            channel=match.group(1).lower(),
            to=tuple(_split_destinations(match.group(2))),
        )
    if "@" in text or text.startswith("+"):
        raise ConfigError(
            f"notify entry {text!r} looks like a destination; write it as "
            f"'{_infer_channel(text)}:{text}'"
        )
    return NotifyTarget(channel=text.lower())


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
        notify=[_notify_target(n) for n in _as_list(merged.get("notify"))]
        or [NotifyTarget("whatsapp")],
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


def _notify_config_from_dict(raw: Any) -> NotifyConfig:
    """Build :class:`NotifyConfig`, normalizing the ``to`` destinations.

    ``override_to`` is deliberately *not* readable from the YAML: it carries
    the ``--notify-to`` flag, whose whole point is to be per-invocation.
    """
    if not raw:
        return NotifyConfig()
    if not isinstance(raw, dict):
        raise ConfigError(f"expected a mapping for NotifyConfig, got {raw!r}")
    known = {"max_hits_per_message", "max_messages_per_run", "to"}
    unknown = set(raw) - known
    if unknown:
        raise ConfigError(f"unknown NotifyConfig keys: {sorted(unknown)}")
    defaults = NotifyConfig()
    return NotifyConfig(
        max_hits_per_message=int(raw.get("max_hits_per_message", defaults.max_hits_per_message)),
        max_messages_per_run=int(raw.get("max_messages_per_run", defaults.max_messages_per_run)),
        to=parse_notify_destinations(raw.get("to")),
    )


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

    config = Config(
        watches=watches,
        stores=deduped,
        discovery=_dataclass_from_dict(
            DiscoveryConfig, data.get("discovery") or stores_data.get("discovery")
        ),
        notify=_notify_config_from_dict(data.get("notify_options")),
        runtime=_dataclass_from_dict(RuntimeConfig, data.get("runtime")),
        state=_dataclass_from_dict(StateConfig, data.get("state")),
    )
    return merge_registry_stores(apply_env_overrides(config))


def apply_env_overrides(config: Config) -> Config:
    """Let environment variables win over the YAML.

    Container Apps injects configuration as env vars, and the image ships the
    same YAML for every environment, so the deployed job needs a way to switch
    the state backend without a rebuild.
    """
    backend = os.getenv("STOCKWATCHER_STATE_BACKEND")
    if backend:
        config.state.backend = backend
    path = os.getenv("STOCKWATCHER_STATE_PATH")
    if path:
        config.state.path = path
    table = os.getenv("AZURE_TABLE_NAME")
    if table:
        config.state.table_name = table
    registry = os.getenv("STOCKWATCHER_DISCOVERY_REGISTRY")
    if registry:
        config.discovery.registry_path = registry
    rate = os.getenv("STOCKWATCHER_RATE")
    if rate:
        try:
            config.runtime.rate = float(rate)
        except ValueError:
            raise ConfigError(f"STOCKWATCHER_RATE must be a number, got {rate!r}") from None

    # Browser-backed stores ship disabled, because they need a chromium that a
    # plain `pip install` does not provide.  The container image does install
    # it, so it opts back in here rather than shipping a second YAML.
    if _env_flag("STOCKWATCHER_ENABLE_BROWSER_STORES"):
        config.stores = [
            replace(store, enabled=True)
            if store.provider in BROWSER_PROVIDERS and not store.enabled
            else store
            for store in config.stores
        ]
    return config


def _env_flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def merge_registry_stores(config: Config) -> Config:
    """Fold the shared discovery registry into the configured store list.

    Discovery promotes stores into a registry shared by every user rather than
    into one user's private state (see :mod:`stockwatcher.discovery.registry`),
    so that file has to be read back here — otherwise nobody would ever scan
    what discovery found.  Configured stores win on provider/country, and the
    call is idempotent so the CLI can re-run it after ``--discovery-registry``.
    """
    path = config.discovery.registry_path
    if not path:
        return config
    registry_file = Path(path)
    if not registry_file.exists():
        return config
    known = {s.host for s in config.stores}
    for raw in _read_yaml(registry_file).get("stores") or []:
        store = _store_from_dict(raw)
        if store.host in known:
            continue
        known.add(store.host)
        config.stores.append(store)
    return config
