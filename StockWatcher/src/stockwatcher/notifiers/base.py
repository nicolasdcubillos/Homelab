"""Notifier plug-in system."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Sequence
from decimal import Decimal

from ..models import Alert, Hit


class NotifierError(RuntimeError):
    """Delivery failed.  Logged by the runner; never aborts a scan."""


class Notifier(ABC):
    """Deliver an :class:`~stockwatcher.models.Alert` somewhere."""

    name: str = "base"

    #: Messages actually dispatched, cumulative.  WhatsApp bills per message
    #: and a batch of restocks can collapse into one, so the run summary needs
    #: this alongside the hit count.  Implementations increment it in ``send``.
    messages_sent: int = 0

    @abstractmethod
    async def send(self, alert: Alert) -> None: ...

    async def aclose(self) -> None:
        """Release notifier-owned resources."""


NotifierFactory = Callable[[dict], Notifier]

_REGISTRY: dict[str, NotifierFactory] = {}


def register_notifier(name: str, factory: NotifierFactory) -> None:
    _REGISTRY[name.lower()] = factory


def available_notifiers() -> list[str]:
    return sorted(_REGISTRY)


def build_notifier(name: str, options: dict | None = None) -> Notifier:
    factory = _REGISTRY.get(name.lower())
    if factory is None:
        raise NotifierError(
            f"unknown notifier {name!r} (known: {', '.join(available_notifiers()) or 'none'})"
        )
    return factory(options or {})


def group_hits(hits: Iterable[Hit]) -> list[list[Hit]]:
    """Group hits by (watch, store, product, **price**) so one message covers many sizes.

    Price is part of the key on purpose.  On consignment stores every size is
    priced separately, so a group spanning several prices could only be
    summarised as "from $X" — and the user explicitly needs the price *of the
    size that is available*.  Keying on price means every message quotes one
    exact figure; sizes that happen to share a price (the common case) still
    collapse into a single message.
    """
    groups: dict[tuple[str, str, str, str], list[Hit]] = {}
    for hit in hits:
        key = (
            hit.watch_name,
            hit.store_host,
            hit.product_url.split("?")[0],
            "" if hit.price is None else str(hit.price),
        )
        groups.setdefault(key, []).append(hit)
    return [sorted(group, key=lambda h: h.variant_label) for group in groups.values()]


def batch_groups(groups: Sequence[Sequence[Hit]], max_hits_per_message: int) -> list[list[Hit]]:
    """Split/merge groups so no message carries more than ``max_hits_per_message``."""
    batches: list[list[Hit]] = []
    for group in groups:
        for start in range(0, len(group), max(1, max_hits_per_message)):
            batches.append(list(group[start : start + max_hits_per_message]))
    return batches


def cheapest_price(hits: Sequence[Hit]) -> Decimal | None:
    prices = [h.price for h in hits if h.price is not None]
    return min(prices) if prices else None


def summarize(hits: Sequence[Hit]) -> dict[str, str]:
    """Render the named template parameters for a batch of hits.

    Batches come from :func:`group_hits`, which keys on price, so every hit
    here shares one price and the rendered figure is the price of the sizes
    listed — never a "from $X" that the user cannot actually pay.
    """
    first = hits[0]
    variants = ", ".join(dict.fromkeys(h.variant_label for h in hits))
    price = cheapest_price(hits)
    price_text = f"${price:,.2f} {first.currency}" if price is not None else "precio no listado"
    return {
        "product": first.product_title,
        "variant": variants,
        "price": price_text,
        "store": first.store_name,
        "url": first.product_url,
    }


def render_text(hits: Sequence[Hit]) -> str:
    """Plain-text rendering used by the console notifier and session messages."""
    params = summarize(hits)
    flag = "" if all(h.color_matched for h in hits) else "  (color fuera de preferencia)"
    return (
        f"🔔 {params['product']} disponible en talla {params['variant']} "
        f"por {params['price']} en {params['store']}{flag}\n{params['url']}"
    )


__all__ = [
    "Alert",
    "Notifier",
    "NotifierError",
    "available_notifiers",
    "batch_groups",
    "build_notifier",
    "cheapest_price",
    "group_hits",
    "register_notifier",
    "render_text",
    "summarize",
]
