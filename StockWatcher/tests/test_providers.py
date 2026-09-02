"""Provider parsing.

Every provider exposes its payload handling as a pure function so the messy
per-retailer details can be tested without touching the network.  The one
network-shaped test uses ``respx`` to mock the transport.
"""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
import respx

from stockwatcher.http import HttpClient
from stockwatcher.models import ProductRef, Store
from stockwatcher.providers.footlocker import (
    FootLockerProvider,
    looks_like_style_code,
    nike_style_to_fl_sku,
    parse_sizes,
)
from stockwatcher.providers.shopify import ShopifyProvider, clean_url, looks_like_shopify
from stockwatcher.sizes import Gender

# --------------------------------------------------------------------------
# Shopify
# --------------------------------------------------------------------------

KITH_SUGGEST = {
    "resources": {
        "results": {
            "products": [
                {
                    "title": "Nike Mind 002 Flyknit - White / Dark Grey / Pure Platinum",
                    "price": "145.00",
                    "url": "/products/nike-mind-002-flyknit?pr_prod_strat=e5&pr_seq=uniform",
                },
                {"title": "Kith Wool Knit", "price": "265.00", "url": "/products/kith-wool-knit"},
            ]
        }
    }
}

KITH_PRODUCT = {
    "title": "Nike Mind 002 Flyknit - White / Dark Grey / Pure Platinum",
    "price": 14500,
    "vendor": "Nike",
    "options": [{"name": "Size"}],
    "variants": [
        {"title": "9.5", "available": False, "price": 14500, "sku": "A-095"},
        {"title": "10", "available": True, "price": 14500, "sku": "A-100"},
    ],
}


@pytest.fixture
def shopify_provider():
    return ShopifyProvider(Store(host="kith.com", provider="shopify", name="Kith"), http=None)


class TestShopifySearchParsing:
    def test_extracts_every_product(self, shopify_provider):
        refs = shopify_provider.parse_search(KITH_SUGGEST)
        assert [r.title for r in refs] == [
            "Nike Mind 002 Flyknit - White / Dark Grey / Pure Platinum",
            "Kith Wool Knit",
        ]

    def test_strips_tracking_querystring(self, shopify_provider):
        """Leaving it on would make the state key change every run."""
        ref = shopify_provider.parse_search(KITH_SUGGEST)[0]
        assert ref.url == "https://kith.com/products/nike-mind-002-flyknit"

    def test_builds_absolute_urls(self, shopify_provider):
        assert all(
            r.url.startswith("https://kith.com/")
            for r in shopify_provider.parse_search(KITH_SUGGEST)
        )

    def test_search_price_is_a_decimal(self, shopify_provider):
        assert shopify_provider.parse_search(KITH_SUGGEST)[0].price == Decimal("145.00")

    @pytest.mark.parametrize("payload", [None, {}, {"resources": {}}, [], "nope"])
    def test_malformed_payloads_yield_nothing(self, shopify_provider, payload):
        """A broken store must degrade to "no results", never raise."""
        assert shopify_provider.parse_search(payload) == []


class TestShopifyProductParsing:
    @pytest.fixture
    def product(self, shopify_provider):
        ref = shopify_provider.parse_search(KITH_SUGGEST)[0]
        return shopify_provider.parse_product(ref, KITH_PRODUCT)

    def test_prices_are_cents(self, product):
        assert product.price == Decimal("145.00")
        assert {v.price for v in product.variants} == {Decimal("145.00")}

    def test_availability_is_per_variant(self, product):
        assert {v.label: v.available for v in product.variants} == {"9.5": False, "10": True}

    def test_colorway_from_dash_suffix(self, product):
        assert product.colorway == "White / Dark Grey / Pure Platinum"

    def test_vendor_is_kept(self, product):
        assert product.vendor == "Nike"

    def test_compound_variant_titles_parse_the_size(self, shopify_provider):
        payload = {
            "title": "Nike Dunk Low",
            "price": 11000,
            "options": [{"name": "Color"}, {"name": "Size"}],
            "variants": [
                {"title": "PINK SMOKE/METALLIC SILVER / 9.5", "available": True, "price": 11000},
                {"title": "Orange / 10", "available": True, "price": 11000},
            ],
        }
        ref = ProductRef(
            store_host="kith.com", provider="shopify", url="https://kith.com/p", title="x"
        )
        product = shopify_provider.parse_product(ref, payload)
        assert [v.size.value for v in product.variants] == [9.5, 10.0]


class TestShopifyHelpers:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("/products/x?a=1&b=2", "/products/x"),
            ("/products/x", "/products/x"),
            ("https://k.com/products/x?y=1", "https://k.com/products/x"),
        ],
    )
    def test_clean_url(self, raw, expected):
        assert clean_url(raw) == expected

    def test_looks_like_shopify_accepts_a_real_payload(self):
        assert looks_like_shopify(KITH_SUGGEST)

    @pytest.mark.parametrize(
        "payload",
        [None, {}, {"resources": {"results": {}}}, {"resources": "x"}, ["a"], "<html>"],
    )
    def test_looks_like_shopify_rejects_everything_else(self, payload):
        """Discovery probes arbitrary domains; a 200 HTML page must not pass."""
        assert not looks_like_shopify(payload)


class TestShopifyOverHttp:
    """One end-to-end pass through HttpClient, with the transport mocked."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_search_then_fetch(self):
        respx.get("https://kith.com/search/suggest.json").mock(
            return_value=httpx.Response(200, json=KITH_SUGGEST)
        )
        respx.get("https://kith.com/products/nike-mind-002-flyknit.js").mock(
            return_value=httpx.Response(200, json=KITH_PRODUCT)
        )
        http = HttpClient(rate=0, default_delay=0)
        try:
            provider = ShopifyProvider(Store(host="kith.com"), http)
            refs = await provider.search("mind 002")
            product = await provider.fetch(refs[0])
        finally:
            await http.aclose()

        assert product is not None
        assert [v.label for v in product.variants if v.available] == ["10"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_bot_challenge_is_reported_not_silently_empty(self):
        """A throttled store must fail loudly.

        Shopify serves an HTML "Verifying your connection" interstitial when it
        rate-limits.  Swallowing that would look identical to "nothing is in
        stock" and the user would never be told their scan is broken.
        """
        from stockwatcher.http import RateLimited

        respx.get("https://kith.com/search/suggest.json").mock(
            return_value=httpx.Response(
                200, html="<html><body>Verifying your connection...</body></html>"
            )
        )
        http = HttpClient(rate=0, default_delay=0, max_retries=0)
        try:
            provider = ShopifyProvider(Store(host="kith.com"), http)
            with pytest.raises(RateLimited):
                await provider.search("mind 002")
        finally:
            await http.aclose()


# --------------------------------------------------------------------------
# Foot Locker
# --------------------------------------------------------------------------


class TestFootLockerSku:
    def test_drops_the_leading_letter_and_dash(self):
        """Nike ``HQ4307-200`` is Foot Locker ``Q4307200``."""
        assert nike_style_to_fl_sku("HQ4307-200") == "Q4307200"

    def test_is_case_insensitive(self):
        assert nike_style_to_fl_sku("hq4308-003") == "Q4308003"

    @pytest.mark.parametrize("code", ["HQ4307-200", "hq4308 003", "IR2176-100"])
    def test_recognises_style_codes(self, code):
        assert looks_like_style_code(code)

    @pytest.mark.parametrize("query", ["mind 002", "nike mind", ""])
    def test_rejects_free_text(self, query):
        assert not looks_like_style_code(query)


FOOT_LOCKER_HTML = """
{"styleDocumentId":"Q4307200_fl_enus","colorDescription":"Hemp/Sanddrift/Pale Ivory",
"sizes":[{"active":true,"productNumber":"1234567","size":"09.5"},
{"active":false,"productNumber":"1234568","size":"10.0"},
{"active":true,"productNumber":"1234569","size":"11.0"}]}
"""


class TestFootLockerSizeParsing:
    def test_reads_active_flag_per_size(self):
        assert parse_sizes(FOOT_LOCKER_HTML, "Q4307200") == [
            ("09.5", True),
            ("10.0", False),
            ("11.0", True),
        ]

    def test_zero_padded_sizes_normalize(self):
        from stockwatcher.sizes import parse_size

        label = parse_sizes(FOOT_LOCKER_HTML, "Q4307200")[0][0]
        assert parse_size(label).value == 9.5

    def test_unknown_sku_yields_nothing(self):
        """No styleDocumentId for the SKU means the product is not sold there."""
        assert parse_sizes(FOOT_LOCKER_HTML, "Q9999999") == []

    def test_empty_page_yields_nothing(self):
        assert parse_sizes("No Results", "Q4307200") == []


class TestFootLockerProvider:
    def test_uses_a_polite_delay(self):
        """Foot Locker starts serving empty pages without ~2.5s spacing."""
        provider = FootLockerProvider(Store(host="www.footlocker.com", provider="footlocker"), None)
        assert provider.delay >= 2.0


# --------------------------------------------------------------------------
# Nike
# --------------------------------------------------------------------------

NIKE_NEXT_DATA = {
    "props": {
        "pageProps": {
            "styleColor": "HQ4308-100",
            "productGroups": [
                {
                    "products": {
                        "HQ4308-100": {
                            "styleColor": "HQ4308-100",
                            "colorDescription": "White/Vast Grey/Anthracite",
                            "genders": ["MEN"],
                            "prices": {"currentPrice": 145, "currency": "USD"},
                            "sizes": [
                                {
                                    "label": "9.5",
                                    "localizedLabel": "M 9.5 / W 11",
                                    "status": "ACTIVE",
                                    "gtins": [{"gtin": "111"}],
                                },
                                {
                                    "label": "10",
                                    "localizedLabel": "M 10 / W 11.5",
                                    "status": "ACTIVE",
                                    "gtins": [{"gtin": "222"}],
                                },
                            ],
                        },
                        "HQ4308-003": {
                            "styleColor": "HQ4308-003",
                            "colorDescription": "Light Smoke Grey",
                            "genders": ["MEN"],
                            "sizes": [{"label": "9.5", "gtins": [{"gtin": "999"}]}],
                        },
                    }
                }
            ],
        }
    }
}

NIKE_GTINS = {
    "objects": [
        {"gtin": "111", "level": "OOS", "available": False},
        {"gtin": "222", "level": "IN_STOCK", "available": True},
    ]
}


class TestNikeParsing:
    def test_selects_the_requested_colorway(self):
        """A Nike PDP ships every colorway; picking the wrong one reports
        another colour's stock."""
        from stockwatcher.providers.nike import select_product

        product = select_product(NIKE_NEXT_DATA)
        assert product["styleColor"] == "HQ4308-100"

    def test_available_gtins_keeps_only_purchasable(self):
        from stockwatcher.providers.nike import available_gtins

        assert available_gtins(NIKE_GTINS) == {"222"}

    def test_status_active_is_not_treated_as_in_stock(self):
        """Both sizes are ACTIVE; only the one with a live GTIN is in stock.

        Trusting ``status`` would alert on every size of every shoe forever.
        """
        from stockwatcher.providers.nike import (
            available_gtins,
            build_nike_variants,
            select_product,
        )

        product = select_product(NIKE_NEXT_DATA)
        variants = build_nike_variants(product, available_gtins(NIKE_GTINS))
        assert {v.label: v.available for v in variants} == {"9.5": False, "10": True}

    def test_gender_comes_from_the_listing(self):
        from stockwatcher.providers.nike import build_nike_variants, select_product

        variants = build_nike_variants(select_product(NIKE_NEXT_DATA), set())
        assert all(v.size.gender is Gender.MENS for v in variants)

    def test_price_is_attached_to_every_variant(self):
        from stockwatcher.providers.nike import build_nike_variants, select_product

        variants = build_nike_variants(select_product(NIKE_NEXT_DATA), set())
        assert {v.price for v in variants} == {Decimal("145")}

    def test_missing_payload_is_handled(self):
        from stockwatcher.providers.nike import available_gtins, select_product

        assert select_product({}) is None
        assert available_gtins(None) == set()


# --------------------------------------------------------------------------
# Generic Playwright scraping
# --------------------------------------------------------------------------


class TestPlaywrightVariantBuilding:
    def test_disabled_buttons_are_out_of_stock(self):
        from stockwatcher.providers.playwright_provider import build_variants

        rows = [{"label": "9.5", "available": False}, {"label": "10", "available": True}]
        variants = build_variants(rows, "Nike Mind 002 Men's")
        assert {v.label: v.available for v in variants} == {"9.5": False, "10": True}

    def test_stock_message_is_stripped_from_the_label(self):
        """Rendered buttons often read "10\\nSold Out"."""
        from stockwatcher.providers.playwright_provider import build_variants

        variants = build_variants([{"label": "10\nSold Out", "available": False}], "shoe")
        assert variants[0].label == "10"

    def test_duplicate_and_blank_labels_are_dropped(self):
        from stockwatcher.providers.playwright_provider import build_variants

        rows = [
            {"label": "10", "available": True},
            {"label": "10", "available": True},
            {"label": ""},
        ]
        assert len(build_variants(rows, "shoe")) == 1

    def test_gender_is_inferred_from_the_title(self):
        from stockwatcher.providers.playwright_provider import build_variants

        variants = build_variants([{"label": "9.5", "available": True}], "WMNS Nike Mind 002")
        assert variants[0].size.gender is Gender.WOMENS

    @pytest.mark.parametrize(
        ("text", "expected"),
        [("$145.00", Decimal("145.00")), ("1,299.99 USD", Decimal("1299.99")), ("", None)],
    )
    def test_price_parsing(self, text, expected):
        from stockwatcher.providers.playwright_provider import parse_price

        assert parse_price(text) == expected
