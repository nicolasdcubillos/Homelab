from __future__ import annotations

import textwrap

import pytest

from portfoliowatcher.config import ConfigError, load_config


def _write(tmp_path, content: str, name: str = "portfolio.yaml"):
    path = tmp_path / name
    path.write_text(textwrap.dedent(content))
    return path


def test_load_config_parses_holdings_and_defaults(tmp_path, monkeypatch):
    monkeypatch.delenv("PORTFOLIOWATCHER_STATE_PATH", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)
    monkeypatch.delenv("PORTFOLIOWATCHER_NOTIFIERS", raising=False)
    path = _write(
        tmp_path,
        """
        analysis_interval_days: 7
        risk_profile:
          horizon: long_term
          tolerance: moderate
        holdings:
          - ticker: aapl
            quantity: 10
            avg_cost: 150.5
            sector_hint: technology
          - ticker: voo
            quantity: 5
            avg_cost: 400
        closed_positions:
          - ticker: adbe
            note: closed
        """,
    )
    config = load_config(path)
    assert config.analysis_interval_days == 7
    assert config.risk_profile.tolerance == "moderate"
    assert [h.ticker for h in config.holdings] == ["AAPL", "VOO"]
    assert config.holdings[0].sector_hint == "technology"
    assert config.holdings[1].sector_hint == "unknown"
    assert config.tickers() == ["AAPL", "VOO"]
    assert [c.ticker for c in config.closed_positions] == ["ADBE"]
    # default state path (env not set)
    assert config.state_path == "data/portfoliowatcher.db"


def test_load_config_allows_empty_holdings(tmp_path, caplog):
    """Finding #5: a brand-new user with no positions must not crash the run."""
    path = _write(tmp_path, "analysis_interval_days: 7\nholdings: []\n")
    config = load_config(path)
    assert config.holdings == []
    assert config.tickers() == []
    assert "defines no holdings" in caplog.text


def test_load_config_allows_missing_holdings_key(tmp_path):
    path = _write(tmp_path, "analysis_interval_days: 7\n")
    assert load_config(path).holdings == []


def test_load_config_rejects_bad_interval(tmp_path):
    path = _write(
        tmp_path,
        """
        analysis_interval_days: -1
        holdings:
          - ticker: AAPL
            quantity: 1
            avg_cost: 100
        """,
    )
    with pytest.raises(ConfigError):
        load_config(path)


def test_load_config_missing_file(tmp_path):
    with pytest.raises(ConfigError):
        load_config(tmp_path / "missing.yaml")


def test_env_overrides_state_path_and_azure(tmp_path, monkeypatch):
    path = _write(
        tmp_path,
        """
        holdings:
          - ticker: AAPL
            quantity: 1
            avg_cost: 100
        """,
    )
    monkeypatch.setenv("PORTFOLIOWATCHER_STATE_PATH", "custom/path.db")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "secret")
    monkeypatch.setenv("PORTFOLIOWATCHER_NOTIFIERS", "whatsapp, telegram")

    config = load_config(path)
    assert config.state_path == "custom/path.db"
    assert config.azure_openai.is_configured
    assert config.notifiers == ["whatsapp", "telegram"]


def test_load_config_reads_notifiers_and_state_path_from_yaml(tmp_path, monkeypatch):
    """Finding #4: the YAML is the base layer for both keys."""
    monkeypatch.delenv("PORTFOLIOWATCHER_STATE_PATH", raising=False)
    monkeypatch.delenv("PORTFOLIOWATCHER_NOTIFIERS", raising=False)
    path = _write(
        tmp_path,
        """
        state_path: yaml/state.db
        notifiers:
          - email
          - whatsapp
        holdings:
          - ticker: AAPL
            quantity: 1
            avg_cost: 100
        """,
    )
    config = load_config(path)
    assert config.state_path == "yaml/state.db"
    assert config.notifiers == ["email", "whatsapp"]


def test_yaml_notifiers_accept_a_comma_separated_string(tmp_path, monkeypatch):
    monkeypatch.delenv("PORTFOLIOWATCHER_NOTIFIERS", raising=False)
    path = _write(
        tmp_path,
        """
        notifiers: email, whatsapp
        holdings:
          - ticker: AAPL
            quantity: 1
            avg_cost: 100
        """,
    )
    assert load_config(path).notifiers == ["email", "whatsapp"]


def test_env_overrides_win_over_the_yaml_values(tmp_path, monkeypatch):
    path = _write(
        tmp_path,
        """
        state_path: yaml/state.db
        notifiers: [whatsapp]
        holdings:
          - ticker: AAPL
            quantity: 1
            avg_cost: 100
        """,
    )
    monkeypatch.setenv("PORTFOLIOWATCHER_STATE_PATH", "env/state.db")
    monkeypatch.setenv("PORTFOLIOWATCHER_NOTIFIERS", "email")

    config = load_config(path)
    assert config.state_path == "env/state.db"
    assert config.notifiers == ["email"]


def test_yaml_notifiers_must_be_a_list_or_string(tmp_path):
    path = _write(
        tmp_path,
        """
        notifiers:
          channel: email
        holdings:
          - ticker: AAPL
            quantity: 1
            avg_cost: 100
        """,
    )
    with pytest.raises(ConfigError):
        load_config(path)


def test_interval_override_env_replaces_the_yaml_interval(tmp_path, monkeypatch):
    """Finding #3: ``analyze --interval-days`` writes this variable."""
    path = _write(
        tmp_path,
        """
        analysis_interval_days: 7
        holdings:
          - ticker: AAPL
            quantity: 1
            avg_cost: 100
        """,
    )
    monkeypatch.setenv("PORTFOLIOWATCHER_INTERVAL_OVERRIDE", "21")
    assert load_config(path).analysis_interval_days == 21


@pytest.mark.parametrize("value", ["0", "-3", "not-a-number"])
def test_interval_override_env_is_validated(tmp_path, monkeypatch, value):
    path = _write(
        tmp_path,
        """
        holdings:
          - ticker: AAPL
            quantity: 1
            avg_cost: 100
        """,
    )
    monkeypatch.setenv("PORTFOLIOWATCHER_INTERVAL_OVERRIDE", value)
    with pytest.raises(ConfigError):
        load_config(path)


def test_interval_override_env_absent_keeps_the_yaml_value(tmp_path, monkeypatch):
    path = _write(
        tmp_path,
        """
        analysis_interval_days: 14
        holdings:
          - ticker: AAPL
            quantity: 1
            avg_cost: 100
        """,
    )
    monkeypatch.delenv("PORTFOLIOWATCHER_INTERVAL_OVERRIDE", raising=False)
    assert load_config(path).analysis_interval_days == 14
