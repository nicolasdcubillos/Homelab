"""Contratos entre ingestion, persistencia, calculo y API del modulo."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Horizon = Literal["SHORT", "MEDIUM", "LONG"]
DataStatus = Literal["SIN_DATOS", "INCOMPLETO", "COMPLETO"]
Regime = Literal["RISK_ON", "RISK_OFF", "NEUTRAL"]
SourceStatus = Literal["DISPONIBLE", "NO_CONFIGURADO", "BLOQUEADO_LICENCIA", "ERROR", "PENDIENTE"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Observation(Contract):
    id: int | None = None
    source_id: str
    series_id: str
    period: str
    value: Decimal
    unit: str
    frequency: Literal["daily", "weekly", "monthly", "quarterly", "event"] = "daily"
    observed_at: dt.datetime
    published_at: dt.datetime | None = None
    available_at: dt.datetime
    ingested_at: dt.datetime | None = None
    vintage: str = "unknown"
    timestamp_precision: Literal["exact", "date", "observed"] = "observed"
    source_url: str
    raw_hash: str = ""
    quality: Literal["OK", "CUARENTENA"] = "OK"

    @field_validator("value")
    @classmethod
    def finite_value(cls, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("El valor debe ser finito.")
        return value

    @field_validator("observed_at", "published_at", "available_at", "ingested_at")
    @classmethod
    def aware_timestamp(cls, value: dt.datetime | None) -> dt.datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("La fecha debe incluir zona horaria.")
        return value.astimezone(dt.timezone.utc) if value is not None else None


class SourceInfo(Contract):
    id: str
    name: str
    url: str
    terms_url: str
    status: SourceStatus = "PENDIENTE"
    detail: str = ""
    series: list[str] = Field(default_factory=list)
    requires_key: bool = False
    restricted: bool = False
    last_success_at: dt.datetime | None = None


class CoverageItem(Contract):
    series_id: str
    name: str
    source_id: str
    required: bool = True
    available: bool = False
    reason: str = ""
    observed_at: dt.datetime | None = None
    published_at: dt.datetime | None = None
    ingested_at: dt.datetime | None = None
    source_url: str = ""


class Evidence(Contract):
    series_id: str
    observation_ids: list[int] = Field(default_factory=list)
    reading: str
    direction: Literal["FAVORABLE", "ADVERSA", "MIXTA", "NO_EVALUABLE"]
    value: float | None = None
    unit: str = ""
    source_url: str = ""
    observed_at: dt.datetime | None = None
    available_at: dt.datetime | None = None


class CategoryResult(Contract):
    category: str
    weight: float
    value: float | None = None
    contribution: float | None = None
    reason: str
    evidence: list[Evidence] = Field(default_factory=list)


class HorizonResult(Contract):
    horizon: Horizon
    data_status: DataStatus
    score: float | None = None
    regime: Regime | None = None
    transition_status: Literal["ESTABLE", "EN_TRANSICION", "NO_EVALUABLE"] = "NO_EVALUABLE"
    previous_regime: Regime | None = None
    confidence: Literal["BAJA", "MEDIA", "ALTA", "NO_EVALUABLE"] = "NO_EVALUABLE"
    calibration_status: Literal["HEURISTICO_NO_VALIDADO"] = "HEURISTICO_NO_VALIDADO"
    categories: list[CategoryResult] = Field(default_factory=list)
    drivers: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    changes: list[str] = Field(default_factory=list)
    would_change: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)


class SnapshotData(Contract):
    as_of: dt.datetime
    model_version: str
    horizons: list[HorizonResult]
    coverage: list[CoverageItem]
    context: str
    mode: Literal["OPERACIONAL", "RECONSTRUCCION"] = "OPERACIONAL"


class ReportSection(Contract):
    number: int
    title: str
    text: str


class ReportData(Contract):
    title: str
    brief: str
    sections: list[ReportSection]
    matrix: list[Evidence]
    html: str
    text: str
    narrative_status: Literal["DESHABILITADO", "ERROR", "COMPLETO"] = "DESHABILITADO"
