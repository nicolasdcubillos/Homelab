"""Where a run's alerts are delivered, and who gets to decide.

StockWatcher is invoked once per user by an external scheduler, out of a
checkout (and a ``.env``) shared by everybody.  Getting the destination
precedence wrong does not fail loudly — it silently sends one user's alerts to
another user's phone or inbox, so it is pinned here.
"""

from __future__ import annotations

import os
import re

import pytest
import yaml

from stockwatcher import cli
from stockwatcher.config import (
    Config,
    ConfigError,
    NotifyConfig,
    NotifyTarget,
    Watch,
    load_config,
    parse_notify_destinations,
)
from stockwatcher.notifiers.base import destination_env, resolve_destinations
from stockwatcher.runner import Runner
from stockwatcher.state import NullStateStore


@pytest.fixture(autouse=True)
def clean_destination_env(monkeypatch):
    """No test may inherit a destination from the developer's own shell."""
    for var in ("WHATSAPP_TO", "EMAIL_TO"):
        monkeypatch.delenv(var, raising=False)


def write_config(tmp_path, data: dict):
    path = tmp_path / "watches.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------


class TestParseNotifyDestinations:
    def test_an_address_is_routed_to_email(self):
        """`--notify-to me@example.com` has to do the obvious thing."""
        assert parse_notify_destinations(["me@example.com"]) == {"email": ["me@example.com"]}

    def test_a_number_is_routed_to_whatsapp(self):
        assert parse_notify_destinations(["+573001234567"]) == {"whatsapp": ["+573001234567"]}

    def test_an_explicit_channel_wins_over_the_shape(self):
        assert parse_notify_destinations(["whatsapp:me@example.com"]) == {
            "whatsapp": ["me@example.com"]
        }

    def test_one_flag_can_carry_several_destinations(self):
        assert parse_notify_destinations(["whatsapp:+57300,+57301"]) == {
            "whatsapp": ["+57300", "+57301"]
        }

    def test_repeated_flags_accumulate_per_channel(self):
        parsed = parse_notify_destinations(["me@example.com", "+573001234567"])
        assert parsed == {"email": ["me@example.com"], "whatsapp": ["+573001234567"]}

    def test_duplicates_collapse(self):
        assert parse_notify_destinations(["a@x.com", "a@x.com"]) == {"email": ["a@x.com"]}

    def test_a_mapping_is_accepted_for_yaml(self):
        assert parse_notify_destinations({"email": ["a@x.com", "b@x.com"]}) == {
            "email": ["a@x.com", "b@x.com"]
        }

    def test_nothing_configured_is_not_an_error(self):
        assert parse_notify_destinations(None) == {}

    def test_an_empty_destination_is_reported(self):
        with pytest.raises(ConfigError):
            parse_notify_destinations(["email:"])


class TestWatchNotifyTargets:
    def test_a_bare_channel_carries_no_destination(self, tmp_path):
        path = write_config(
            tmp_path, {"watches": [{"name": "a", "match": ["a"], "notify": ["email"]}]}
        )
        assert load_config(path).watches[0].notify == [NotifyTarget("email")]

    def test_a_channel_can_pin_its_destination(self, tmp_path):
        path = write_config(
            tmp_path,
            {"watches": [{"name": "a", "match": ["a"], "notify": ["email:me@example.com"]}]},
        )
        assert load_config(path).watches[0].notify == [NotifyTarget("email", ("me@example.com",))]

    def test_the_default_channel_is_still_whatsapp(self, tmp_path):
        path = write_config(tmp_path, {"watches": [{"name": "a", "match": ["a"]}]})
        assert load_config(path).watches[0].notify == [NotifyTarget("whatsapp")]

    def test_a_destination_without_a_channel_is_rejected(self, tmp_path):
        """Otherwise it would register as an unknown channel at send time,
        long after the config could have said so."""
        path = write_config(
            tmp_path, {"watches": [{"name": "a", "match": ["a"], "notify": ["me@example.com"]}]}
        )
        with pytest.raises(ConfigError, match=re.escape("email:me@example.com")):
            load_config(path)

    def test_notify_options_accepts_a_destination_map(self, tmp_path):
        path = write_config(
            tmp_path,
            {
                "watches": [{"name": "a", "match": ["a"]}],
                "notify_options": {"max_hits_per_message": 3, "to": {"email": "a@x.com"}},
            },
        )
        config = load_config(path)
        assert config.notify.max_hits_per_message == 3
        assert config.notify.to == {"email": ["a@x.com"]}

    def test_unknown_notify_options_keys_are_rejected(self, tmp_path):
        path = write_config(
            tmp_path,
            {"watches": [{"name": "a", "match": ["a"]}], "notify_options": {"nope": 1}},
        )
        with pytest.raises(ConfigError, match="nope"):
            load_config(path)


# --------------------------------------------------------------------------
# Precedence
# --------------------------------------------------------------------------


class TestResolveDestinations:
    def test_channels_declare_their_environment_variable(self):
        assert destination_env("email") == "EMAIL_TO"
        assert destination_env("whatsapp") == "WHATSAPP_TO"
        assert destination_env("console") is None

    def test_the_flag_wins_over_everything(self, monkeypatch):
        monkeypatch.setenv("EMAIL_TO", "env@example.com")
        assert resolve_destinations(
            "email", override=["flag@example.com"], configured=["yaml@example.com"]
        ) == ["flag@example.com"]

    def test_the_environment_wins_over_the_yaml(self, monkeypatch):
        """The scheduler injects the destination per subprocess; a YAML value
        shipped in a shared checkout must never outrank it."""
        monkeypatch.setenv("EMAIL_TO", "env@example.com")
        assert resolve_destinations("email", configured=["yaml@example.com"]) == ["env@example.com"]

    def test_the_yaml_is_the_fallback(self):
        assert resolve_destinations("email", configured=["yaml@example.com"]) == [
            "yaml@example.com"
        ]

    def test_nothing_configured_resolves_to_nothing(self):
        assert resolve_destinations("email") == []

    def test_a_channel_without_an_env_var_ignores_the_environment(self, monkeypatch):
        monkeypatch.setenv("EMAIL_TO", "env@example.com")
        assert resolve_destinations("console", configured=["x"]) == ["x"]


class TestDotenvContract:
    """`.env` must never outrank the process environment.

    Every user shares this checkout, so the one `.env` on disk carries the
    machine owner's destination.  ``python-dotenv`` only leaves the caller's
    value alone because ``override`` defaults to ``False``; switching to
    ``load_dotenv(override=True)`` would redirect every user's alerts to that
    shared address.  These tests fail the moment someone does.
    """

    def test_the_process_environment_survives_loading_dotenv(self, tmp_path, monkeypatch):
        (tmp_path / ".env").write_text(
            "EMAIL_TO=owner-of-the-vm@example.com\nWHATSAPP_TO=+570000000000\n",
            encoding="utf-8",
        )
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("EMAIL_TO", "user@example.com")
        monkeypatch.setenv("WHATSAPP_TO", "+573001234567")

        cli.load_env_file()

        assert os.environ["EMAIL_TO"] == "user@example.com"
        assert os.environ["WHATSAPP_TO"] == "+573001234567"
        assert resolve_destinations("email") == ["user@example.com"]

    def test_dotenv_still_supplies_a_destination_nobody_injected(self, tmp_path, monkeypatch):
        """Single-user installs keep working: the file is a fallback, not a
        rule that got disabled."""
        (tmp_path / ".env").write_text("EMAIL_TO=me@example.com\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        cli.load_env_file()

        assert resolve_destinations("email") == ["me@example.com"]

    def test_a_missing_dotenv_is_not_an_error(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        cli.load_env_file()
        assert resolve_destinations("email") == []


# --------------------------------------------------------------------------
# End to end through the CLI and the runner
# --------------------------------------------------------------------------


def build_runner(config: Config) -> Runner:
    return Runner(config, state=NullStateStore(), http=None)


class TestRunnerDestinations:
    def test_the_flag_addresses_the_notifier(self, monkeypatch):
        monkeypatch.setenv("EMAIL_TO", "env@example.com")
        config = Config(
            notify=NotifyConfig(override_to={"email": ["flag@example.com"]}),
        )
        notifier = build_runner(config)._notifier(NotifyTarget("email"))
        assert notifier.recipients == ["flag@example.com"]

    def test_a_watch_can_address_its_own_channel(self):
        notifier = build_runner(Config())._notifier(NotifyTarget("email", ("watch@example.com",)))
        assert notifier.recipients == ["watch@example.com"]

    def test_the_environment_still_addresses_an_unpinned_channel(self, monkeypatch):
        monkeypatch.setenv("EMAIL_TO", "env@example.com")
        notifier = build_runner(Config())._notifier(NotifyTarget("email"))
        assert notifier.recipients == ["env@example.com"]

    def test_two_destinations_get_two_notifiers(self):
        """One shared notifier would send both users the union of the hits."""
        runner = build_runner(Config())
        first = runner._notifier(NotifyTarget("email", ("a@example.com",)))
        second = runner._notifier(NotifyTarget("email", ("b@example.com",)))
        assert first is not second
        assert first.recipients == ["a@example.com"]
        assert second.recipients == ["b@example.com"]

    def test_the_same_destination_shares_one_notifier(self):
        """Otherwise the per-run message cap would be counted twice."""
        runner = build_runner(Config())
        target = NotifyTarget("email", ("a@example.com",))
        assert runner._notifier(target) is runner._notifier(target)

    def test_dry_run_never_addresses_a_real_channel(self):
        runner = Runner(Config(), state=NullStateStore(), http=None, dry_run=True)
        notifier = runner._notifier(NotifyTarget("email", ("a@example.com",)))
        assert notifier.name == "console"


class TestCliWiring:
    def test_notify_to_reaches_the_config(self, tmp_path):
        path = write_config(tmp_path, {"watches": [{"name": "a", "match": ["a"]}]})
        args = cli.build_parser().parse_args(
            ["--watches", str(path), "--notify-to", "me@example.com", "run"]
        )
        config = cli._load(args)
        assert config.notify.override_to == {"email": ["me@example.com"]}

    def test_notify_to_is_repeatable(self, tmp_path):
        path = write_config(tmp_path, {"watches": [{"name": "a", "match": ["a"]}]})
        args = cli.build_parser().parse_args(
            [
                "--watches",
                str(path),
                "--notify-to",
                "me@example.com",
                "--notify-to",
                "+573001234567",
                "run",
            ]
        )
        config = cli._load(args)
        assert config.notify.override_to == {
            "email": ["me@example.com"],
            "whatsapp": ["+573001234567"],
        }

    def test_it_is_a_global_flag(self, tmp_path):
        """The scheduler puts every option before the subcommand; parsing it
        only after `run` would abort argparse."""
        path = write_config(tmp_path, {"watches": [{"name": "a", "match": ["a"]}]})
        args = cli.build_parser().parse_args(
            ["--watches", str(path), "--notify-to", "me@example.com", "stores"]
        )
        assert args.notify_to == ["me@example.com"]

    def test_no_flag_leaves_the_environment_in_charge(self, tmp_path, monkeypatch):
        monkeypatch.setenv("EMAIL_TO", "env@example.com")
        path = write_config(tmp_path, {"watches": [{"name": "a", "match": ["a"]}]})
        args = cli.build_parser().parse_args(["--watches", str(path), "run"])
        config = cli._load(args)
        assert config.notify.override_to == {}
        notifier = build_runner(config)._notifier(NotifyTarget("email"))
        assert notifier.recipients == ["env@example.com"]


class TestPerWatchRouting:
    @pytest.mark.asyncio
    async def test_each_watch_reaches_its_own_destination(self, monkeypatch):
        """Two watches, two inboxes: the hits must not be merged into one
        message sent to both."""
        from decimal import Decimal

        from stockwatcher.models import Hit

        sent: dict[tuple[str, ...], list[str]] = {}

        class CaptureNotifier:
            def __init__(self, options):
                self.recipients = tuple(options.get("to") or ())
                self.messages_sent = 0

            async def send(self, alert):
                sent.setdefault(self.recipients, []).extend(h.watch_name for h in alert.hits)
                self.messages_sent += 1

            async def aclose(self):
                return None

        monkeypatch.setattr(
            "stockwatcher.runner.build_notifier", lambda channel, options: CaptureNotifier(options)
        )

        watches = [
            Watch(name="a", match=["a"], notify=[NotifyTarget("email", ("a@example.com",))]),
            Watch(name="b", match=["b"], notify=[NotifyTarget("email", ("b@example.com",))]),
        ]
        hits = [
            Hit(
                watch_name=name,
                store_host="k.com",
                store_name="Kith",
                provider="shopify",
                product_title="p",
                product_url="https://k.com/p",
                variant_label="10",
                price=Decimal("100"),
                currency="USD",
            )
            for name in ("a", "b")
        ]

        await build_runner(Config(watches=watches))._notify(hits, watches)

        assert sent == {("a@example.com",): ["a"], ("b@example.com",): ["b"]}
