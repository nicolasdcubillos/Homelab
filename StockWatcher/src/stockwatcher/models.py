"""Core domain models.

Everything here is provider-agnostic.  Providers translate a store's payload
into :class:`Product` / :class:`Variant`; the rest of the engine only ever sees
these types.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from .sizes import Gender, Size, parse_size


@dataclass(frozen=True)
class Store:
    """A retailer the watcher knows how to talk to."""

    host: str
    provider: str = "shopify"
    country: str = "US"
    name: str | None = None
    enabled: bool = True
    delay: float | None = None
    options: dict = field(default_factory=dict)
    source: str = "seed"

    @property
    def display_name(self) -> str:
        return self.name or self.host

    @property
    def base_url(self) -> str:
        return f"https://{self.host}"


@dataclass(frozen=True)
class ProductRef:
    """A search hit: enough to fetch the full product later."""

    store_host: str
    provider: str
    url: str
    title: str
    price: Decimal | None = None
    handle: str | None = None
    raw: dict = field(default_factory=dict, compare=False, repr=False)


@dataclass(frozen=True)
class Variant:
    """One purchasable variation of a product (a shoe size, a capacity, ...)."""

    label: str
    available: bool
    sku: str | None = None
    price: Decimal | None = None
    size: Size | None = None

    @classmethod
    def create(
        cls,
        label: str,
        available: bool,
        *,
        sku: str | None = None,
        price: Decimal | None = None,
        gender: Gender = Gender.UNISEX,
    ) -> Variant:
        return cls(
            label=str(label).strip(),
            available=bool(available),
            sku=sku,
            price=price,
            size=parse_size(label, gender),
        )


@dataclass
class Product:
    """A normalized product listing with its variants."""

    ref: ProductRef
    title: str
    url: str
    variants: list[Variant] = field(default_factory=list)
    price: Decimal | None = None
    currency: str = "USD"
    vendor: str | None = None
    colorway: str | None = None
    gender: Gender = Gender.UNISEX
    store_host: str = ""
    provider: str = ""

    @property
    def searchable_text(self) -> str:
        parts = [self.title, self.colorway or "", self.vendor or "", self.url]
        return " ".join(p for p in parts if p)


@dataclass(frozen=True)
class Hit:
    """A watch matched an in-stock variant at a store."""

    watch_name: str
    store_host: str
    store_name: str
    provider: str
    product_title: str
    product_url: str
    variant_label: str
    price: Decimal | None
    currency: str
    colorway: str | None = None
    color_matched: bool = True
    country: str = "US"
    detected_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def key(self) -> str:
        """Stable identity used by the state store for transition detection."""
        raw = "|".join(
            [
                self.watch_name.lower(),
                self.store_host.lower(),
                _canonical_url(self.product_url),
                self.variant_label.lower(),
            ]
        )
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    @property
    def price_text(self) -> str:
        if self.price is None:
            return "n/a"
        return f"${self.price:,.2f} {self.currency}"


@dataclass(frozen=True)
class Alert:
    """A batch of hits to notify about."""

    hits: tuple[Hit, ...]

    @property
    def is_empty(self) -> bool:
        return not self.hits


@dataclass
class StoreRecord:
    """Registry bookkeeping for a store (persisted in the state store)."""

    host: str
    provider: str = "shopify"
    country: str = "US"
    enabled: bool = True
    first_seen: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_ok: datetime | None = None
    fail_count: int = 0
    source: str = "discovery"
    note: str = ""

    def to_store(self) -> Store:
        return Store(
            host=self.host,
            provider=self.provider,
            country=self.country,
            enabled=self.enabled,
            source=self.source,
        )


@dataclass
class RunSummary:
    """Per-run telemetry, logged at the end of every scan."""

    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    stores_scanned: int = 0
    stores_failed: int = 0
    products_seen: int = 0
    variants_seen: int = 0
    hits: int = 0
    new_hits: int = 0
    notifications_sent: int = 0
    errors: list[str] = field(default_factory=list)
    discovered_stores: list[str] = field(default_factory=list)
    #: host -> wall-clock seconds, used to spot a store that drags a run out.
    store_seconds: dict[str, float] = field(default_factory=dict)

    @property
    def duration_seconds(self) -> float:
        return (datetime.now(UTC) - self.started_at).total_seconds()

    def as_dict(self) -> dict:
        return {
            "duration_s": round(self.duration_seconds, 2),
            "stores_scanned": self.stores_scanned,
            "stores_failed": self.stores_failed,
            "products_seen": self.products_seen,
            "variants_seen": self.variants_seen,
            "hits": self.hits,
            "new_hits": self.new_hits,
            "notifications_sent": self.notifications_sent,
            "discovered_stores": self.discovered_stores,
            "slowest_stores": dict(
                sorted(self.store_seconds.items(), key=lambda kv: kv[1], reverse=True)[:5]
            ),
            "errors": self.errors[:20],
        }


def _canonical_url(url: str) -> str:
    return url.split("?")[0].rstrip("/").lower()
