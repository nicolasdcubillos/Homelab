"""Nike.com provider.

Nike answers ``403`` to any non-browser client, so a headless browser is
required to load the page at all - it reuses the shared chromium instance from
:mod:`stockwatcher.providers.playwright_provider`.

Reading stock correctly took some finding, so the reasoning is recorded here:

* The rendered size grid (``#size-selector``) **never hydrates** under headless
  chromium - it stays an empty ``<div>``.  So scraping the buttons' disabled
  state, the obvious approach, yields nothing.
* ``__NEXT_DATA__`` *is* in the server-rendered HTML and carries every size as
  ``{label, localizedLabel, gtins, status}``.  But ``status: "ACTIVE"`` only
  means the SKU exists in the catalogue - a sold-out size is still ACTIVE.
  Using it as a stock signal would alert on everything, permanently.
* The PDP itself calls ``api.nike.com/deliver/available_gtins/v3`` with **no
  auth** and it returns 200: ``{objects: [{gtin, available, level}]}`` where
  ``level`` is ``OOS`` / ``IN_STOCK``.  Joining that onto the ``gtins`` of each
  size gives true per-size availability.

That join is what this provider implements.  The request is issued from inside
the page so it carries the same session and origin the browser already has.

One more trap: from a non-US IP Nike shows a country-switch interstitial and
prices in local currency.  The ``US`` market cookies below pin it to USD.
"""

from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Any

from ..models import Product, ProductRef, Variant
from ..sizes import Gender
from .base import ProviderError, register_provider
from .playwright_provider import PlaywrightProvider

log = logging.getLogger(__name__)

GTIN_ENDPOINT = (
    "https://api.nike.com/deliver/available_gtins/v3"
    "?filter=styleColor({style_color})&filter=merchGroup({market})"
)

#: Pins the storefront to the US market.  Without these, a Colombian IP gets a
#: country-switch modal and COP prices.
US_MARKET_COOKIES = [
    {"name": "NIKE_COMMERCE_COUNTRY", "value": "US", "domain": ".nike.com", "path": "/"},
    {"name": "NIKE_COMMERCE_LANG_LOCALE", "value": "en_US", "domain": ".nike.com", "path": "/"},
    {"name": "geoloc", "value": "cc=US,rc=OR,tp=vhigh,tz=PST", "domain": ".nike.com", "path": "/"},
]

_GENDER_MAP = {"MEN": Gender.MENS, "WOMEN": Gender.WOMENS}


# --------------------------------------------------------------------------
# Pure parsing helpers (unit-tested without a browser)
# --------------------------------------------------------------------------


def select_product(next_data: dict, style_color: str | None = None) -> dict | None:
    """Pull the requested colorway's product node out of ``__NEXT_DATA__``.

    A Nike PDP ships *every* colorway of the style; ``pageProps.styleColor``
    says which one the URL asked for.  Picking the wrong one would report
    another colour's stock.
    """
    props = next_data.get("props") if isinstance(next_data, dict) else None
    page_props = (props or {}).get("pageProps") if isinstance(props, dict) else None
    if not isinstance(page_props, dict):
        return None
    wanted = style_color or page_props.get("styleColor")
    for group in page_props.get("productGroups") or []:
        products = group.get("products") if isinstance(group, dict) else None
        if not isinstance(products, dict):
            continue
        if wanted and wanted in products:
            return products[wanted]
    selected = page_props.get("selectedProduct")
    return selected if isinstance(selected, dict) else None


def available_gtins(payload: Any) -> set[str]:
    """GTINs that are actually purchasable right now."""
    objects = payload.get("objects") if isinstance(payload, dict) else None
    if not isinstance(objects, list):
        return set()
    return {
        str(obj["gtin"])
        for obj in objects
        if isinstance(obj, dict) and obj.get("gtin") and obj.get("available") is True
    }


def product_gender(product: dict) -> Gender:
    genders = [str(g).upper() for g in (product.get("genders") or [])]
    if len(genders) == 1:
        return _GENDER_MAP.get(genders[0], Gender.UNISEX)
    return Gender.UNISEX


def build_nike_variants(product: dict, in_stock: set[str]) -> list[Variant]:
    """Join Nike's size list against the available-GTIN set.

    ``status`` is deliberately ignored: ACTIVE means "this SKU exists", not
    "you can buy it".
    """
    gender = product_gender(product)
    price = _current_price(product)
    variants: list[Variant] = []
    for size in product.get("sizes") or []:
        if not isinstance(size, dict):
            continue
        label = str(size.get("label") or "").strip()
        localized = str(size.get("localizedLabel") or "").strip()
        if not label and not localized:
            continue
        gtins = {
            str(g.get("gtin"))
            for g in size.get("gtins") or []
            if isinstance(g, dict) and g.get("gtin")
        }
        # A single-gender listing gives a clean numeric label; a dual-sized one
        # ("M 9 / W 10.5") carries the gender in the label itself.
        if gender is Gender.UNISEX and localized:
            label_for_size, gender_for_size = localized, Gender.UNISEX
        else:
            label_for_size, gender_for_size = (label or localized), gender
        variants.append(
            Variant.create(
                label_for_size,
                available=bool(gtins & in_stock),
                sku=next(iter(sorted(gtins)), None),
                price=price,
                gender=gender_for_size,
            )
        )
    return variants


def _current_price(product: dict) -> Decimal | None:
    prices = product.get("prices")
    if not isinstance(prices, dict):
        return None
    raw = prices.get("currentPrice")
    if raw is None:
        return None
    try:
        return Decimal(str(raw))
    except Exception:
        return None


def _currency(product: dict) -> str:
    prices = product.get("prices")
    if isinstance(prices, dict) and prices.get("currency"):
        return str(prices["currency"])
    return "USD"


def _title(product: dict, fallback: str) -> str:
    info = product.get("productInfo")
    if isinstance(info, dict):
        content = info.get("productContent")
        if isinstance(content, dict):
            for key in ("fullTitle", "title"):
                value = content.get(key)
                if value:
                    return str(value)
    for key in ("fullTitle", "title", "groupLabel"):
        value = product.get(key)
        if value:
            return str(value)
    return fallback


# --------------------------------------------------------------------------
# Provider
# --------------------------------------------------------------------------


class NikeProvider(PlaywrightProvider):
    """Browser-loaded PDP + unauthenticated GTIN availability lookup."""

    name = "nike"
    default_delay = 2.0

    def __init__(self, store, http) -> None:
        if not store.options:
            store = _with_profile(store)
        super().__init__(store, http)
        self.market = str((store.options or {}).get("market", "US"))

    async def _page(self) -> Any:
        first_time = self._context is None
        page = await super()._page()
        if first_time:
            await self._context.add_cookies(US_MARKET_COOKIES)
        return page

    async def fetch(self, ref: ProductRef) -> Product | None:
        page = await self._page()
        try:
            await self._goto(page, ref.url)
            raw = await page.evaluate(
                "() => { const el = document.getElementById('__NEXT_DATA__');"
                " return el ? el.textContent : null; }"
            )
            if not raw:
                raise ProviderError(f"{self.store.host}: no __NEXT_DATA__ on {ref.url}")
            next_data = json.loads(raw)
            product = select_product(next_data)
            if not product:
                raise ProviderError(f"{self.store.host}: no product node for {ref.url}")

            style_color = str(product.get("styleColor") or "")
            in_stock = await self._available_gtins(page, style_color)
            title = _title(product, ref.title)
            variants = build_nike_variants(product, in_stock)
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(f"{self.store.host}: fetch {ref.url} failed: {exc}") from exc
        finally:
            await page.close()

        if not variants:
            return None
        return Product(
            ref=ref,
            title=title,
            url=ref.url,
            variants=variants,
            price=_current_price(product),
            currency=_currency(product),
            vendor="Nike",
            colorway=product.get("colorDescription"),
            gender=product_gender(product),
            store_host=self.store.host,
            provider=self.name,
        )

    async def _available_gtins(self, page: Any, style_color: str) -> set[str]:
        if not style_color:
            return set()
        url = GTIN_ENDPOINT.format(style_color=style_color, market=self.market)
        # Issued from inside the page so it inherits the browser's session and
        # origin; the same request from a bare HTTP client is refused.
        payload = await page.evaluate(
            """async (url) => {
                const res = await fetch(url, {headers: {'Accept': 'application/json'}});
                if (!res.ok) return null;
                return await res.json();
            }""",
            url,
        )
        if payload is None:
            log.warning("%s: availability lookup failed for %s", self.store.host, style_color)
            return set()
        return available_gtins(payload)


def _with_profile(store):
    from dataclasses import replace

    return replace(store, options={"profile": "nike"})


register_provider("nike", NikeProvider)
