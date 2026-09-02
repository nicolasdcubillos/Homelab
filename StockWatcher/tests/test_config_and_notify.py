"""Config loading, notification batching and run orchestration helpers."""

from __future__ import annotations

from decimal import Decimal

import pytest
import yaml

from stockwatcher.config import ConfigError, Watch, load_config
from stockwatcher.models import Alert, Hit
from stockwatcher.notifiers.base import batch_groups, group_hits, render_text, summarize
from stockwatcher.notifiers.console import ConsoleNotifier
from stockwatcher.runner import consolidate_queries
from stockwatcher.sizes import Gender


def write_config(tmp_path, data: dict):
    path = tmp_path / "watches.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------


class TestConfigLoading:
    def test_loads_a_minimal_watch(self, tmp_path):
        path = write_config(
            tmp_path,
            {
                "watches": [
                    {
                        "name": "Nike Mind 002",
                        "match": ["mind 002"],
                        "variants": ["9.5", "10"],
                        "gender": "mens",
                        "max_price": 160,
                    }
                ]
            },
        )
        config = load_config(path)
        watch = config.watches[0]
        assert watch.name == "Nike Mind 002"
        assert watch.variants == ["9.5", "10"]
        assert watch.gender is Gender.MENS
        assert watch.max_price == Decimal("160")

    def test_defaults_apply_to_every_watch(self, tmp_path):
        path = write_config(
            tmp_path,
            {
                "defaults": {"gender": "mens", "max_price": 160, "notify": ["whatsapp"]},
                "watches": [
                    {"name": "a", "match": ["a"]},
                    {"name": "b", "match": ["b"], "max_price": 500},
                ],
            },
        )
        watches = load_config(path).watches
        assert [w.max_price for w in watches] == [Decimal("160"), Decimal("500")]
        assert all(w.gender is Gender.MENS for w in watches)

    def test_a_config_with_no_watches_is_an_error(self, tmp_path):
        with pytest.raises(ConfigError):
            load_config(write_config(tmp_path, {"watches": []}))

    def test_missing_file_is_an_error(self, tmp_path):
        with pytest.raises(ConfigError):
            load_config(tmp_path / "nope.yaml")

    def test_stores_are_deduplicated(self, tmp_path):
        path = write_config(
            tmp_path,
            {
                "watches": [{"name": "a", "match": ["a"]}],
                "stores": [{"host": "kith.com"}, {"host": "kith.com", "name": "dupe"}],
            },
        )
        assert [s.host for s in load_config(path).stores] == ["kith.com"]

    def test_env_overrides_win(self, tmp_path, monkeypatch):
        """Container Apps configures the job with env vars, not YAML edits."""
        monkeypatch.setenv("STOCKWATCHER_STATE_BACKEND", "azure_table")
        monkeypatch.setenv("STOCKWATCHER_RATE", "2.5")
        path = write_config(
            tmp_path,
            {"watches": [{"name": "a", "match": ["a"]}], "state": {"backend": "sqlite"}},
        )
        config = load_config(path)
        assert config.state.backend == "azure_table"
        assert config.runtime.rate == 2.5


class TestShippedConfig:
    """The repo ships a working config; a typo there breaks every run."""

    def test_default_config_parses(self):
        config = load_config("config/watches.yaml", "config/stores.yaml")
        assert len(config.watches) == 3
        assert len(config.stores) >= 35

    def test_the_three_nike_mind_watches_are_configured_as_asked(self):
        config = load_config("config/watches.yaml", "config/stores.yaml")
        for watch in config.watches:
            assert watch.gender is Gender.MENS
            assert watch.max_price == Decimal("160")
            assert set(watch.variants) == {"9.5", "10"}
            assert "white" in watch.colors

    def test_every_store_uses_a_known_provider(self):
        from stockwatcher.providers import available_providers

        config = load_config("config/watches.yaml", "config/stores.yaml")
        known = set(available_providers())
        assert {s.provider for s in config.stores} <= known


class TestSearchQueries:
    def test_long_terms_also_emit_a_broader_prefix(self):
        """Store search is fuzzy: "mind 002 flyknit" misses the shoe on Kith."""
        watch = Watch(name="w", match=["mind 002 flyknit"])
        assert watch.search_queries == ["mind 002 flyknit", "mind 002"]

    def test_short_terms_are_left_alone(self):
        assert Watch(name="w", match=["mind 002"]).search_queries == ["mind 002"]

    def test_explicit_queries_win(self):
        watch = Watch(name="w", match=["mind 002 flyknit"], queries=["ir2176"])
        assert watch.search_queries == ["ir2176"]

    def test_match_groups_tokenize(self):
        assert Watch(name="w", match=["Mind 002 Flyknit"]).match_groups == [
            ["mind", "002", "flyknit"]
        ]


class TestConsolidateQueries:
    def test_drops_queries_covered_by_a_broader_one(self):
        """Each dropped query is one fewer request against a shared rate budget."""
        queries = ["mind 002", "mind 002 flyknit", "mind 001"]
        assert sorted(consolidate_queries(queries)) == ["mind 001", "mind 002"]

    def test_broadest_query_is_tried_first(self):
        """Ordering matters: the limit truncates the tail."""
        assert consolidate_queries(["nike mind 002 flyknit", "mind"])[0] == "mind"

    def test_keeps_unrelated_queries(self):
        assert sorted(consolidate_queries(["mind 001", "mind 002"])) == ["mind 001", "mind 002"]

    def test_deduplicates(self):
        assert consolidate_queries(["mind 002", "mind 002"]) == ["mind 002"]

    def test_respects_the_limit(self):
        assert len(consolidate_queries(["a", "b", "c", "d", "e"], limit=3)) == 3

    def test_empty_input(self):
        assert consolidate_queries([]) == []


# --------------------------------------------------------------------------
# Notification batching
# --------------------------------------------------------------------------


def hit(variant="10", *, price="145", product="Nike Mind 002", store="Kith", url="https://k.com/p"):
    return Hit(
        watch_name="w",
        store_host="k.com",
        store_name=store,
        provider="shopify",
        product_title=product,
        product_url=url,
        variant_label=variant,
        price=Decimal(price) if price is not None else None,
        currency="USD",
    )


class TestGrouping:
    def test_sizes_at_the_same_price_share_one_message(self):
        groups = group_hits([hit("9.5"), hit("10")])
        assert len(groups) == 1
        assert summarize(groups[0])["variant"] == "10, 9.5"

    def test_different_prices_are_not_merged(self):
        """Otherwise the message could only say "from $X" — the exact failure
        mode that per-variant pricing exists to prevent."""
        groups = group_hits([hit("9", price="358"), hit("8.5", price="314")])
        assert len(groups) == 2
        assert {summarize(g)["price"] for g in groups} == {"$358.00 USD", "$314.00 USD"}

    def test_different_products_are_not_merged(self):
        groups = group_hits(
            [hit(product="A", url="https://k.com/a"), hit(product="B", url="https://k.com/b")]
        )
        assert len(groups) == 2

    def test_tracking_params_do_not_split_a_group(self):
        groups = group_hits([hit(url="https://k.com/p"), hit("9.5", url="https://k.com/p?x=1")])
        assert len(groups) == 1

    def test_batching_respects_the_cap(self):
        group = [hit(str(n)) for n in range(10)]
        batches = batch_groups([group], max_hits_per_message=4)
        assert [len(b) for b in batches] == [4, 4, 2]


class TestRendering:
    def test_message_states_the_price_of_the_size(self):
        text = render_text([hit("9.5", price="145")])
        assert "talla 9.5" in text
        assert "$145.00 USD" in text
        assert "Kith" in text

    def test_message_includes_the_url(self):
        assert "https://k.com/p" in render_text([hit()])

    def test_colour_mismatch_is_flagged_not_hidden(self):
        off = hit()
        off = Hit(**{**off.__dict__, "color_matched": False})
        assert "color fuera de preferencia" in render_text([off])

    def test_unknown_price_is_stated_plainly(self):
        assert "precio no listado" in render_text([hit(price=None)])


class TestConsoleNotifier:
    @pytest.mark.asyncio
    async def test_prints_every_batch(self, capsys):
        await ConsoleNotifier().send(Alert((hit("9.5"), hit("10"))))
        out = capsys.readouterr().out
        assert "talla 10, 9.5" in out

    @pytest.mark.asyncio
    async def test_empty_alert_prints_nothing(self, capsys):
        await ConsoleNotifier().send(Alert(()))
        assert capsys.readouterr().out == ""
