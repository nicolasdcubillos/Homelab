"""Provider plug-in system.

A provider knows how to talk to one *kind* of storefront.  Instances are bound
to a single :class:`~stockwatcher.models.Store`, so the same class (e.g. the
generic Shopify one) serves dozens of hosts.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable

from ..http import HttpClient
from ..models import Product, ProductRef, Store

log = logging.getLogger(__name__)


class ProviderError(RuntimeError):
    """A store-level failure.  Never fatal: the runner logs and moves on."""


class Provider(ABC):
    """Search a store and normalize one of its products."""

    name: str = "base"
    #: Minimum seconds between requests to this provider's host.
    default_delay: float = 0.0

    def __init__(self, store: Store, http: HttpClient) -> None:
        self.store = store
        self.http = http

    @property
    def delay(self) -> float:
        return self.store.delay if self.store.delay is not None else self.default_delay

    @abstractmethod
    async def search(self, query: str) -> list[ProductRef]:
        """Return candidate products for a free-text query."""

    @abstractmethod
    async def fetch(self, ref: ProductRef) -> Product | None:
        """Return the full product with per-variant availability."""

    async def aclose(self) -> None:
        """Release provider-owned resources (browsers, sessions, ...)."""


ProviderFactory = Callable[[Store, HttpClient], Provider]

_REGISTRY: dict[str, ProviderFactory] = {}


def register_provider(name: str, factory: ProviderFactory) -> None:
    _REGISTRY[name.lower()] = factory


def available_providers() -> list[str]:
    return sorted(_REGISTRY)


def build_provider(store: Store, http: HttpClient) -> Provider:
    factory = _REGISTRY.get(store.provider.lower())
    if factory is None:
        raise ProviderError(
            f"unknown provider {store.provider!r} for {store.host} "
            f"(known: {', '.join(available_providers()) or 'none'})"
        )
    return factory(store, http)
