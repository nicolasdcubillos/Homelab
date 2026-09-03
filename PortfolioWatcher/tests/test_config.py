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


def test_load_config_requires_holdings(tmp_path):
    path = _write(tmp_path, "analysis_interval_days: 7\nholdings: []\n")
    with pytest.raises(ConfigError):
        load_config(path)


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
