"""Size / variant normalization.

Sneaker sizing is where this system is most likely to alert on the wrong
thing, so these cases are drawn from labels seen on real storefronts.
"""

from __future__ import annotations

import pytest

from stockwatcher.sizes import Gender, infer_gender, is_kids, parse_size, variants_match


class TestParseSize:
    @pytest.mark.parametrize(
        ("label", "expected"),
        [
            ("9.5", 9.5),
            ("10", 10.0),
            ("09.0", 9.0),  # Foot Locker zero-pads
            ("10.0", 10.0),
            ("US 10", 10.0),
            ("Size 9.5", 9.5),
            ("9 1/2", 9.5),
        ],
    )
    def test_plain_labels(self, label, expected):
        size = parse_size(label)
        assert size is not None
        assert size.value == pytest.approx(expected)

    def test_stadium_goods_womens_suffix(self):
        """``9.5W`` is a *women's* 9.5, not a men's."""
        size = parse_size("9.5W")
        assert size is not None
        assert size.value == pytest.approx(9.5)
        assert size.gender is Gender.WOMENS

    def test_leading_w_is_womens(self):
        size = parse_size("W 9.5")
        assert size is not None
        assert size.gender is Gender.WOMENS

    def test_dual_label_resolves_to_mens(self):
        """Nike/Foot Locker label unisex shoes ``M 9 / W 10.5``."""
        size = parse_size("M 9 / W 10.5")
        assert size is not None
        assert size.value == pytest.approx(9.0)
        assert size.gender is Gender.MENS

    @pytest.mark.parametrize(
        ("label", "expected"),
        [
            ("Orange / 9", 9.0),
            ("PINK SMOKE/METALLIC SILVER-MYSTIC DATES / 9.5", 9.5),
            ("Black / Chrome / 10.5", 10.5),
        ],
    )
    def test_compound_titles_take_the_last_segment(self, label, expected):
        """Colour is often glued onto the size with a slash.

        Taking the *first* segment would read "Orange" as the size (and, worse,
        would silently parse ``9`` out of a colour code).
        """
        size = parse_size(label)
        assert size is not None
        assert size.value == pytest.approx(expected)

    @pytest.mark.parametrize("label", ["10.5Y", "5.5Y", "10C", "GS 7", "TD 4"])
    def test_kids_sizes_are_rejected(self, label):
        assert parse_size(label) is None

    @pytest.mark.parametrize("label", ["EU 43", "UK 8.5", "27.5 CM"])
    def test_foreign_scales_are_rejected(self, label):
        """Only US sizing is understood; anything else must not be guessed."""
        assert parse_size(label) is None

    def test_unparseable_label_is_none(self):
        assert parse_size("One Size") is None
        assert parse_size("") is None


class TestIsKids:
    @pytest.mark.parametrize("label", ["10.5Y", "6.5y", "GS 7"])
    def test_detects_kids(self, label):
        assert is_kids(label)

    def test_adult_sizes_are_not_kids(self):
        assert not is_kids("10.5")


class TestInferGender:
    @pytest.mark.parametrize(
        "title",
        [
            "WMNS Nike Mind 002",
            "Nike Mind 002 Women's",
            "Nike W Air Max",
            "Nike Mind 002 (Women)",
        ],
    )
    def test_womens_titles(self, title):
        assert infer_gender(title) is Gender.WOMENS

    @pytest.mark.parametrize(
        "title",
        ["Nike Mind 001 Mule - Men's", "Nike Mind 002 Mens Running Shoes"],
    )
    def test_mens_titles(self, title):
        assert infer_gender(title) is Gender.MENS

    def test_unmarked_title_is_unisex(self):
        assert infer_gender("Nike Mind 002 Flyknit") is Gender.UNISEX


class TestVariantsMatch:
    def test_same_size_matches(self):
        assert variants_match("9.5", "9.5", store_gender=Gender.MENS, requested_gender=Gender.MENS)

    def test_zero_padded_matches(self):
        assert variants_match("09.5", "9.5", store_gender=Gender.MENS, requested_gender=Gender.MENS)

    def test_womens_size_never_matches_a_mens_watch(self):
        """The headline case: Stadium Goods ``9.5W`` must not fire a mens watch."""
        assert not variants_match(
            "9.5W", "9.5", store_gender=Gender.WOMENS, requested_gender=Gender.MENS
        )

    def test_mens_size_never_matches_a_womens_watch(self):
        assert not variants_match(
            "9.5", "9.5", store_gender=Gender.MENS, requested_gender=Gender.WOMENS
        )

    def test_dual_label_matches_mens_watch(self):
        assert variants_match(
            "M 9 / W 10.5", "9", store_gender=Gender.MENS, requested_gender=Gender.MENS
        )

    def test_unisex_request_matches_anything(self):
        assert variants_match(
            "9.5", "9.5", store_gender=Gender.MENS, requested_gender=Gender.UNISEX
        )

    def test_different_sizes_do_not_match(self):
        assert not variants_match(
            "10.5", "9.5", store_gender=Gender.MENS, requested_gender=Gender.MENS
        )

    def test_non_numeric_variants_fall_back_to_text(self):
        """Keeps the engine generic: 'variant' is not always a shoe size."""
        assert variants_match(
            "256GB", "256gb", store_gender=Gender.UNISEX, requested_gender=Gender.UNISEX
        )
        assert not variants_match(
            "512GB", "256gb", store_gender=Gender.UNISEX, requested_gender=Gender.UNISEX
        )
