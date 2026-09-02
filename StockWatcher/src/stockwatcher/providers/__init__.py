"""Provider registry.

Importing this package registers every built-in provider.  The Playwright
provider is optional: if the ``playwright`` extra is not installed it simply is
not registered and stores using it are skipped with a clear warning.
"""

from __future__ import annotations

import logging

from .base import (
    Provider,
    ProviderError,
    available_providers,
    build_provider,
    register_provider,
)
from .footlocker import FootLockerProvider
from .shopify import ShopifyProvider

log = logging.getLogger(__name__)

try:  # pragma: no cover - depends on optional extra
    from .playwright_provider import PlaywrightProvider

    _PLAYWRIGHT_AVAILABLE = True
except Exception as exc:  # pragma: no cover - optional dependency
    PlaywrightProvider = None  # type: ignore[assignment]
    _PLAYWRIGHT_AVAILABLE = False
    log.debug("playwright provider unavailable: %s", exc)

__all__ = [
    "FootLockerProvider",
    "PlaywrightProvider",
    "Provider",
    "ProviderError",
    "ShopifyProvider",
    "available_providers",
    "build_provider",
    "register_provider",
]
