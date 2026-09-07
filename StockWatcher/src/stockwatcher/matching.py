"""Pure matching logic: does this product/variant satisfy this watch?

Kept free of I/O so it is trivially unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .config import Watch
from .models import Hit, Product, Store, Variant
from .sizes import Gender, genders_compatible, normalize_text, variants_match


@dataclass(frozen=True)
class VariantMatch:
    variant: Variant
    price: Decimal | None
    color_matched: bool


def store_allowed(watch: Watch, store: Store) -> bool:
    """Country filter plus an optional per-watch store allow-list."""
    if watch.countries and store.country.upper() not in watch.countries:
        return False
    return not (watch.stores and store.host.lower() not in watch.stores)


def text_matches(watch: Watch, text: str) -> bool:
    """True when any ``match`` group has all of its tokens present in *text*."""
    haystack = normalize_text(text)
    if not haystack:
        return False
    groups = watch.match_groups
    if not groups:
        return False
    return any(all(token in haystack for token in group) for group in groups)


def text_excluded(watch: Watch, text: str) -> bool:
    haystack = normalize_text(text)
    return any(term and term in haystack for term in watch.exclude)


def color_matched(watch: Watch, text: str) -> bool:
    """Colour is a *soft* preference: we still alert, but flag the mismatch."""
    if not watch.colors:
        return True
    haystack = normalize_text(text)
    return any(color and color in haystack for color in watch.colors)


def price_ok(watch: Watch, price: Decimal | None) -> bool:
    """Unknown prices pass: better a noisy alert than a missed restock."""
    if watch.max_price is None or price is None:
        return True
    return price <= watch.max_price


def product_matches(watch: Watch, product: Product) -> bool:
    text = product.searchable_text
    if not text_matches(watch, text):
        return False
    if text_excluded(watch, text):
        return False
    return genders_compatible(watch.gender, product.gender)


def variant_matches(watch: Watch, product: Product, variant: Variant) -> bool:
    """Does this variant sit on the axis value the user asked for?"""
    if not watch.variants:
        return True
    variant_gender = variant.size.gender if variant.size else product.gender
    return any(
        variants_match(
            variant.label,
            requested,
            store_gender=variant_gender,
            requested_gender=watch.gender,
        )
        for requested in watch.variants
    )


def effective_price(product: Product, variant: Variant) -> Decimal | None:
    """The price the user would actually pay for *this* variant.

    Never falls back to the product-level price when the variant carries one.
    On consignment stores (Stadium Goods is the clearest case) every size is
    priced separately and the product-level ``price`` is the *minimum* across
    variants — frequently the price of a size that is sold out.  Using it would
    fire ``max_price`` alerts for prices that are not purchasable, which is the
    worst failure mode this system has.
    """
    if variant.price is not None:
        return variant.price
    return product.price


def match_product(
    watch: Watch, product: Product, store: Store, *, include_unavailable: bool = False
) -> list[VariantMatch]:
    """Return every variant of ``product`` that satisfies ``watch``.

    By default only in-stock variants are returned.  The runner passes
    ``include_unavailable=True`` so the state store also learns about variants
    that are currently sold out — that is what makes the
    ``unavailable -> available`` transition detectable on a later run.
    """
    if not store_allowed(watch, store):
        return []
    if not product_matches(watch, product):
        return []

    matches: list[VariantMatch] = []
    for variant in product.variants:
        if not variant.available and not include_unavailable:
            continue
        if not variant_matches(watch, product, variant):
            continue
        price = effective_price(product, variant)
        if not price_ok(watch, price):
            continue
        matches.append(
            VariantMatch(
                variant=variant,
                price=price,
                color_matched=color_matched(watch, product.searchable_text),
            )
        )
    return matches


def _to_hit(watch: Watch, product: Product, store: Store, match: VariantMatch) -> Hit:
    return Hit(
        watch_name=watch.name,
        store_host=store.host,
        store_name=store.display_name,
        provider=product.provider or store.provider,
        product_title=product.title,
        product_url=product.url,
        variant_label=match.variant.label,
        price=match.price,
        currency=product.currency or watch.currency,
        colorway=product.colorway,
        color_matched=match.color_matched,
        country=store.country,
        image_url=product.image_url,
    )


def build_hits(watch: Watch, product: Product, store: Store) -> list[Hit]:
    """In-stock hits only."""
    return [_to_hit(watch, product, store, m) for m in match_product(watch, product, store)]


def build_observations(watch: Watch, product: Product, store: Store) -> list[tuple[Hit, bool]]:
    """``[(hit, is_available), ...]`` for every matching variant, stocked or not."""
    return [
        (_to_hit(watch, product, store, m), m.variant.available)
        for m in match_product(watch, product, store, include_unavailable=True)
    ]


def infer_watch_gender(watch: Watch) -> Gender:  # pragma: no cover - trivial
    return watch.gender
