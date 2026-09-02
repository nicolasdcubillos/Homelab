"""Foot Locker provider.

Foot Locker does *not* need a headless browser: plain HTTPS with a real Chrome
User-Agent plus ``Accept-Language: en-US,en;q=0.9`` returns fully populated
HTML with the product JSON embedded.  Two things matter:

* **SKU shape.**  Foot Locker's SKU is the Nike style code with the leading
  letter dropped and the dash removed (Nike ``HQ4307-200`` -> ``Q4307200``).
  The PDP lives at ``/product/~/{SKU}.html``.  If the response contains no
  ``styleDocumentId`` the SKU simply does not exist there.
* **Rate limiting.**  Faster than ~2.5s between requests and the site starts
  returning empty / "No Results" pages, so the provider declares a
  ``default_delay``.
"""

from __future__ import annotations

import logging
import re
from decimal import Decimal, InvalidOperation
from urllib.parse import quote_plus, urlsplit

from ..http import ACCEPT_LANGUAGE_EN_US
from ..models import Product, ProductRef, Store, Variant
from ..sizes import Gender, infer_gender
from .base import Provider, register_provider

log = logging.getLogger(__name__)

HOST = "www.footlocker.com"

_STYLE_DOC_RE = re.compile(r'"styleDocumentId"\s*:\s*"([A-Za-z0-9]+)_fl_enus"')
_SIZE_RE = re.compile(
    r'"active"\s*:\s*(true|false)\s*,\s*"productNumber"\s*:\s*"\d+"\s*,\s*"size"\s*:\s*"([0-9.]+)"'
)
_COLOR_RE = re.compile(r'"colorDescription"\s*:\s*"([^"]+)"')
_NAME_RE = re.compile(r'"name"\s*:\s*"([^"]{4,120})"')
_PRICE_RES = (
    re.compile(r'"originalPrice"\s*:\s*([0-9]+(?:\.[0-9]+)?)'),
    re.compile(r'"formattedOriginalPrice"\s*:\s*"\$?([0-9,]+(?:\.[0-9]+)?)"'),
    re.compile(r'"price"\s*:\s*([0-9]+(?:\.[0-9]+)?)'),
)
_PRODUCT_HREF_RE = re.compile(r'href="(/product/[^"?#]+\.html)"')
_STYLE_CODE_RE = re.compile(r"^[A-Za-z]{2}\d{4}[- ]?\d{3}$")


def nike_style_to_fl_sku(style_code: str) -> str:
    """``HQ4307-200`` -> ``Q4307200`` (drop the first letter, drop the dash)."""
    cleaned = re.sub(r"[^A-Za-z0-9]", "", style_code or "").upper()
    return cleaned[1:] if cleaned and cleaned[0].isalpha() else cleaned


def looks_like_style_code(query: str) -> bool:
    return bool(_STYLE_CODE_RE.match((query or "").strip()))


def _first_price(text: str) -> Decimal | None:
    for pattern in _PRICE_RES:
        match = pattern.search(text)
        if not match:
            continue
        try:
            return Decimal(match.group(1).replace(",", "")).quantize(Decimal("0.01"))
        except InvalidOperation:  # pragma: no cover - defensive
            continue
    return None


def parse_sizes(html: str, sku: str) -> list[tuple[str, bool]]:
    """Return ``[(size_label, in_stock), ...]`` for one style document.

    Sizes are zero padded on Foot Locker (``09.0``, ``10.0``); normalization
    happens later in :mod:`stockwatcher.sizes`.
    """
    target = sku.upper()
    windows: list[str] = []
    matches = list(_STYLE_DOC_RE.finditer(html))
    for index, match in enumerate(matches):
        if match.group(1).upper() != target:
            continue
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(html)
        windows.append(html[start : min(end, start + 20000)])

    seen: dict[str, bool] = {}
    for window in windows:
        for active, size in _SIZE_RE.findall(window):
            in_stock = active == "true"
            seen[size] = seen.get(size, False) or in_stock
    return sorted(seen.items(), key=lambda item: item[0])


class FootLockerProvider(Provider):
    """Search + PDP scraping for footlocker.com (and its sibling banners)."""

    name = "footlocker"
    default_delay = 2.5

    def __init__(self, store: Store, http) -> None:
        super().__init__(store, http)
        self.max_results = int(store.options.get("limit", 6))

    def product_url(self, sku: str) -> str:
        return f"{self.store.base_url}/product/~/{sku.upper()}.html"

    async def search(self, query: str) -> list[ProductRef]:
        refs: list[ProductRef] = []
        if looks_like_style_code(query):
            sku = nike_style_to_fl_sku(query)
            if sku:
                refs.append(
                    ProductRef(
                        store_host=self.store.host,
                        provider=self.name,
                        url=self.product_url(sku),
                        title=query,
                        handle=sku,
                    )
                )
                return refs

        url = f"{self.store.base_url}/search?query={quote_plus(query)}"
        response = await self.http.get(url, delay=self.delay, headers=ACCEPT_LANGUAGE_EN_US)
        if response.status_code != 200:
            return refs
        return self.parse_search(response.text)

    def parse_search(self, html: str) -> list[ProductRef]:
        refs: list[ProductRef] = []
        seen: set[str] = set()
        for href in _PRODUCT_HREF_RE.findall(html):
            path = urlsplit(href).path
            if path in seen:
                continue
            seen.add(path)
            handle = path.rstrip("/").split("/")[-1].removesuffix(".html")
            refs.append(
                ProductRef(
                    store_host=self.store.host,
                    provider=self.name,
                    url=self.store.base_url + path,
                    title=handle,
                    handle=handle,
                )
            )
            if len(refs) >= self.max_results:
                break
        if refs:
            return refs

        # Fall back to style documents referenced directly on the search page.
        for sku in dict.fromkeys(_STYLE_DOC_RE.findall(html)):
            refs.append(
                ProductRef(
                    store_host=self.store.host,
                    provider=self.name,
                    url=self.product_url(sku),
                    title=sku,
                    handle=sku,
                )
            )
            if len(refs) >= self.max_results:
                break
        return refs

    async def fetch(self, ref: ProductRef) -> Product | None:
        response = await self.http.get(ref.url, delay=self.delay, headers=ACCEPT_LANGUAGE_EN_US)
        if response.status_code != 200:
            return None
        return self.parse_product(ref, response.text)

    def parse_product(self, ref: ProductRef, html: str) -> Product | None:
        sku = (ref.handle or "").upper()
        if not sku:
            sku = urlsplit(ref.url).path.rstrip("/").split("/")[-1].removesuffix(".html").upper()
        style_ids = {s.upper() for s in _STYLE_DOC_RE.findall(html)}
        if not style_ids:
            log.debug("footlocker: no styleDocumentId on %s (sku missing)", ref.url)
            return None
        if sku not in style_ids:
            # Search results land on a canonical PDP whose SKU we only learn here.
            sku = next(iter(sorted(style_ids)))

        color_match = _COLOR_RE.search(html)
        colorway = color_match.group(1) if color_match else None
        name_match = _NAME_RE.search(html)
        title = (name_match.group(1) if name_match else ref.title) or sku
        gender = infer_gender(f"{title} {colorway or ''}")
        price = _first_price(html)

        variants = [
            Variant.create(
                label=size,
                available=in_stock,
                sku=f"{sku}-{size}",
                price=price,
                gender=gender if gender is not Gender.UNISEX else Gender.MENS,
            )
            for size, in_stock in parse_sizes(html, sku)
        ]

        return Product(
            ref=ref,
            title=title,
            url=ref.url,
            variants=variants,
            price=price,
            currency="USD",
            vendor=None,
            colorway=colorway,
            gender=gender,
            store_host=self.store.host,
            provider=self.name,
        )


register_provider("footlocker", FootLockerProvider)
