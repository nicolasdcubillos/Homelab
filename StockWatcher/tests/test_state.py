"""State transitions: the logic that stops the same restock alerting hourly."""

from __future__ import annotations

from decimal import Decimal

import pytest

from conftest import make_product
from stockwatcher.matching import build_observations
from stockwatcher.models import Hit, Store, Variant
from stockwatcher.sizes import Gender
from stockwatcher.state import SqliteStateStore, detect_transitions
from stockwatcher.state.base import NullStateStore


def hit(variant_label: str = "10", *, watch: str = "w", url: str = "https://x.com/p") -> Hit:
    return Hit(
        watch_name=watch,
        store_host="x.com",
        store_name="X",
        provider="shopify",
        product_title="Nike Mind 002",
        product_url=url,
        variant_label=variant_label,
        price=Decimal("145"),
        currency="USD",
    )


class TestHitKey:
    def test_key_is_stable(self):
        assert hit().key == hit().key

    def test_key_separates_variants(self):
        assert hit("10").key != hit("9.5").key

    def test_key_separates_watches(self):
        assert hit(watch="a").key != hit(watch="b").key

    def test_key_ignores_tracking_querystring(self):
        """Shopify appends per-session tracking params to search result URLs.

        If those leaked into the key, every run would look like a brand new
        product and alert again.
        """
        plain = hit(url="https://x.com/products/mind-002")
        tracked = hit(url="https://x.com/products/mind-002?pr_prod_strat=e5&pr_seq=uniform")
        assert plain.key == tracked.key


class TestDetectTransitions:
    def test_first_sighting_of_an_available_item_alerts(self):
        """Never seen before but in stock: from the user's view it appeared."""
        result = detect_transitions([(hit(), True)], previous={})
        assert [h.variant_label for h in result.new_hits] == ["10"]

    def test_unavailable_to_available_alerts(self):
        h = hit()
        result = detect_transitions([(h, True)], previous={h.key: False})
        assert len(result.new_hits) == 1

    def test_still_available_does_not_alert(self):
        """The whole point: no hourly spam while an item stays in stock."""
        h = hit()
        result = detect_transitions([(h, True)], previous={h.key: True})
        assert result.new_hits == []
        assert result.still_available == 1

    def test_unavailable_never_alerts(self):
        h = hit()
        result = detect_transitions([(h, False)], previous={h.key: True})
        assert result.new_hits == []
        assert result.updates[h.key] is False

    def test_going_out_of_stock_is_recorded_so_a_restock_alerts_again(self):
        h = hit()
        gone = detect_transitions([(h, False)], previous={h.key: True})
        assert gone.updates[h.key] is False
        back = detect_transitions([(h, True)], previous=gone.updates)
        assert len(back.new_hits) == 1

    def test_duplicate_observations_in_one_run_prefer_available(self):
        """Two search queries can surface the same product; stock wins."""
        h = hit()
        result = detect_transitions([(h, False), (h, True)], previous={})
        assert len(result.new_hits) == 1
        assert result.updates[h.key] is True

    def test_updates_cover_every_observation(self):
        result = detect_transitions([(hit("9.5"), False), (hit("10"), True)], previous={})
        assert len(result.updates) == 2


class TestEndToEndSuppression:
    """The realistic loop: observe -> persist -> observe again."""

    @pytest.mark.asyncio
    async def test_repeat_run_produces_no_alerts(self, tmp_path, mind_watch, store):
        product = make_product(
            variants=[
                Variant.create("9.5", False, price=Decimal("145"), gender=Gender.MENS),
                Variant.create("10", True, price=Decimal("145"), gender=Gender.MENS),
            ]
        )
        observations = build_observations(mind_watch, product, store)

        async with SqliteStateStore(tmp_path / "state.db") as state:
            previous = await state.get_states([h.key for h, _ in observations])
            first = detect_transitions(observations, previous)
            assert len(first.new_hits) == 1
            await state.set_states(first.updates)

            previous = await state.get_states([h.key for h, _ in observations])
            second = detect_transitions(observations, previous)
            assert second.new_hits == []
            assert second.still_available == 1

    @pytest.mark.asyncio
    async def test_restock_after_going_out_alerts_again(self, tmp_path, mind_watch, store):
        sold_out = make_product(
            variants=[Variant.create("10", False, price=Decimal("145"), gender=Gender.MENS)]
        )
        in_stock = make_product(
            variants=[Variant.create("10", True, price=Decimal("145"), gender=Gender.MENS)]
        )

        async with SqliteStateStore(tmp_path / "state.db") as state:
            for product, expected in ((sold_out, 0), (in_stock, 1), (in_stock, 0), (sold_out, 0)):
                observations = build_observations(mind_watch, product, store)
                previous = await state.get_states([h.key for h, _ in observations])
                result = detect_transitions(observations, previous)
                await state.set_states(result.updates)
                assert len(result.new_hits) == expected

            observations = build_observations(mind_watch, in_stock, store)
            previous = await state.get_states([h.key for h, _ in observations])
            assert len(detect_transitions(observations, previous).new_hits) == 1


class TestSqliteStore:
    @pytest.mark.asyncio
    async def test_states_round_trip(self, tmp_path):
        async with SqliteStateStore(tmp_path / "s.db") as state:
            await state.set_states({"a": True, "b": False})
            assert await state.get_states(["a", "b", "missing"]) == {"a": True, "b": False}

    @pytest.mark.asyncio
    async def test_state_persists_across_instances(self, tmp_path):
        path = tmp_path / "s.db"
        async with SqliteStateStore(path) as state:
            await state.set_states({"a": True})
        async with SqliteStateStore(path) as state:
            assert await state.get_states(["a"]) == {"a": True}

    @pytest.mark.asyncio
    async def test_store_registry_round_trip(self, tmp_path):
        from stockwatcher.models import StoreRecord

        async with SqliteStateStore(tmp_path / "s.db") as state:
            await state.upsert_store(
                StoreRecord(host="new.com", provider="shopify", source="discovery")
            )
            records = await state.list_stores()
            assert [r.host for r in records] == ["new.com"]
            assert records[0].source == "discovery"

    @pytest.mark.asyncio
    async def test_run_number_increments(self, tmp_path):
        async with SqliteStateStore(tmp_path / "s.db") as state:
            assert [await state.next_run_number() for _ in range(3)] == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_empty_key_list_does_not_query(self, tmp_path):
        async with SqliteStateStore(tmp_path / "s.db") as state:
            assert await state.get_states([]) == {}


class TestNullStore:
    @pytest.mark.asyncio
    async def test_remembers_nothing_across_instances(self):
        """--state-backend none must alert every run, by design."""
        async with NullStateStore() as state:
            await state.set_states({"a": True})
        async with NullStateStore() as state:
            assert await state.get_states(["a"]) == {}


class TestTransitionsAreProviderAgnostic:
    """Suppression must work identically whichever provider found the stock.

    Nike and the Playwright stores arrive through a completely different code
    path (headless browser, GTIN join) than the Shopify JSON providers, so it
    is worth pinning that they are not special-cased anywhere downstream.
    """

    def nike_hit(self, variant: str = "10") -> Hit:
        return Hit(
            watch_name="Nike Mind 002",
            store_host="www.nike.com",
            store_name="Nike",
            provider="nike",
            product_title="Nike Mind 002",
            product_url="https://www.nike.com/t/mind-002/IR2176-101",
            variant_label=variant,
            price=Decimal("145"),
            currency="USD",
        )

    @pytest.mark.asyncio
    async def test_a_nike_restock_alerts_once_then_goes_quiet(self, tmp_path):
        target = self.nike_hit()
        async with SqliteStateStore(tmp_path / "s.db") as state:
            # Run 1: out of stock, nothing to say.
            first = detect_transitions([(target, False)], await state.get_states([target.key]))
            await state.set_states(first.updates)
            assert first.new_hits == []

            # Run 2: it restocks — alert.
            second = detect_transitions([(target, True)], await state.get_states([target.key]))
            await state.set_states(second.updates)
            assert [h.variant_label for h in second.new_hits] == ["10"]

            # Run 3: still in stock — silence, not a second message.
            third = detect_transitions([(target, True)], await state.get_states([target.key]))
            await state.set_states(third.updates)
            assert third.new_hits == []
            assert third.still_available == 1

            # Run 4: sells out and restocks again — alert again.
            await state.set_states(
                detect_transitions([(target, False)], await state.get_states([target.key])).updates
            )
            fifth = detect_transitions([(target, True)], await state.get_states([target.key]))
            assert [h.variant_label for h in fifth.new_hits] == ["10"]

    def test_the_state_key_ignores_the_provider(self):
        """Switching a store to a browser provider must not replay every alert."""
        via_browser = self.nike_hit()
        via_json = Hit(**{**via_browser.__dict__, "provider": "shopify"})
        assert via_browser.key == via_json.key


def test_store_display_name_falls_back_to_host():
    assert Store(host="kith.com").display_name == "kith.com"
    assert Store(host="kith.com", name="Kith").display_name == "Kith"
