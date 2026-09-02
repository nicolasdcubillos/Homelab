"""Shared fixtures.

Nothing in the suite touches the network: providers are exercised through
their pure parse functions, or through ``respx``-mocked transports.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from stockwatcher.config import Watch
from stockwatcher.models import Product, ProductRef, Store, Variant
from stockwatcher.sizes import Gender


@pytest.fixture
def store() -> Store:
    return Store(host="example.com", provider="shopify", name="Example", country="US")


@pytest.fixture
def mind_watch() -> Watch:
    return Watch(
        name="Nike Mind 002",
        match=["mind 002"],
        exclude=["wmns", "women"],
        variants=["9.5", "10"],
        gender=Gender.MENS,
        colors=["white", "summit", "platinum", "sail"],
        max_price=Decimal("160"),
    )


def make_product(
    *,
    title: str = "Nike Mind 002",
    variants: list[Variant] | None = None,
    price: Decimal | None = None,
    colorway: str | None = None,
    gender: Gender = Gender.MENS,
    host: str = "example.com",
) -> Product:
    ref = ProductRef(store_host=host, provider="shopify", url=f"https://{host}/p", title=title)
    return Product(
        ref=ref,
        title=title,
        url=ref.url,
        variants=variants or [],
        price=price,
        currency="USD",
        colorway=colorway,
        gender=gender,
        store_host=host,
        provider="shopify",
    )
