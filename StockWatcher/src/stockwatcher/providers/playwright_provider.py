"""Headless-browser provider for storefronts that refuse plain HTTP.

A handful of large retailers (nike.com, hibbett.com, jdsports.com,
finishline.com, snipesusa.com, dickssportinggoods.com, scheels.com) answer
``403`` to any non-browser client and render their size grid client side, so
there is no JSON payload to read.  This provider drives headless chromium
instead.

It is **config driven**: everything site-specific lives in a
:class:`BrowserProfile` (a set of CSS selectors), either one of the built-in
profiles below or an inline ``options`` block on the store.  Adding a new
JS-gated retailer should mean adding selectors to YAML, not writing code.

Why the size grid and not the embedded JSON
-------------------------------------------
Nike's PDP *does* embed a ``skus`` array with ``{label, localizedLabel,
status}`` and a per-colorway ``statusModifier`` of ``BUYABLE_BUY`` /
``OUT_OF_STOCK``.  Tempting, but ``status: ACTIVE`` on a SKU only means *that
SKU exists in the catalogue* - not that it is purchasable.  The only honest
signal is the rendered size button's disabled state, which is what we read.
(``api.nike.com`` is a dead end too: every endpoint returns 400/401/404
without a session token.)

The browser is expensive to start, so a single chromium instance is shared by
every store using this provider and reference-counted: it shuts down when the
last provider closes.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from ..models import Product, ProductRef, Store, Variant
from ..sizes import infer_gender
from .base import Provider, ProviderError, register_provider

log = logging.getLogger(__name__)

Selector = str | list[str]

_PRICE_RE = re.compile(r"(\d[\d,]*\.\d{2}|\d[\d,]*)")


@dataclass(frozen=True)
class BrowserProfile:
    """CSS selectors describing one JS-gated storefront."""

    #: Search URL with a ``{query}`` placeholder (already URL-encoded).
    search_url: str
    #: Anchors on the results page pointing at product detail pages.
    product_link: Selector
    #: Elements on the PDP, one per variant (size buttons / radios).
    variant: Selector
    title: Selector = "h1"
    #: Optional selector *relative to* a variant element holding its label.
    variant_label: str | None = None
    colorway: Selector | None = None
    price: Selector | None = None
    #: Waited for before scraping; falls back to ``variant``.
    wait_for: Selector | None = None
    #: Substrings that mark a variant element as unbuyable when they appear in
    #: its (or its container's) class list or aria attributes.
    unavailable_markers: tuple[str, ...] = (
        "disabled",
        "sold-out",
        "soldout",
        "out-of-stock",
        "oos",
        "unavailable",
    )
    #: Product URLs must contain this to be treated as a PDP.
    product_url_marker: str = ""
    max_results: int = 8
    #: Extra settle time after networkidle, for lazily hydrated grids.
    settle_ms: int = 600


PROFILES: dict[str, BrowserProfile] = {
    "nike": BrowserProfile(
        search_url="https://www.nike.com/w?q={query}&vst={query}",
        product_link=[
            "a.product-card__link-overlay",
            "[data-testid='product-card__link-overlay']",
            "a[data-testid='product-card-link']",
        ],
        variant=[
            "[data-testid='pdp-grid-selector-input']",
            "#skuAndSize input[type='radio']",
            "fieldset input[type='radio'][id^='size-']",
        ],
        title=["h1#pdp_product_title", "[data-testid='product_title']", "h1"],
        colorway=["[data-testid='product_subtitle']", "#pdp_product_subtitle"],
        price=["[data-testid='currentPrice-container']", "#price-container"],
        product_url_marker="/t/",
    ),
    "hibbett": BrowserProfile(
        search_url="https://www.hibbett.com/search?q={query}",
        product_link=["a.product-tile__link", "a[href*='.html']"],
        variant=["button.size-swatch", "[data-attr='size'] button"],
        colorway=[".product-color", "[data-attr='color'] .selected-value"],
        price=[".price .sales .value", ".price"],
        product_url_marker=".html",
    ),
    "jdsports": BrowserProfile(
        search_url="https://www.jdsports.com/search/{query}/",
        product_link=["a.product_name_link", "a[href*='/product/']"],
        variant=["ul.sizes li button", "[data-e2e='pdp-sizeSelector'] button"],
        price=[".pri", "[data-e2e='pdp-productPrice']"],
        product_url_marker="/product/",
    ),
    "finishline": BrowserProfile(
        search_url="https://www.finishline.com/store/catalog/search.jsp?query={query}",
        product_link=["a.product-card-link", "a[href*='/store/product/']"],
        variant=["ul.size-container li button", ".size-select button"],
        price=[".product-price", "[data-testid='product-price']"],
        product_url_marker="/product/",
    ),
    "snipes": BrowserProfile(
        search_url="https://www.snipesusa.com/search?q={query}",
        product_link=["a.product-tile-image-link", "a[href*='.html']"],
        variant=[".size-attribute button", "button.size-value"],
        price=[".sales .value", ".price"],
        product_url_marker=".html",
    ),
    "dicks": BrowserProfile(
        search_url="https://www.dickssportinggoods.com/search?searchTerm={query}",
        product_link=["a.dsg-react-product-card-link", "a[href*='/p/']"],
        variant=["[data-testid='size-selection'] button", ".size-selection button"],
        price=["[data-testid='product-price']", ".product-price"],
        product_url_marker="/p/",
    ),
    "scheels": BrowserProfile(
        search_url="https://www.scheels.com/search?q={query}",
        product_link=["a.product-tile__link", "a[href*='/p/']"],
        variant=[".size-selector button", "button[data-size]"],
        price=[".product-price", ".price"],
        product_url_marker="/p/",
    ),
}


# --------------------------------------------------------------------------
# Shared browser
# --------------------------------------------------------------------------


class _SharedBrowser:
    """One chromium instance shared by every Playwright-backed store.

    Launching a browser costs ~1s and ~200MB; doing it per store would dwarf
    the actual scraping.  Reference-counted so the run tears it down as soon
    as the last store is done with it.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._refs = 0
        self._playwright: Any = None
        self._browser: Any = None

    async def acquire(self, user_agent: str) -> Any:
        async with self._lock:
            self._refs += 1
            if self._browser is None:
                try:
                    from playwright.async_api import async_playwright
                except ImportError as exc:  # pragma: no cover - optional extra
                    self._refs -= 1
                    raise ProviderError(
                        "playwright is not installed; run "
                        "`pip install 'stockwatcher[browser]' && playwright install chromium`"
                    ) from exc
                self._playwright = await async_playwright().start()
                self._browser = await self._playwright.chromium.launch(
                    headless=True,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--disable-dev-shm-usage",
                        "--no-sandbox",
                    ],
                )
                log.debug("launched shared chromium (ua=%s)", user_agent)
            return self._browser

    async def release(self) -> None:
        async with self._lock:
            self._refs = max(0, self._refs - 1)
            if self._refs or self._browser is None:
                return
            try:
                await self._browser.close()
                await self._playwright.stop()
            except Exception as exc:  # pragma: no cover - best effort teardown
                log.debug("browser teardown: %s", exc)
            finally:
                self._browser = None
                self._playwright = None


_SHARED = _SharedBrowser()


# --------------------------------------------------------------------------
# Page-side extraction
# --------------------------------------------------------------------------

#: Runs inside the page.  Returns ``[{label, available}]`` for the first
#: selector that matches anything.  Kept in one evaluate() call because a
#: round trip per size button is painfully slow over CDP.
_VARIANT_JS = """
([selectors, labelSel, markers]) => {
  let nodes = [];
  for (const sel of selectors) {
    nodes = Array.from(document.querySelectorAll(sel));
    if (nodes.length) break;
  }
  const classOf = (el) => {
    if (!el) return '';
    const c = el.className;
    if (typeof c === 'string') return c;
    if (c && typeof c.baseVal === 'string') return c.baseVal;
    return '';
  };
  return nodes.map((node) => {
    let label = '';
    if (labelSel) {
      const inner = node.querySelector(labelSel);
      if (inner) label = inner.textContent || '';
    }
    if (!label && node.id) {
      const tied = document.querySelector('label[for="' + CSS.escape(node.id) + '"]');
      if (tied) label = tied.textContent || '';
    }
    if (!label) {
      label = node.getAttribute('aria-label') || node.getAttribute('data-size')
        || node.getAttribute('title') || node.value || node.textContent || '';
    }
    const container = node.closest('label, li, button, div') || node;
    let disabled = node.disabled === true
      || node.hasAttribute('disabled')
      || (node.getAttribute('aria-disabled') || '').toLowerCase() === 'true'
      || (container.getAttribute('aria-disabled') || '').toLowerCase() === 'true';
    if (!disabled) {
      const blob = (classOf(node) + ' ' + classOf(container)).toLowerCase();
      disabled = markers.some((m) => blob.includes(m));
    }
    return { label: String(label).trim(), available: !disabled };
  });
}
"""


def _as_list(selector: Selector | None) -> list[str]:
    if selector is None:
        return []
    if isinstance(selector, str):
        return [selector]
    return list(selector)


def parse_price(text: str | None) -> Decimal | None:
    """Pull a decimal out of rendered price text like ``"$145.00"``."""
    if not text:
        return None
    match = _PRICE_RE.search(text.replace("\xa0", " "))
    if not match:
        return None
    try:
        return Decimal(match.group(1).replace(",", ""))
    except Exception:
        return None


def build_variants(rows: list[dict], title: str) -> list[Variant]:
    """Normalize scraped ``{label, available}`` rows into variants.

    Pure, so the messy label handling is unit-testable without a browser.
    """
    gender = infer_gender(title)
    variants: list[Variant] = []
    seen: set[str] = set()
    for row in rows:
        label = str(row.get("label") or "").strip()
        if not label:
            continue
        # Rendered buttons often carry the stock message in their text, e.g.
        # "10\nSold Out"; keep the first line as the label.
        label = label.splitlines()[0].strip()
        if not label or label.lower() in seen:
            continue
        seen.add(label.lower())
        variants.append(Variant.create(label, bool(row.get("available")), gender=gender))
    return variants


# --------------------------------------------------------------------------
# Provider
# --------------------------------------------------------------------------


@dataclass
class _PageResult:
    title: str
    colorway: str | None
    price: Decimal | None
    rows: list[dict] = field(default_factory=list)


class PlaywrightProvider(Provider):
    """Generic headless-chromium provider driven by :class:`BrowserProfile`."""

    name = "playwright"
    default_delay = 1.5

    def __init__(self, store: Store, http) -> None:
        super().__init__(store, http)
        self.profile = self._resolve_profile(store)
        self._browser: Any = None
        self._context: Any = None

    @staticmethod
    def _resolve_profile(store: Store) -> BrowserProfile:
        options = dict(store.options or {})
        name = options.pop("profile", None)
        base = PROFILES.get(str(name).lower()) if name else None
        if base is None and not options:
            raise ProviderError(
                f"{store.host}: playwright store needs options.profile "
                f"(one of {', '.join(sorted(PROFILES))}) or inline selectors"
            )
        fields = {f: getattr(base, f) for f in BrowserProfile.__dataclass_fields__} if base else {}
        for key, value in options.items():
            if key in BrowserProfile.__dataclass_fields__:
                fields[key] = tuple(value) if key == "unavailable_markers" else value
        if "search_url" not in fields or "product_link" not in fields or "variant" not in fields:
            raise ProviderError(f"{store.host}: playwright profile is missing required selectors")
        return BrowserProfile(**fields)

    # ------------------------------------------------------------ lifecycle

    async def _page(self) -> Any:
        if self._context is None:
            self._browser = await _SHARED.acquire(self.http.user_agent)
            self._context = await self._browser.new_context(
                user_agent=self.http.user_agent,
                locale="en-US",
                viewport={"width": 1440, "height": 900},
                extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
            )
        return await self._context.new_page()

    async def aclose(self) -> None:
        if self._context is not None:
            try:
                await self._context.close()
            except Exception as exc:  # pragma: no cover - best effort
                log.debug("context close: %s", exc)
            self._context = None
            self._browser = None
            await _SHARED.release()

    # --------------------------------------------------------------- search

    async def search(self, query: str) -> list[ProductRef]:
        from urllib.parse import quote_plus

        url = self.profile.search_url.format(query=quote_plus(query))
        page = await self._page()
        try:
            await self._goto(page, url)
            hrefs = await self._collect_links(page)
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(f"{self.store.host}: search failed: {exc}") from exc
        finally:
            await page.close()

        refs: list[ProductRef] = []
        seen: set[str] = set()
        for href, text in hrefs:
            absolute = self._absolute(href)
            if not absolute or absolute in seen:
                continue
            if self.profile.product_url_marker and self.profile.product_url_marker not in absolute:
                continue
            seen.add(absolute)
            refs.append(
                ProductRef(
                    store_host=self.store.host,
                    provider=self.name,
                    url=absolute,
                    title=text or absolute.rsplit("/", 1)[-1].replace("-", " "),
                )
            )
            if len(refs) >= self.profile.max_results:
                break
        return refs

    async def _collect_links(self, page: Any) -> list[tuple[str, str]]:
        for selector in _as_list(self.profile.product_link):
            rows = await page.evaluate(
                """(sel) => Array.from(document.querySelectorAll(sel))
                    .map((a) => [a.getAttribute('href') || '',
                                 (a.getAttribute('aria-label') || a.textContent || '').trim()])""",
                selector,
            )
            if rows:
                return [(str(h), str(t)) for h, t in rows if h]
        return []

    # ---------------------------------------------------------------- fetch

    async def fetch(self, ref: ProductRef) -> Product | None:
        page = await self._page()
        try:
            await self._goto(page, ref.url)
            result = await self._scrape(page)
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(f"{self.store.host}: fetch {ref.url} failed: {exc}") from exc
        finally:
            await page.close()

        title = result.title or ref.title
        variants = build_variants(result.rows, title)
        if not variants:
            log.debug("%s: no variants scraped from %s", self.store.host, ref.url)
            return None
        return Product(
            ref=ref,
            title=title,
            url=ref.url,
            variants=variants,
            price=result.price,
            currency="USD",
            colorway=result.colorway,
            gender=infer_gender(f"{title} {result.colorway or ''}"),
            store_host=self.store.host,
            provider=self.name,
        )

    async def _scrape(self, page: Any) -> _PageResult:
        variant_selectors = _as_list(self.profile.variant)
        for selector in _as_list(self.profile.wait_for) or variant_selectors:
            try:
                await page.wait_for_selector(selector, timeout=8000, state="attached")
                break
            except Exception:
                continue
        if self.profile.settle_ms:
            await page.wait_for_timeout(self.profile.settle_ms)

        rows = await page.evaluate(
            _VARIANT_JS,
            [
                variant_selectors,
                self.profile.variant_label,
                list(self.profile.unavailable_markers),
            ],
        )
        return _PageResult(
            title=await self._text(page, self.profile.title) or "",
            colorway=await self._text(page, self.profile.colorway),
            price=parse_price(await self._text(page, self.profile.price)),
            rows=list(rows or []),
        )

    # --------------------------------------------------------------- helpers

    async def _goto(self, page: Any, url: str) -> None:
        response = await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        if response is not None and response.status >= 400:
            raise ProviderError(f"{self.store.host}: HTTP {response.status} for {url}")

    @staticmethod
    async def _text(page: Any, selector: Selector | None) -> str | None:
        for candidate in _as_list(selector):
            try:
                node = await page.query_selector(candidate)
            except Exception:
                continue
            if node is None:
                continue
            text = (await node.inner_text()).strip()
            if text:
                return text
        return None

    def _absolute(self, href: str) -> str | None:
        href = href.strip()
        if href.startswith("http"):
            return href.split("?")[0]
        if href.startswith("//"):
            return f"https:{href}".split("?")[0]
        if href.startswith("/"):
            return f"{self.store.base_url}{href}".split("?")[0]
        return None


register_provider("playwright", PlaywrightProvider)
