"""Store auto-discovery and run orchestration robustness."""

from __future__ import annotations

import httpx
import pytest
import respx

from stockwatcher.config import Config, DiscoveryConfig, Watch, load_config
from stockwatcher.discovery import (
    YamlStoreRegistry,
    build_store_registry,
    candidate_hosts,
    discover_stores,
    discovery_queries,
    is_blocked,
    probe_shopify,
)
from stockwatcher.discovery.registry import StateStoreRegistry
from stockwatcher.discovery.search import (
    NullSearchBackend,
    SearchBackend,
    build_search_backend,
    host_of,
)
from stockwatcher.http import HttpClient
from stockwatcher.models import Store, StoreRecord
from stockwatcher.providers.base import ProviderError
from stockwatcher.runner import Runner, merge_stores
from stockwatcher.sizes import Gender
from stockwatcher.state import SqliteStateStore

SHOPIFY_HIT = {
    "resources": {
        "results": {
            "products": [
                {"title": "Nike Mind 002 Flyknit", "price": "145.00", "url": "/products/mind-002"}
            ]
        }
    }
}
SHOPIFY_MISS = {"resources": {"results": {"products": [{"title": "Wool Hat", "url": "/p/hat"}]}}}


class FakeSearch(SearchBackend):
    """A search backend that always offers one promotable host."""

    enabled = True

    async def search(self, query, limit=20):
        return ["https://newstore.com/collections/all", "https://amazon.com/x"]


@pytest.fixture
def watch():
    return Watch(name="Mind 002", match=["mind 002"], gender=Gender.MENS)


class TestHostFiltering:
    @pytest.mark.parametrize(
        "host",
        ["amazon.com", "www.stockx.com", "goat.com", "reddit.com", "sneakernews.com"],
    )
    def test_marketplaces_and_blogs_are_blocked(self, host):
        """Aggregators list stock they do not sell; promoting them means noise."""
        assert is_blocked(host)

    @pytest.mark.parametrize("host", ["kith.com", "bodega.com", "www.shoepalace.com"])
    def test_real_retailers_pass(self, host):
        assert not is_blocked(host)

    def test_candidates_skip_known_hosts(self):
        urls = ["https://kith.com/x", "https://newstore.com/y"]
        assert candidate_hosts(urls, known={"kith.com"}) == ["newstore.com"]

    def test_www_prefix_does_not_defeat_the_known_check(self):
        """Otherwise every seeded store would be rediscovered every pass."""
        assert candidate_hosts(["https://www.kith.com/x"], known={"kith.com"}) == []

    def test_candidates_are_deduplicated(self):
        urls = ["https://a.com/1", "https://a.com/2", "https://b.com/1"]
        assert candidate_hosts(urls, known=set()) == ["a.com", "b.com"]

    def test_junk_urls_are_ignored(self):
        assert candidate_hosts(["not a url", ""], known=set()) == []

    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("https://kith.com/products/x", "kith.com"),
            ("http://www.a.co.uk/y?z=1", "www.a.co.uk"),
            ("garbage", None),
        ],
    )
    def test_host_of(self, url, expected):
        assert host_of(url) == expected


class TestDiscoveryQueries:
    def test_derived_from_match_terms(self, watch):
        queries = discovery_queries(watch)
        assert queries
        assert all("mind 002" in q for q in queries)


class TestProbe:
    @pytest.mark.asyncio
    @respx.mock
    async def test_promotes_a_shopify_host_selling_the_product(self, watch):
        respx.get("https://newstore.com/search/suggest.json").mock(
            return_value=httpx.Response(200, json=SHOPIFY_HIT)
        )
        http = HttpClient(rate=0, default_delay=0)
        try:
            assert await probe_shopify("newstore.com", watch, http) is True
        finally:
            await http.aclose()

    @pytest.mark.asyncio
    @respx.mock
    async def test_rejects_a_shopify_host_without_the_product(self, watch):
        """Being on Shopify is not enough — it has to sell the thing."""
        respx.get("https://hats.com/search/suggest.json").mock(
            return_value=httpx.Response(200, json=SHOPIFY_MISS)
        )
        http = HttpClient(rate=0, default_delay=0)
        try:
            assert await probe_shopify("hats.com", watch, http) is False
        finally:
            await http.aclose()

    @pytest.mark.asyncio
    @respx.mock
    async def test_rejects_a_non_shopify_host(self, watch):
        respx.get("https://blog.com/search/suggest.json").mock(
            return_value=httpx.Response(200, html="<html>not shopify</html>")
        )
        http = HttpClient(rate=0, default_delay=0)
        try:
            assert await probe_shopify("blog.com", watch, http) is False
        finally:
            await http.aclose()

    @pytest.mark.asyncio
    @respx.mock
    async def test_network_failure_is_not_fatal(self, watch):
        respx.get("https://down.com/search/suggest.json").mock(
            side_effect=httpx.ConnectError("nope")
        )
        http = HttpClient(rate=0, default_delay=0, max_retries=0)
        try:
            assert await probe_shopify("down.com", watch, http) is False
        finally:
            await http.aclose()


class TestSearchBackend:
    def test_no_api_key_degrades_to_a_no_op(self, monkeypatch):
        """Discovery must never be a hard dependency on a paid API."""
        for var in ("BRAVE_SEARCH_API_KEY", "BING_SEARCH_API_KEY", "SERPAPI_API_KEY"):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.delenv("STOCKWATCHER_SEARCH_BACKEND", raising=False)
        backend = build_search_backend(http=None, backend="auto")
        assert not backend.enabled

    @pytest.mark.asyncio
    async def test_null_backend_returns_nothing(self):
        assert await NullSearchBackend().search("anything") == []


class TestDiscoverStores:
    @pytest.mark.asyncio
    @respx.mock
    async def test_promotes_and_persists(self, tmp_path, watch):
        respx.get("https://newstore.com/search/suggest.json").mock(
            return_value=httpx.Response(200, json=SHOPIFY_HIT)
        )
        http = HttpClient(rate=0, default_delay=0)
        try:
            async with SqliteStateStore(tmp_path / "s.db") as state:
                promoted = await discover_stores(
                    watches=[watch],
                    known_hosts={"kith.com"},
                    http=http,
                    config=DiscoveryConfig(),
                    state=state,
                    backend=FakeSearch(),
                )
                assert [r.host for r in promoted] == ["newstore.com"]
                assert [r.host for r in await state.list_stores()] == ["newstore.com"]
                assert promoted[0].source == "discovery"
                assert promoted[0].first_seen is not None
        finally:
            await http.aclose()

    @pytest.mark.asyncio
    async def test_disabled_backend_is_a_no_op(self, tmp_path, watch):
        async with SqliteStateStore(tmp_path / "s.db") as state:
            promoted = await discover_stores(
                watches=[watch],
                known_hosts=set(),
                http=None,
                config=DiscoveryConfig(),
                state=state,
                backend=NullSearchBackend(),
            )
        assert promoted == []


class TestSharedDiscoveryRegistry:
    """Discovery must not spend one user's search quota on what another user
    already found.  With per-user state stores that only works if promotions
    land somewhere shared."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_promotions_go_to_the_registry_not_to_private_state(self, tmp_path, watch):
        registry = tmp_path / "registry.yaml"
        respx.get("https://newstore.com/search/suggest.json").mock(
            return_value=httpx.Response(200, json=SHOPIFY_HIT)
        )
        http = HttpClient(rate=0, default_delay=0)
        try:
            async with SqliteStateStore(tmp_path / "user-a.db") as state:
                promoted = await discover_stores(
                    watches=[watch],
                    known_hosts=set(),
                    http=http,
                    config=DiscoveryConfig(registry_path=str(registry)),
                    state=state,
                    backend=FakeSearch(),
                )
                assert [r.host for r in promoted] == ["newstore.com"]
                # The user's own state stays about *this* user.
                assert await state.list_stores() == []
        finally:
            await http.aclose()

        assert [r.host for r in await YamlStoreRegistry(registry).list_stores()] == ["newstore.com"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_second_user_does_not_reprobe_a_known_host(self, tmp_path, watch):
        registry = tmp_path / "registry.yaml"
        route = respx.get("https://newstore.com/search/suggest.json").mock(
            return_value=httpx.Response(200, json=SHOPIFY_HIT)
        )
        config = DiscoveryConfig(registry_path=str(registry))
        http = HttpClient(rate=0, default_delay=0)
        try:
            async with SqliteStateStore(tmp_path / "user-a.db") as state:
                await discover_stores(
                    watches=[watch],
                    known_hosts=set(),
                    http=http,
                    config=config,
                    state=state,
                    backend=FakeSearch(),
                )
            probes_after_first_user = route.call_count

            async with SqliteStateStore(tmp_path / "user-b.db") as state:
                promoted = await discover_stores(
                    watches=[watch],
                    known_hosts=set(),
                    http=http,
                    config=config,
                    state=state,
                    backend=FakeSearch(),
                )
        finally:
            await http.aclose()

        assert promoted == []
        assert route.call_count == probes_after_first_user

    @pytest.mark.asyncio
    async def test_the_registry_is_append_only(self, tmp_path):
        """Concurrent users append to one file; nobody may overwrite it."""
        registry = YamlStoreRegistry(tmp_path / "registry.yaml")
        await registry.add(StoreRecord(host="a.com", note="first"))
        await registry.add(StoreRecord(host="b.com", note="second"))
        await registry.add(StoreRecord(host="a.com", note="duplicate"))

        records = await registry.list_stores()
        assert [r.host for r in records] == ["a.com", "b.com"]
        assert records[0].note == "first"
        assert await registry.known_hosts() == {"a.com", "b.com"}

    @pytest.mark.asyncio
    async def test_an_absent_registry_reads_as_empty(self, tmp_path):
        registry = YamlStoreRegistry(tmp_path / "nothing-here.yaml")
        assert await registry.list_stores() == []
        assert await registry.known_hosts() == set()

    @pytest.mark.asyncio
    async def test_registry_stores_are_scanned_by_everyone(self, tmp_path):
        """A promotion nobody reads back is a promotion nobody benefits from."""
        registry = YamlStoreRegistry(tmp_path / "registry.yaml")
        await registry.add(StoreRecord(host="newstore.com", country="CA"))

        watches = tmp_path / "watches.yaml"
        watches.write_text(
            "watches:\n  - {name: a, match: [a]}\n"
            f"discovery: {{registry_path: {tmp_path / 'registry.yaml'}}}\n",
            encoding="utf-8",
        )
        config = load_config(watches)
        found = {s.host: s for s in config.stores}
        assert found["newstore.com"].country == "CA"
        assert found["newstore.com"].source == "discovery"

    def test_a_configured_store_wins_over_the_registry(self, tmp_path):
        registry = tmp_path / "registry.yaml"
        registry.write_text(
            "stores:\n  - {host: kith.com, provider: playwright, source: discovery}\n",
            encoding="utf-8",
        )
        watches = tmp_path / "watches.yaml"
        watches.write_text(
            "watches:\n  - {name: a, match: [a]}\n"
            "stores:\n  - {host: kith.com, provider: shopify}\n"
            f"discovery: {{registry_path: {registry}}}\n",
            encoding="utf-8",
        )
        config = load_config(watches)
        assert [(s.host, s.provider) for s in config.stores] == [("kith.com", "shopify")]

    def test_the_default_target_is_still_the_state_store(self):
        """Single-user installs keep working with no registry configured."""
        assert isinstance(build_store_registry(DiscoveryConfig(), state=None), StateStoreRegistry)
        assert isinstance(
            build_store_registry(DiscoveryConfig(registry_path="x.yaml"), state=None),
            YamlStoreRegistry,
        )

    def test_the_registry_path_can_come_from_the_environment(self, tmp_path, monkeypatch):
        monkeypatch.setenv("STOCKWATCHER_DISCOVERY_REGISTRY", str(tmp_path / "shared.yaml"))
        watches = tmp_path / "watches.yaml"
        watches.write_text("watches:\n  - {name: a, match: [a]}\n", encoding="utf-8")
        assert load_config(watches).discovery.registry_path == str(tmp_path / "shared.yaml")

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_run_promotes_into_the_registry(self, tmp_path, watch, monkeypatch):
        """The whole point is the scheduled `run`, not just `discover`."""
        monkeypatch.setattr(
            "stockwatcher.discovery.build_search_backend", lambda http, backend: FakeSearch()
        )
        respx.get("https://newstore.com/search/suggest.json").mock(
            return_value=httpx.Response(200, json=SHOPIFY_HIT)
        )
        registry = tmp_path / "registry.yaml"
        config = Config(watches=[watch])
        config.discovery.registry_path = str(registry)

        http = HttpClient(rate=0, default_delay=0)
        try:
            async with SqliteStateStore(tmp_path / "user-a.db") as state:
                summary = await Runner(config, http=http, state=state).run(discover=True)
                assert await state.list_stores() == []
        finally:
            await http.aclose()

        assert summary.discovered_stores == ["newstore.com"]
        assert [r.host for r in await YamlStoreRegistry(registry).list_stores()] == ["newstore.com"]


class TestMergeStores:
    def test_registry_entries_are_added(self):
        from stockwatcher.models import StoreRecord

        merged = merge_stores(
            [Store(host="kith.com")],
            [StoreRecord(host="newstore.com", provider="shopify", source="discovery")],
        )
        assert {s.host for s in merged} == {"kith.com", "newstore.com"}

    def test_retired_registry_entries_are_dropped(self):
        from stockwatcher.models import StoreRecord

        merged = merge_stores(
            [],
            [StoreRecord(host="dead.com", provider="shopify", enabled=False, source="discovery")],
        )
        assert merged == []

    def test_config_wins_over_the_registry(self):
        from stockwatcher.models import StoreRecord

        merged = merge_stores(
            [Store(host="kith.com", provider="shopify", name="Kith")],
            [StoreRecord(host="kith.com", provider="playwright", source="discovery")],
        )
        assert [s.provider for s in merged] == ["shopify"]

    def test_a_locally_retired_discovery_stays_retired(self):
        """A store promoted through the shared registry arrives as a config
        store.  Auto-retire is per user and lives in their state, so it has to
        outrank that or a dead store would be scanned forever."""
        from stockwatcher.models import StoreRecord

        merged = merge_stores(
            [Store(host="dead.com", source="discovery")],
            [StoreRecord(host="dead.com", enabled=False, source="discovery")],
        )
        assert merged == []

    def test_a_seeded_store_is_never_retired_by_the_registry(self):
        """Curated stores are the operator's decision, not the runner's."""
        from stockwatcher.models import StoreRecord

        merged = merge_stores(
            [Store(host="kith.com", source="seed")],
            [StoreRecord(host="kith.com", enabled=False, source="discovery")],
        )
        assert [s.host for s in merged] == ["kith.com"]


class TestRunnerRobustness:
    @pytest.mark.asyncio
    async def test_one_failing_store_does_not_abort_the_run(self, tmp_path, monkeypatch):
        """A single broken retailer must never cost the user an alert elsewhere."""
        from stockwatcher.models import Product, ProductRef, Variant

        good = Store(host="good.com", provider="shopify", name="Good")
        bad = Store(host="bad.com", provider="shopify", name="Bad")

        class FakeProvider:
            def __init__(self, store, http):
                self.store = store

            async def search(self, query):
                if self.store.host == "bad.com":
                    raise ProviderError("boom")
                return [
                    ProductRef(
                        store_host="good.com",
                        provider="shopify",
                        url="https://good.com/p",
                        title="Nike Mind 002",
                    )
                ]

            async def fetch(self, ref):
                return Product(
                    ref=ref,
                    title="Nike Mind 002",
                    url=ref.url,
                    variants=[Variant.create("10", True, gender=Gender.MENS)],
                    currency="USD",
                    gender=Gender.MENS,
                    store_host="good.com",
                    provider="shopify",
                )

            async def aclose(self):
                return None

        monkeypatch.setattr("stockwatcher.runner.build_provider", FakeProvider)

        config = Config(
            watches=[Watch(name="Mind 002", match=["mind 002"], gender=Gender.MENS)],
            stores=[good, bad],
        )
        config.state.path = str(tmp_path / "s.db")

        sent: list = []

        class CaptureNotifier:
            async def send(self, alert):
                sent.extend(alert.hits)

            async def aclose(self):
                return None

        async with SqliteStateStore(tmp_path / "s.db") as state:
            http = HttpClient(rate=0, default_delay=0)
            try:
                runner = Runner(config, http=http, state=state)
                monkeypatch.setattr(runner, "_notifier", lambda channel: CaptureNotifier())
                summary = await runner.run(discover=False)
            finally:
                await http.aclose()

        assert summary.stores_scanned == 1
        assert summary.stores_failed == 1
        assert [h.store_host for h in sent] == ["good.com"]
        assert any("bad.com" in e for e in summary.errors)

    @pytest.mark.asyncio
    async def test_a_store_whose_every_query_fails_counts_as_failed(self, tmp_path, monkeypatch):
        """Otherwise a clean-looking scan resets fail_count and auto-retire
        never fires, so a permanently broken store is watched forever."""

        class AlwaysFails:
            def __init__(self, store, http):
                pass

            async def search(self, query):
                raise ProviderError("boom")

            async def fetch(self, ref):  # pragma: no cover - never reached
                raise AssertionError

            async def aclose(self):
                return None

        monkeypatch.setattr("stockwatcher.runner.build_provider", AlwaysFails)
        config = Config(
            watches=[Watch(name="Mind 002", match=["mind 002"], queries=["a", "b"])],
            stores=[Store(host="bad.com", provider="shopify")],
        )
        async with SqliteStateStore(tmp_path / "s.db") as state:
            http = HttpClient(rate=0, default_delay=0)
            try:
                summary = await Runner(config, http=http, state=state).run(discover=False)
            finally:
                await http.aclose()

        assert summary.stores_failed == 1
        assert summary.stores_scanned == 0

    @pytest.mark.asyncio
    async def test_one_flaky_query_out_of_several_is_tolerated(self, tmp_path, monkeypatch):
        calls: list[str] = []

        class OneFlakyQuery:
            def __init__(self, store, http):
                pass

            async def search(self, query):
                calls.append(query)
                if query == "a":
                    raise ProviderError("boom")
                return []

            async def fetch(self, ref):  # pragma: no cover - never reached
                raise AssertionError

            async def aclose(self):
                return None

        monkeypatch.setattr("stockwatcher.runner.build_provider", OneFlakyQuery)
        config = Config(
            watches=[Watch(name="Mind 002", match=["mind 002"], queries=["a", "b"])],
            stores=[Store(host="ok.com", provider="shopify")],
        )
        async with SqliteStateStore(tmp_path / "s.db") as state:
            http = HttpClient(rate=0, default_delay=0)
            try:
                summary = await Runner(config, http=http, state=state).run(discover=False)
            finally:
                await http.aclose()

        assert sorted(calls) == ["a", "b"]
        assert summary.stores_failed == 0
        assert summary.stores_scanned == 1
