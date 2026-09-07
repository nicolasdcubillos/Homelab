"""Generic Shopify provider.

Two unauthenticated endpoints do all the work on any Shopify storefront:

``/search/suggest.json``
    ``?q=<query>&resources[type]=product&resources[limit]=15`` ->
    ``json["resources"]["results"]["products"]`` with ``{title, price, url}``.
    The ``url`` carries a tracking querystring that must be stripped.

``<product_url>.js``
    ``{title, price (CENTS), vendor, variants: [{title, available, sku, price}]}``
    where ``available`` is the real-time per-variant stock boolean.

This is the backbone of the watcher: a large share of US sneaker/apparel
retailers run Shopify, and these endpoints give exact per-size stock.

Two hard-won details are encoded here:

**Prices are per variant, never product level.**  The top-level ``price`` is
the *minimum* across variants.  On consignment stores every size is priced
separately, so the headline price is frequently the price of a size that is
sold out — using it would fire ``max_price`` alerts for prices the user cannot
actually pay.  See ``tests/test_matching.py`` for the Stadium Goods regression.

**Never send ``Accept-Language: en-US``.**  It switches Shopify Markets into
geo-localized pricing: from a Colombian IP, kith.com then returns COP
(``48200000``) instead of USD (``14500``).  We pin ``country=US`` instead.
"""

from __future__ import annotations

import logging
import re
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlsplit

from ..models import Product, ProductRef, Store, Variant
from ..sizes import Gender, infer_gender
from .base import Provider, register_provider

log = logging.getLogger(__name__)

SUGGEST_PATH = "/search/suggest.json"
#: Forces Shopify Markets to quote the US storefront price.
MARKET_PARAMS = {"country": "US"}
JSON_HEADERS = {"Accept": "application/json,text/javascript,*/*;q=0.8"}

_SIZE_OPTION_NAMES = ("size", "talla", "shoe size", "us size", "sizes", "us")
_COLOR_OPTION_NAMES = ("color", "colour", "colorway", "col")
_MONEY_RE = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?")


def clean_url(url: str) -> str:
    """Strip Shopify's ``?pr_prod_strat=...`` tracking querystring."""
    return url.split("?")[0] if url else url


def money_from_cents(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return (Decimal(str(value)) / Decimal(100)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError):
        return None


def money_from_text(value: Any) -> Decimal | None:
    """suggest.json prices arrive as ``"$160.00"`` / ``"160.00"`` / cents ints."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return Decimal(str(value)).quantize(Decimal("0.01"))
    match = _MONEY_RE.search(str(value))
    if not match:
        return None
    try:
        return Decimal(match.group(0).replace(",", "")).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def _option_names(payload: dict) -> list[str]:
    options = payload.get("options") or []
    names: list[str] = []
    for option in options:
        if isinstance(option, str):
            names.append(option)
        elif isinstance(option, dict):
            names.append(str(option.get("name") or ""))
    return names


def _option_index(names: list[str], candidates: tuple[str, ...]) -> int | None:
    for index, name in enumerate(names):
        if name.strip().lower() in candidates:
            return index
    for index, name in enumerate(names):
        lowered = name.strip().lower()
        if any(candidate in lowered for candidate in candidates):
            return index
    return None


def _variant_option(variant: dict, index: int | None) -> str | None:
    if index is None:
        return None
    options = variant.get("options")
    if isinstance(options, list) and index < len(options):
        value = options[index]
        if value:
            return str(value)
    value = variant.get(f"option{index + 1}")
    return str(value) if value else None


def _colorway_from_title(title: str) -> str | None:
    """Kith-style titles put the colorway after a dash: ``"Nike Mind 002 - White / Grey"``."""
    if " - " not in title:
        return None
    return title.split(" - ", 1)[1].strip() or None


def absolute_image_url(value: Any) -> str | None:
    """Shopify serves CDN images protocol-relative (``//cdn.shopify.com/...``).

    Fine in a browser, but an email client resolves that against the message's
    own origin (i.e. nowhere), so the picture never loads.  Force ``https:``.
    """
    if not value:
        return None
    url = str(value).strip()
    if not url:
        return None
    if url.startswith("//"):
        return f"https:{url}"
    if url.startswith("http://") or url.startswith("https://"):
        return url
    return None


def _suggest_image(item: dict) -> str | None:
    return absolute_image_url(item.get("image") or item.get("featured_image"))


def _product_image(payload: dict) -> str | None:
    featured = payload.get("featured_image")
    if featured:
        return absolute_image_url(featured)
    images = payload.get("images") or []
    if isinstance(images, list) and images:
        return absolute_image_url(images[0])
    return None


class ShopifyProvider(Provider):
    """Works against any Shopify storefront without credentials."""

    name = "shopify"
    #: Shopify's suggest endpoint returns 429 when queries arrive back to back;
    #: a small spacing plus the per-host semaphore keeps every store answering.
    default_delay = 0.35

    def __init__(self, store: Store, http) -> None:
        super().__init__(store, http)
        self.limit = int(store.options.get("limit", 15))

    async def search(self, query: str) -> list[ProductRef]:
        payload = await self.http.get_json(
            self.store.base_url + SUGGEST_PATH,
            delay=self.delay,
            headers=JSON_HEADERS,
            params={
                "q": query,
                "resources[type]": "product",
                "resources[limit]": str(self.limit),
                **MARKET_PARAMS,
            },
        )
        return self.parse_search(payload)

    def parse_search(self, payload: Any) -> list[ProductRef]:
        products = extract_suggest_products(payload)
        refs: list[ProductRef] = []
        for item in products:
            raw_url = str(item.get("url") or "")
            if not raw_url:
                continue
            path = clean_url(raw_url)
            if path.startswith("http"):
                split = urlsplit(path)
                path = split.path
            if not path.startswith("/"):
                path = "/" + path
            refs.append(
                ProductRef(
                    store_host=self.store.host,
                    provider=self.name,
                    url=self.store.base_url + path,
                    title=str(item.get("title") or "").strip(),
                    price=money_from_text(item.get("price")),
                    handle=path.rstrip("/").split("/")[-1],
                    image_url=_suggest_image(item) if isinstance(item, dict) else None,
                    raw=item if isinstance(item, dict) else {},
                )
            )
        return refs

    async def fetch(self, ref: ProductRef) -> Product | None:
        url = clean_url(ref.url) + ".js"
        payload = await self.http.get_json(
            url, delay=self.delay, headers=JSON_HEADERS, params=MARKET_PARAMS
        )
        if not isinstance(payload, dict):
            return None
        return self.parse_product(ref, payload)

    def parse_product(self, ref: ProductRef, payload: dict) -> Product:
        names = _option_names(payload)
        size_index = _option_index(names, _SIZE_OPTION_NAMES)
        color_index = _option_index(names, _COLOR_OPTION_NAMES)

        title = str(payload.get("title") or ref.title).strip()
        vendor = payload.get("vendor")
        tags = payload.get("tags") or []
        tag_text = " ".join(str(t) for t in tags) if isinstance(tags, list) else str(tags)
        gender = infer_gender(f"{title} {tag_text} {payload.get('type') or ''}")

        colorway: str | None = None
        raw_variants = payload.get("variants") or []
        variants: list[Variant] = []
        for raw in raw_variants:
            if not isinstance(raw, dict):
                continue
            label = _variant_option(raw, size_index) or str(raw.get("title") or "").strip()
            if colorway is None:
                colorway = _variant_option(raw, color_index)
            variant_gender = gender
            if variant_gender is Gender.UNISEX:
                variant_gender = infer_gender(str(raw.get("title") or ""))
            variants.append(
                Variant.create(
                    label=label,
                    available=bool(raw.get("available")),
                    sku=str(raw["sku"]) if raw.get("sku") else None,
                    # Per-variant price ONLY.  The product-level price is the
                    # minimum across variants and is routinely the price of a
                    # sold-out size (see the module docstring).
                    price=money_from_cents(raw.get("price")),
                    gender=variant_gender,
                )
            )

        return Product(
            ref=ref,
            title=title,
            url=clean_url(ref.url),
            variants=variants,
            # Kept for display only; matching always uses the variant price.
            price=money_from_cents(payload.get("price")) or ref.price,
            currency=str(payload.get("currency") or "USD").upper(),
            vendor=str(vendor) if vendor else None,
            colorway=colorway or _colorway_from_title(title),
            gender=gender,
            store_host=self.store.host,
            provider=self.name,
            image_url=_product_image(payload) or ref.image_url,
        )


def extract_suggest_products(payload: Any) -> list[dict]:
    """Pull the product list out of a ``suggest.json`` body, tolerating shapes."""
    if not isinstance(payload, dict):
        return []
    results = (payload.get("resources") or {}).get("results")
    if not isinstance(results, dict):
        return []
    products = results.get("products")
    if not isinstance(products, list):
        return []
    return [p for p in products if isinstance(p, dict)]


def looks_like_shopify(payload: Any) -> bool:
    """Cheap validity probe used by store discovery."""
    if not isinstance(payload, dict):
        return False
    resources = payload.get("resources")
    if not isinstance(resources, dict):
        return False
    results = resources.get("results")
    return isinstance(results, dict) and "products" in results


register_provider("shopify", ShopifyProvider)
