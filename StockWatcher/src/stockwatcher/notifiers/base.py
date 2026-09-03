"""Notifier plug-in system."""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Sequence
from decimal import Decimal

from ..models import Alert, Hit
from ..sizes import parse_size


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

#: Channel -> the environment variable that carries its destination.
_DESTINATION_ENV: dict[str, str] = {}


def register_notifier(
    name: str,
    factory: NotifierFactory,
    *,
    destination_env: str | None = None,
) -> None:
    """Register a channel, optionally naming the env var that addresses it.

    ``destination_env`` is what makes :func:`resolve_destinations` able to
    apply one precedence rule to every channel instead of hard-coding
    ``WHATSAPP_TO`` / ``EMAIL_TO`` at the call site.
    """
    key = name.lower()
    _REGISTRY[key] = factory
    if destination_env:
        _DESTINATION_ENV[key] = destination_env


def available_notifiers() -> list[str]:
    return sorted(_REGISTRY)


def destination_env(channel: str) -> str | None:
    """Name of the env var holding ``channel``'s destination, if it has one."""
    return _DESTINATION_ENV.get(channel.lower())


def env_list(name: str) -> list[str]:
    """Read a comma/semicolon separated env var into a list."""
    raw = os.getenv(name, "")
    return [part.strip() for part in raw.replace(";", ",").split(",") if part.strip()]


def resolve_destinations(
    channel: str,
    *,
    override: Sequence[str] | None = None,
    configured: Sequence[str] | None = None,
) -> list[str]:
    """Decide where ``channel`` delivers, highest precedence first:

    1. ``override`` — the ``--notify-to`` flag, supplied per invocation.
    2. the process environment (``WHATSAPP_TO`` / ``EMAIL_TO``).
    3. ``configured`` — the YAML destination (``watches[].notify`` entry, or
       ``notify_options.to``).

    **This order is a security contract, not a preference.**  StockWatcher is
    invoked once per user by an external scheduler, and every user shares one
    checkout — so one ``.env``.  Layer 2 only keeps users apart because
    ``dotenv.load_dotenv`` defaults to ``override=False``: a destination
    already present in the process environment beats the shared file.  Calling
    ``load_dotenv(override=True)`` anywhere (see :func:`stockwatcher.cli.main`)
    would silently redirect *every* user's alerts to whatever address the
    shared ``.env`` happens to carry.  Layer 1 exists so a caller never has to
    rely on that subtlety at all: an explicit flag beats both.
    """
    if override:
        return list(override)
    var = _DESTINATION_ENV.get(channel.lower())
    from_env = env_list(var) if var else []
    if from_env:
        return from_env
    return list(configured or [])


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
    return [sorted(group, key=_variant_sort_key) for group in groups.values()]


def _variant_sort_key(hit: Hit) -> tuple[int, float, str]:
    """Order sizes numerically, so a message reads "9.5, 10" not "10, 9.5".

    Sorting the raw labels as strings puts "10" before "9.5".  Non-numeric
    variants (colours, capacities) fall back to alphabetical, after the
    numeric ones.
    """
    size = parse_size(hit.variant_label)
    if size is not None:
        return (0, size.value, hit.variant_label)
    return (1, 0.0, hit.variant_label.lower())


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
    "destination_env",
    "env_list",
    "group_hits",
    "register_notifier",
    "render_text",
    "resolve_destinations",
    "summarize",
]
