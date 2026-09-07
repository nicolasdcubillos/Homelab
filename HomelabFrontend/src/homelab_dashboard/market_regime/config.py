"""Versioned, explicit heuristic rules; these are not calibrated probabilities."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

CATEGORIES = ("MACRO", "RATES", "FX", "VOLATILITY", "CREDIT", "EQUITY", "CROSS_ASSET")
HORIZONS = ("SHORT", "MEDIUM", "LONG")
MACRO_SERIES = (
    "CPI",
    "CORE_CPI",
    "NFP",
    "UNEMPLOYMENT",
    "AHE",
    "JOLTS",
    "PCE",
    "CORE_PCE",
    "GDP",
    "FED_FUNDS",
    "FED_BALANCE",
)
MARKET_SERIES = (
    "US02Y",
    "US10Y",
    "USDJPY",
    "SPX",
    "ES",
    "NDX",
    "NQ",
    "RUSSELL",
    "DOW",
    "DXY",
    "VIX",
    "MOVE",
    "HY_OAS",
    "IG_OAS",
)


class RuleModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class HorizonConfig(RuleModel):
    target_bars: int = Field(ge=1, le=36)
    bar_frequency: Literal["daily", "weekly", "monthly"]
    structure_bars: int = Field(ge=8, le=120)
    macro_readings: int = Field(ge=3, le=24)
    gdp_readings: int = Field(ge=3, le=12)
    change_bars: int = Field(ge=2, le=24)
    weights: dict[str, float]

    @model_validator(mode="after")
    def valid_weights(self):
        if set(self.weights) != set(CATEGORIES):
            raise ValueError("Se requieren exactamente siete categorias.")
        if any(not 0 < x <= 100 for x in self.weights.values()):
            raise ValueError("Pesos deben ser positivos y finitos.")
        if abs(sum(self.weights.values()) - 100) > 1e-8:
            raise ValueError("Los siete pesos deben sumar 100.")
        if self.weights["CROSS_ASSET"] > 5:
            raise ValueError("Cross-asset no puede aportar mas de cinco puntos.")
        if self.weights["MACRO"] < max(self.weights.values()):
            raise ValueError("Macro/politica debe ser la categoria superior.")
        if self.change_bars >= self.structure_bars:
            raise ValueError("La referencia de cambio debe caber en la ventana.")
        return self


class SeriesRule(RuleModel):
    units: list[str] = Field(min_length=1)
    max_age_days: int = Field(ge=1, le=400)
    positive: bool = True


class Rules(RuleModel):
    pivot_side: int = Field(default=2, ge=2, le=5)
    history_min: int = Field(default=252, ge=252, le=756)
    history_max: int = Field(default=756, ge=252, le=2520)
    volatility_quantiles: list[float] = Field(default=[10, 75, 90, 97.5])
    rapid_quantile: float = Field(default=90, ge=75, le=99)
    credit_stress_quantile: float = Field(default=90, ge=75, le=99)
    persistence_bars: int = Field(default=3, ge=3, le=12)
    direction_epsilon: float = Field(default=1e-9, ge=0, le=0.01)
    growth_zero: float = 0
    inflation_target: float = Field(default=2, gt=0, le=10)
    inflation_hot: float = Field(default=3, gt=0, le=20)
    employment_weights: dict[str, float] = Field(
        default={"NFP": 0.5, "UNEMPLOYMENT": 0.3, "JOLTS": 0.2}
    )
    inflation_weights: dict[str, float] = Field(
        default={"CPI": 0.15, "CORE_CPI": 0.25, "PCE": 0.15, "CORE_PCE": 0.3, "AHE": 0.15}
    )
    policy_weights: dict[str, float] = Field(default={"FED_FUNDS": 0.7, "FED_BALANCE": 0.3})
    macro_weights: dict[str, float] = Field(
        default={"context": 0.7, "employment": 0.1, "growth": 0.1, "policy": 0.1}
    )
    pair_weights: dict[str, float] = Field(default={"first": 0.5, "second": 0.5})
    equity_weights: dict[str, float] = Field(
        default={"SPX": 0.3, "NDX": 0.3, "RUSSELL": 0.2, "DOW": 0.2}
    )
    context_values: dict[str, float] = Field(
        default={
            "RESILIENTE_DESINFLACION": 1,
            "INFLACION_ENDURECIMIENTO": -1,
            "DETERIORO_ACTIVIDAD": -1,
            "MIXTO": 0,
        }
    )
    rates_values: dict[str, float] = Field(
        default={
            "resilient_rising": 0.5,
            "resilient_falling_short": 1,
            "inflation_rising": -1,
            "deterioration_falling": -1,
            "deterioration_other": -0.5,
            "unresolved": 0,
        }
    )
    fx_values: dict[str, float] = Field(
        default={
            "confirmed_stress": -1,
            "inflation_strong_dollar": -0.5,
            "resilient_easing_or_carry": 0.5,
            "unresolved": 0,
        }
    )
    volatility_values: dict[str, float] = Field(
        default={
            "extreme": -1,
            "stress": -1,
            "elevated": -0.5,
            "normal_falling_persistent": 0.5,
            "rapid_increase": -0.5,
            "unresolved": 0,
        }
    )
    verified_sessions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def coherent_rules(self):
        import datetime as dt

        groups = {
            "employment_weights": {"NFP", "UNEMPLOYMENT", "JOLTS"},
            "inflation_weights": {"CPI", "CORE_CPI", "PCE", "CORE_PCE", "AHE"},
            "policy_weights": {"FED_FUNDS", "FED_BALANCE"},
            "macro_weights": {"context", "employment", "growth", "policy"},
            "pair_weights": {"first", "second"},
            "equity_weights": {"SPX", "NDX", "RUSSELL", "DOW"},
        }
        for name, keys in groups.items():
            weights = getattr(self, name)
            if (
                set(weights) != keys
                or any(not 0 < x <= 1 for x in weights.values())
                or abs(sum(weights.values()) - 1) > 1e-8
            ):
                raise ValueError(f"{name}: claves exactas y pesos positivos que sumen uno.")
        if (
            self.history_max < self.history_min
            or self.volatility_quantiles != sorted(set(self.volatility_quantiles))
            or len(self.volatility_quantiles) != 4
            or not all(0 < x < 100 for x in self.volatility_quantiles)
        ):
            raise ValueError("Historia/cuantiles inconsistentes.")
        if self.inflation_target >= self.inflation_hot:
            raise ValueError("El umbral alto debe superar la meta de inflacion.")
        if set(self.context_values) != {
            "RESILIENTE_DESINFLACION",
            "INFLACION_ENDURECIMIENTO",
            "DETERIORO_ACTIVIDAD",
            "MIXTO",
        } or any(x not in (-1, -0.5, 0, 0.5, 1) for x in self.context_values.values()):
            raise ValueError("Tabla contextual incompleta o fuera de escala.")
        tables = {
            "rates_values": {
                "resilient_rising",
                "resilient_falling_short",
                "inflation_rising",
                "deterioration_falling",
                "deterioration_other",
                "unresolved",
            },
            "fx_values": {
                "confirmed_stress",
                "inflation_strong_dollar",
                "resilient_easing_or_carry",
                "unresolved",
            },
            "volatility_values": {
                "extreme",
                "stress",
                "elevated",
                "normal_falling_persistent",
                "rapid_increase",
                "unresolved",
            },
        }
        for name, keys in tables.items():
            table = getattr(self, name)
            if set(table) != keys or any(x not in (-1, -0.5, 0, 0.5, 1) for x in table.values()):
                raise ValueError(f"{name}: tabla incompleta o fuera de escala discreta.")
        if self.verified_sessions != sorted(set(self.verified_sessions)):
            raise ValueError("Las sesiones verificadas deben ser unicas y cronologicas.")
        for value in self.verified_sessions:
            if dt.date.fromisoformat(value).isoformat() != value:
                raise ValueError("Sesion debe ser YYYY-MM-DD.")
        return self


class TransitionConfig(RuleModel):
    entry_on: float = Field(default=65, ge=0, le=100)
    entry_off: float = Field(default=35, ge=0, le=100)
    exit_on: float = Field(default=55, ge=0, le=100)
    exit_off: float = Field(default=45, ge=0, le=100)
    aligned_categories: int = Field(default=3, ge=3, le=6)
    persistence: dict[str, int] = Field(default={"SHORT": 3, "MEDIUM": 2, "LONG": 2})

    @model_validator(mode="after")
    def ordered(self):
        if not self.entry_off < self.exit_off < self.exit_on < self.entry_on:
            raise ValueError("Umbrales de histeresis fuera de orden.")
        if set(self.persistence) != set(HORIZONS) or any(
            type(x) is not int or x < 2 for x in self.persistence.values()
        ):
            raise ValueError("Persistencia requerida por horizonte.")
        return self


class ValidationConfig(RuleModel):
    train_min: int = Field(default=30, ge=5, le=1000)
    test_size: int = Field(default=20, ge=2, le=1000)
    min_folds: int = Field(default=3, ge=3, le=100)
    min_nonoverlapping: int = Field(default=30, ge=30, le=1000)
    sample_stride: int = Field(default=5, ge=1, le=100)
    embargo_bars: dict[str, int] = Field(default={"SHORT": 12, "MEDIUM": 8, "LONG": 12})
    return_favorable_quantile: float = Field(default=0.6, gt=0, lt=1)
    return_adverse_quantile: float = Field(default=0.2, gt=0, lt=1)
    drawdown_favorable_quantile: float = Field(default=0.5, gt=0, lt=1)
    drawdown_adverse_quantile: float = Field(default=0.8, gt=0, lt=1)

    @model_validator(mode="after")
    def valid_validation(self):
        if set(self.embargo_bars) != set(HORIZONS) or any(
            type(x) is not int or x < 1 for x in self.embargo_bars.values()
        ):
            raise ValueError("Embargo requerido por horizonte.")
        if (
            self.return_adverse_quantile >= self.return_favorable_quantile
            or self.drawdown_favorable_quantile >= self.drawdown_adverse_quantile
        ):
            raise ValueError("Cuantiles de etiquetas fuera de orden.")
        return self


class EngineConfig(RuleModel):
    model_version: str = Field(min_length=1, max_length=100)
    horizons: dict[str, HorizonConfig]
    required_series: list[str]
    series: dict[str, SeriesRule]
    rules: Rules = Field(default_factory=Rules)
    transition: TransitionConfig = Field(default_factory=TransitionConfig)
    validation: ValidationConfig = Field(default_factory=ValidationConfig)

    @model_validator(mode="after")
    def complete(self):
        if set(self.horizons) != set(HORIZONS):
            raise ValueError("Se requieren SHORT, MEDIUM y LONG independientes.")
        for horizon, frequency in zip(HORIZONS, ("daily", "weekly", "monthly")):
            if self.horizons[horizon].bar_frequency != frequency:
                raise ValueError("SHORT diario, MEDIUM semanal, LONG mensual.")
            if self.validation.embargo_bars[horizon] < self.horizons[horizon].target_bars:
                raise ValueError("El embargo no puede ser menor al horizonte objetivo.")
        core = set(MACRO_SERIES + MARKET_SERIES)
        if len(set(self.required_series)) != len(self.required_series):
            raise ValueError("Requisitos duplicados.")
        if not core.issubset(self.required_series):
            raise ValueError("No se pueden eliminar requisitos centrales del modelo.")
        if not set(self.required_series).issubset(self.series):
            raise ValueError("Faltan reglas de unidad/frescura.")
        return self


def _defaults() -> dict:
    series = {
        name: {"units": ["index", "points", "index points"], "max_age_days": 5, "positive": True}
        for name in MARKET_SERIES
    }
    for name in ("US02Y", "US10Y"):
        series[name] = {"units": ["percent", "%"], "max_age_days": 7, "positive": False}
    series["USDJPY"] = {
        "units": ["JPY/USD", "JPY per USD"],
        "max_age_days": 14,
        "positive": True,
    }
    for name in ("HY_OAS", "IG_OAS"):
        series[name] = {
            "units": ["percent", "%", "basis_points", "bps"],
            "max_age_days": 5,
            "positive": True,
        }
    for name in MACRO_SERIES:
        series[name] = {"units": ["index"], "max_age_days": 75, "positive": True}
    for name in ("CPI", "CORE_CPI"):
        series[name]["units"] += ["index 1982-84=100"]
    for name in ("PCE", "CORE_PCE"):
        series[name]["units"] += ["index 2017=100"]
        series[name]["max_age_days"] = 95
    series["NFP"]["units"] = ["thousands", "thousands_of_persons", "thousands of persons"]
    series["UNEMPLOYMENT"]["units"] = ["percent", "%"]
    series["AHE"]["units"] = ["USD/hour", "dollars_per_hour", "USD per hour"]
    series["JOLTS"]["units"] = ["thousands", "thousands_of_persons", "thousands of persons"]
    series["JOLTS"]["max_age_days"] = 100
    series["GDP"] = {
        "units": ["percent", "%", "percent_annual_rate", "billions of chained 2017 USD"],
        "max_age_days": 220,
        "positive": False,
    }
    series["FED_FUNDS"] = {
        "units": ["percent", "%"],
        "max_age_days": 7,
        "positive": False,
    }
    series["FED_BALANCE"] = {
        "units": ["millions_USD", "millions_of_dollars", "millions of USD"],
        "max_age_days": 14,
        "positive": True,
    }
    series["NFCI"] = {
        "units": ["index", "standard_deviations"],
        "max_age_days": 21,
        "positive": False,
    }
    horizons = {}
    for name, target, frequency, window, macro, gdp, change, weights in (
        ("SHORT", 12, "daily", 40, 3, 3, 5, (30, 10, 10, 15, 15, 15, 5)),
        ("MEDIUM", 8, "weekly", 26, 6, 4, 4, (40, 10, 10, 10, 15, 10, 5)),
        ("LONG", 12, "monthly", 24, 12, 6, 3, (50, 10, 5, 5, 15, 10, 5)),
    ):
        horizons[name] = {
            "target_bars": target,
            "bar_frequency": frequency,
            "structure_bars": window,
            "macro_readings": macro,
            "gdp_readings": gdp,
            "change_bars": change,
            "weights": dict(zip(CATEGORIES, weights)),
        }
    return EngineConfig(
        model_version="heuristic-v1",
        horizons=horizons,
        required_series=list(MACRO_SERIES + MARKET_SERIES),
        series=series,
    ).model_dump(mode="json")


DEFAULT_CONFIG: dict = _defaults()


def validate_config(value: dict) -> dict:
    """Return an independent, JSON-safe configuration or raise ValidationError."""
    return EngineConfig.model_validate(value).model_dump(mode="json")
