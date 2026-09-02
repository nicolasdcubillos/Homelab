"""Watch/product matching: price, colour, gender and the per-variant price rule."""

from __future__ import annotations

from decimal import Decimal

import pytest

from conftest import make_product
from stockwatcher.config import Watch
from stockwatcher.matching import (
    build_hits,
    build_observations,
    color_matched,
    effective_price,
    match_product,
    price_ok,
    store_allowed,
    text_excluded,
    text_matches,
)
from stockwatcher.models import Store, Variant
from stockwatcher.providers.shopify import ShopifyProvider
from stockwatcher.sizes import Gender


def variant(label: str, available: bool, price: str | None = None, gender=Gender.MENS) -> Variant:
    return Variant.create(
        label,
        available,
        price=Decimal(price) if price is not None else None,
        gender=gender,
    )


class TestTextMatching:
    def test_all_tokens_of_a_group_must_be_present(self, mind_watch):
        assert text_matches(mind_watch, "Nike Mind 002 Flyknit")
        assert not text_matches(mind_watch, "Nike Mind 001")

    def test_any_group_may_match(self):
        watch = Watch(name="w", match=["mind 002 flyknit", "ir2176"])
        assert text_matches(watch, "Nike IR2176 sample")
        assert text_matches(watch, "Nike Mind 002 Flyknit Wolf Grey")

    def test_exclusions(self, mind_watch):
        assert text_excluded(mind_watch, "WMNS Nike Mind 002")
        assert not text_excluded(mind_watch, "Nike Mind 002")


class TestColorMatching:
    def test_preferred_colour_present(self, mind_watch):
        assert color_matched(mind_watch, "Nike Mind 002 Flyknit White / Platinum")

    def test_colour_absent_is_not_a_match(self, mind_watch):
        assert not color_matched(mind_watch, "Nike Mind 002 Black/Chrome")

    def test_no_preference_always_matches(self):
        assert color_matched(Watch(name="w", match=["x"]), "anything at all")

    def test_colour_is_soft_and_still_alerts(self, mind_watch, store):
        """A colour miss must flag, not suppress — a restock is still news."""
        product = make_product(
            title="Nike Mind 002", colorway="Black/Chrome", variants=[variant("10", True, "145")]
        )
        hits = build_hits(mind_watch, product, store)
        assert len(hits) == 1
        assert hits[0].color_matched is False


class TestPriceFiltering:
    def test_within_budget(self, mind_watch):
        assert price_ok(mind_watch, Decimal("145"))

    def test_over_budget(self, mind_watch):
        assert not price_ok(mind_watch, Decimal("358"))

    def test_exactly_at_budget(self, mind_watch):
        assert price_ok(mind_watch, Decimal("160"))

    def test_unknown_price_passes(self, mind_watch):
        """Better a noisy alert than a missed restock."""
        assert price_ok(mind_watch, None)

    def test_no_budget_passes_everything(self):
        assert price_ok(Watch(name="w", match=["x"]), Decimal("9999"))


class TestEffectivePrice:
    def test_variant_price_wins(self):
        product = make_product(price=Decimal("216"))
        assert effective_price(product, variant("9", True, "358")) == Decimal("358")

    def test_falls_back_to_product_price_only_when_variant_has_none(self):
        product = make_product(price=Decimal("145"))
        assert effective_price(product, variant("9", True)) == Decimal("145")


class TestGenderSeparation:
    def test_womens_listing_never_matches_a_mens_watch(self, mind_watch, store):
        product = make_product(
            title="WMNS Nike Mind 002", gender=Gender.WOMENS, variants=[variant("9.5", True, "145")]
        )
        assert match_product(mind_watch, product, store) == []

    def test_stadium_goods_w_suffix_is_not_a_mens_size(self, mind_watch, store):
        """``9.5W`` is a women's 9.5 and must not satisfy ``variants: ["9.5"]``."""
        product = make_product(
            variants=[
                variant("9.5W", True, "145", gender=Gender.UNISEX),
                variant("11", True, "145"),
            ]
        )
        assert match_product(mind_watch, product, store) == []


class TestStoreFiltering:
    def test_country_filter(self, mind_watch):
        canada = Store(host="capsuletoronto.com", country="CA")
        assert not store_allowed(mind_watch, canada)
        assert store_allowed(mind_watch, Store(host="kith.com", country="US"))

    def test_per_watch_allow_list(self):
        watch = Watch(name="w", match=["x"], stores=["kith.com"])
        assert store_allowed(watch, Store(host="kith.com"))
        assert not store_allowed(watch, Store(host="bodega.com"))


class TestObservations:
    def test_unavailable_variants_are_still_observed(self, mind_watch, store):
        """Recording sold-out sizes is what makes the transition detectable."""
        product = make_product(variants=[variant("9.5", False, "145"), variant("10", True, "145")])
        observations = build_observations(mind_watch, product, store)
        assert sorted((h.variant_label, ok) for h, ok in observations) == [
            ("10", True),
            ("9.5", False),
        ]

    def test_build_hits_returns_only_in_stock(self, mind_watch, store):
        product = make_product(variants=[variant("9.5", False, "145"), variant("10", True, "145")])
        assert [h.variant_label for h in build_hits(mind_watch, product, store)] == ["10"]


# ---------------------------------------------------------------------------
# The regression that guards the whole per-variant-price class of bug.
# ---------------------------------------------------------------------------

#: Real payload shape from
#: stadiumgoods.com/products/yeezy-boost-350-v2-zebra-2017-2023-022952.js
#:
#: The product-level price (21600 = $216.00) is the *minimum* across variants,
#: and here it belongs to sizes that are sold out.  The sizes actually for sale
#: cost far more.  Treating $216 as "the price" would fire a max_price alert
#: for a price the user cannot pay.
STADIUM_GOODS_ZEBRA = {
    "title": "Yeezy Boost 350 V2 'Zebra' 2017/2023",
    "price": 21600,
    "vendor": "adidas",
    "url": "/products/yeezy-boost-350-v2-zebra-2017-2023-022952",
    "variants": [
        {"title": "8.5", "available": True, "price": 31400, "sku": "022952-085"},
        {"title": "9", "available": True, "price": 35800, "sku": "022952-090"},
        {"title": "9.5", "available": False, "price": 21600, "sku": "022952-095"},
        {"title": "10", "available": False, "price": 21600, "sku": "022952-100"},
    ],
}


@pytest.fixture
def zebra_product():
    store = Store(host="stadiumgoods.com", provider="shopify", name="Stadium Goods")
    provider = ShopifyProvider(store, http=None)
    ref = provider.parse_search(
        {
            "resources": {
                "results": {
                    "products": [
                        {
                            "title": STADIUM_GOODS_ZEBRA["title"],
                            "price": "216.00",
                            "url": STADIUM_GOODS_ZEBRA["url"] + "?pr_prod_strat=e5",
                        }
                    ]
                }
            }
        }
    )[0]
    return provider.parse_product(ref, STADIUM_GOODS_ZEBRA)


class TestPerVariantPriceRegression:
    def test_variant_prices_are_read_individually(self, zebra_product):
        prices = {v.label: v.price for v in zebra_product.variants}
        assert prices == {
            "8.5": Decimal("314.00"),
            "9": Decimal("358.00"),
            "9.5": Decimal("216.00"),
            "10": Decimal("216.00"),
        }

    def test_product_price_is_not_used_as_a_variant_price(self, zebra_product):
        """$216 is the minimum across variants, not the price of size 9."""
        size_nine = next(v for v in zebra_product.variants if v.label == "9")
        assert effective_price(zebra_product, size_nine) == Decimal("358.00")
        assert zebra_product.price == Decimal("216.00")

    def test_no_alerts_for_an_in_budget_price_on_a_sold_out_size(self, zebra_product):
        """The required guard.

        Sizes 9 and 10 are requested with a $250 budget.  Size 10 is within
        budget but sold out; size 9 is in stock but costs $358.  The correct
        answer is *zero* alerts.  Using the product-level price would wrongly
        alert on size 9 at "$216".
        """
        watch = Watch(
            name="Yeezy Zebra",
            match=["yeezy boost 350 v2 zebra"],
            variants=["9", "10"],
            gender=Gender.MENS,
            max_price=Decimal("250"),
        )
        store = Store(host="stadiumgoods.com", provider="shopify")
        assert build_hits(watch, zebra_product, store) == []

    def test_a_budget_that_covers_the_real_price_does_alert(self, zebra_product):
        """Sanity check: the filter is not simply rejecting everything."""
        watch = Watch(
            name="Yeezy Zebra",
            match=["yeezy boost 350 v2 zebra"],
            variants=["9", "10"],
            gender=Gender.MENS,
            max_price=Decimal("400"),
        )
        store = Store(host="stadiumgoods.com", provider="shopify")
        hits = build_hits(watch, zebra_product, store)
        assert [(h.variant_label, h.price) for h in hits] == [("9", Decimal("358.00"))]
