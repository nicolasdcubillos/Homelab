"""YAML configuration loading for the portfolio and runtime settings."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class ConfigError(ValueError):
    """Raised when the YAML config is malformed."""


@dataclass
class Holding:
    """One active position in the portfolio."""

    ticker: str
    quantity: float
    avg_cost: float
    sector_hint: str = "unknown"

    @property
    def cost_basis(self) -> float:
        return self.quantity * self.avg_cost


@dataclass
class ClosedPosition:
    """Historical reference only — excluded from active analysis."""

    ticker: str
    note: str = ""


@dataclass
class RiskProfile:
    horizon: str = "long_term"
    tolerance: str = "moderate"
    notes: str = ""


@dataclass
class AzureOpenAIConfig:
    endpoint: str = ""
    api_key: str = ""
    api_version: str = "2024-10-21"
    triage_deployment: str = "gpt-5-6-luna"
    analysis_deployment: str = "gpt-5-6-sol"

    @property
    def is_configured(self) -> bool:
        return bool(self.endpoint and self.api_key)


@dataclass
class PortfolioConfig:
    analysis_interval_days: int = 7
    risk_profile: RiskProfile = field(default_factory=RiskProfile)
    holdings: list[Holding] = field(default_factory=list)
    closed_positions: list[ClosedPosition] = field(default_factory=list)
    state_path: str = "data/portfoliowatcher.db"
    azure_openai: AzureOpenAIConfig = field(default_factory=AzureOpenAIConfig)
    notifiers: list[str] = field(default_factory=lambda: ["whatsapp"])
    sec_edgar_user_agent: str = ""

    def tickers(self) -> list[str]:
        return [h.ticker for h in self.holdings]


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        raise ConfigError(f"config file not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must contain a YAML mapping at the top level")
    return data


def _holding_from_dict(raw: Any) -> Holding:
    if not isinstance(raw, dict):
        raise ConfigError(f"each holding must be a mapping, got {raw!r}")
    ticker = raw.get("ticker")
    if not ticker:
        raise ConfigError("every holding needs a 'ticker'")
    try:
        quantity = float(raw.get("quantity", 0))
        avg_cost = float(raw.get("avg_cost", 0))
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"holding {ticker!r} has a non-numeric quantity/avg_cost") from exc
    return Holding(
        ticker=str(ticker).upper(),
        quantity=quantity,
        avg_cost=avg_cost,
        sector_hint=str(raw.get("sector_hint") or "unknown"),
    )


def _closed_from_dict(raw: Any) -> ClosedPosition:
    if not isinstance(raw, dict):
        raise ConfigError(f"each closed_position must be a mapping, got {raw!r}")
    ticker = raw.get("ticker")
    if not ticker:
        raise ConfigError("every closed_position needs a 'ticker'")
    return ClosedPosition(ticker=str(ticker).upper(), note=str(raw.get("note") or ""))


def _risk_profile_from_dict(raw: Any) -> RiskProfile:
    if not raw:
        return RiskProfile()
    if not isinstance(raw, dict):
        raise ConfigError(f"'risk_profile' must be a mapping, got {raw!r}")
    return RiskProfile(
        horizon=str(raw.get("horizon") or "long_term"),
        tolerance=str(raw.get("tolerance") or "moderate"),
        notes=str(raw.get("notes") or ""),
    )


def load_config(path: str | os.PathLike[str] = "config/portfolio.yaml") -> PortfolioConfig:
    """Load ``portfolio.yaml`` and apply environment variable overrides."""
    data = _read_yaml(Path(path))

    raw_holdings = data.get("holdings") or []
    if not raw_holdings:
        raise ConfigError(f"{path} defines no holdings")
    holdings = [_holding_from_dict(h) for h in raw_holdings]

    closed = [_closed_from_dict(c) for c in data.get("closed_positions") or []]

    interval = data.get("analysis_interval_days", 7)
    try:
        interval = int(interval)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"'analysis_interval_days' must be an integer, got {interval!r}") from exc
    if interval <= 0:
        raise ConfigError("'analysis_interval_days' must be positive")

    config = PortfolioConfig(
        analysis_interval_days=interval,
        risk_profile=_risk_profile_from_dict(data.get("risk_profile")),
        holdings=holdings,
        closed_positions=closed,
    )
    return apply_env_overrides(config)


def apply_env_overrides(config: PortfolioConfig) -> PortfolioConfig:
    """Let environment variables win over the YAML defaults, mirroring StockWatcher."""
    state_path = os.getenv("PORTFOLIOWATCHER_STATE_PATH")
    if state_path:
        config.state_path = state_path

    config.azure_openai = AzureOpenAIConfig(
        endpoint=os.getenv("AZURE_OPENAI_ENDPOINT", ""),
        api_key=os.getenv("AZURE_OPENAI_API_KEY", ""),
        api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21"),
        triage_deployment=os.getenv("AZURE_OPENAI_TRIAGE_DEPLOYMENT", "gpt-5-6-luna"),
        analysis_deployment=os.getenv("AZURE_OPENAI_ANALYSIS_DEPLOYMENT", "gpt-5-6-sol"),
    )

    notifiers = os.getenv("PORTFOLIOWATCHER_NOTIFIERS")
    if notifiers:
        config.notifiers = [n.strip() for n in notifiers.split(",") if n.strip()]

    config.sec_edgar_user_agent = os.getenv("SEC_EDGAR_USER_AGENT", "")

    return config
