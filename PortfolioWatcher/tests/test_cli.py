from __future__ import annotations

import ast
import os
import textwrap
from pathlib import Path

import pytest
from dotenv import load_dotenv

from portfoliowatcher import cli
from portfoliowatcher.config import PortfolioConfig
from portfoliowatcher.notifier import Notifier, register_notifier


def _write_config(tmp_path, holdings: str = "") -> Path:
    path = tmp_path / "portfolio.yaml"
    path.write_text(
        textwrap.dedent(
            f"""
            analysis_interval_days: 7
            holdings:{holdings}
            """
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def no_dotenv(monkeypatch):
    """Keep the developer's real .env out of CLI tests."""
    monkeypatch.setattr(cli, "load_dotenv", lambda *args, **kwargs: None)


class RecordingNotifier(Notifier):
    """Captures what the CLI resolved as the destination, sends nothing."""

    name = "recording"
    last: RecordingNotifier | None = None

    def __init__(self, options: dict | None = None) -> None:
        options = options or {}
        self.recipients = options.get("to") or []
        self.messages: list[str] = []
        RecordingNotifier.last = self

    async def send(self, message: str) -> None:
        self.messages.append(message)


register_notifier("recording", lambda options: RecordingNotifier(options))


# ------------------------------------- notification-destination contract (#2)


def test_process_env_wins_over_dotenv_file(tmp_path, monkeypatch):
    """Regression pin: this is what makes one-process-per-user safe.

    ``cli._load_all`` calls ``load_dotenv()`` with its default
    ``override=False``. A caller that injects the destination through ``env=``
    must beat whatever the shared ``.env`` on disk says — otherwise every user
    would get their alerts delivered to the VM owner's number/address.
    """
    env_file = tmp_path / ".env"
    env_file.write_text(
        "WHATSAPP_TO=+570000000000\nEMAIL_TO=owner-of-the-vm@example.com\n", encoding="utf-8"
    )
    monkeypatch.setenv("WHATSAPP_TO", "+573001112233")
    monkeypatch.setenv("EMAIL_TO", "user@example.com")

    load_dotenv(env_file)

    assert os.environ["WHATSAPP_TO"] == "+573001112233"
    assert os.environ["EMAIL_TO"] == "user@example.com"


def test_cli_never_enables_dotenv_override():
    """``load_dotenv(override=True)`` would invert the precedence above."""
    tree = ast.parse(Path(cli.__file__).read_text(encoding="utf-8"))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "load_dotenv"
    ]
    assert calls, "cli.py must still load the .env file"
    for call in calls:
        overrides = [kw for kw in call.keywords if kw.arg == "override"]
        assert not overrides, "load_dotenv must keep its default override=False"


def test_dotenv_fills_only_the_gaps(tmp_path, monkeypatch):
    """The shared .env still supplies values the caller did not inject."""
    env_file = tmp_path / ".env"
    env_file.write_text("ACS_CONNECTION_STRING=from-file\n", encoding="utf-8")
    monkeypatch.delenv("ACS_CONNECTION_STRING", raising=False)

    load_dotenv(env_file)

    assert os.environ["ACS_CONNECTION_STRING"] == "from-file"


# ------------------------------------------------------------ --notify-to (#2)


def test_parser_accepts_notify_to():
    args = cli.build_parser().parse_args(["--notify-to", "user@example.com", "daily"])
    assert args.notify_to == "user@example.com"


def test_main_forwards_notify_to_as_a_list(monkeypatch):
    captured = {}

    def fake_run_daily(config_path, *, dry_run, notify_to=None):
        captured["notify_to"] = notify_to
        return ""

    monkeypatch.setattr(cli, "run_daily", fake_run_daily)
    assert cli.main(["--notify-to", "a@example.com, b@example.com", "daily"]) == 0
    assert captured["notify_to"] == ["a@example.com", "b@example.com"]


def test_main_without_notify_to_passes_an_empty_list(monkeypatch):
    captured = {}

    def fake_run_weekly(config_path, *, dry_run, force=False, notify_to=None):
        captured["notify_to"] = notify_to
        return ""

    monkeypatch.setattr(cli, "run_weekly", fake_run_weekly)
    assert cli.main(["weekly"]) == 0
    assert captured["notify_to"] == []


async def test_dispatch_prefers_notify_to_over_environment(monkeypatch):
    monkeypatch.setenv("EMAIL_TO", "owner-of-the-vm@example.com")
    config = PortfolioConfig(notifiers=["recording"])

    await cli._dispatch(config, "informe", dry_run=False, notify_to=["user@example.com"])

    assert RecordingNotifier.last.recipients == ["user@example.com"]
    assert RecordingNotifier.last.messages == ["informe"]


async def test_dispatch_without_notify_to_leaves_resolution_to_the_notifier():
    config = PortfolioConfig(notifiers=["recording"])

    await cli._dispatch(config, "informe", dry_run=False, notify_to=None)

    assert RecordingNotifier.last.recipients == []


async def test_dispatch_dry_run_sends_nothing(capsys):
    config = PortfolioConfig(notifiers=["recording"])
    RecordingNotifier.last = None

    await cli._dispatch(config, "informe", dry_run=True, notify_to=["user@example.com"])

    assert RecordingNotifier.last is None
    assert "informe" in capsys.readouterr().out


# --------------------------------------------- analyze --interval-days (#3)


def test_analyze_interval_days_reaches_the_config(tmp_path, monkeypatch, no_dotenv):
    # ``main`` writes os.environ directly, so seed the variable through
    # monkeypatch to guarantee it is removed again at teardown.
    monkeypatch.setenv("PORTFOLIOWATCHER_INTERVAL_OVERRIDE", "7")
    config_path = _write_config(
        tmp_path,
        holdings="\n              - ticker: AAPL\n                quantity: 1\n                avg_cost: 100",
    )
    seen = {}

    def fake_run_weekly(path, *, dry_run, force=False, notify_to=None):
        seen["interval"] = cli.load_config(path).analysis_interval_days
        return ""

    monkeypatch.setattr(cli, "run_weekly", fake_run_weekly)
    assert cli.main(["--config", str(config_path), "analyze", "--interval-days", "21"]) == 0
    assert seen["interval"] == 21


# ------------------------------------------------- empty holdings exit (#5)


def test_run_daily_exits_cleanly_without_holdings(tmp_path, caplog, no_dotenv):
    config_path = _write_config(tmp_path, holdings=" []")
    assert cli.run_daily(str(config_path), dry_run=True) == ""
    assert "no holdings configured" in caplog.text


def test_run_weekly_exits_cleanly_without_holdings(tmp_path, caplog, no_dotenv):
    config_path = _write_config(tmp_path, holdings=" []")
    assert cli.run_weekly(str(config_path), dry_run=True, force=True) == ""
    assert "no holdings configured" in caplog.text


def test_main_returns_zero_for_an_empty_portfolio(tmp_path, no_dotenv):
    config_path = _write_config(tmp_path, holdings=" []")
    assert cli.main(["--config", str(config_path), "--dry-run", "daily"]) == 0
