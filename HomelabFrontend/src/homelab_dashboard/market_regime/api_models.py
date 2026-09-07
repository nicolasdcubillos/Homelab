"""Respuestas de API sin credenciales, destinatarios ajenos ni payloads raw."""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import Field

from .schemas import Contract, CoverageItem, Horizon, ReportData, SnapshotData, SourceInfo


class OverviewOut(Contract):
    enabled: bool
    engine_enabled: bool
    deliveries_enabled: bool
    snapshot_id: str | None = None
    snapshot: SnapshotData | None = None
    coverage: list[CoverageItem]
    first_snapshot_at: dt.datetime | None = None
    next_report_at: dt.datetime | None = None
    calendar_status: str
    warning: str = "Score heuristico no validado; no es probabilidad de ganancias."


class SourcesOut(Contract):
    items: list[SourceInfo]


class CoverageOut(Contract):
    items: list[CoverageItem]


class SnapshotOut(Contract):
    id: str
    created_at: dt.datetime
    sha256: str
    data: SnapshotData


class HistoryOut(Contract):
    items: list[SnapshotOut]
    first_available_at: dt.datetime | None
    requested_from: dt.datetime
    unavailable_before_first: bool
    total: int
    limit: int
    offset: int


class ConfigOut(Contract):
    version: int
    enabled: bool
    config: dict[str, object]
    updated_at: dt.datetime


class ConfigIn(Contract):
    version: int = Field(ge=1)
    enabled: bool
    config: dict[str, object]


class RunIn(Contract):
    kind: Literal["ingest", "snapshot", "report"] = "ingest"


class RunOut(Contract):
    id: str
    kind: str
    status: str
    requested_at: dt.datetime
    started_at: dt.datetime | None
    finished_at: dt.datetime | None
    detail: str
    result: dict[str, object]


class RunsOut(Contract):
    items: list[RunOut]


class ReportOut(Contract):
    id: str
    week_key: str
    snapshot_id: str
    created_at: dt.datetime
    sha256: str
    data: ReportData


class ReportsOut(Contract):
    items: list[ReportOut]
    total: int
    limit: int
    offset: int


class SubscriptionIn(Contract):
    enabled: bool = False
    email: bool = False
    whatsapp: bool = False
    horizons: list[Horizon] = Field(default_factory=lambda: ["SHORT", "MEDIUM", "LONG"])
    accept_consent: bool = False


class SubscriptionOut(Contract):
    enabled: bool
    email: bool
    whatsapp: bool
    horizons: list[Horizon]
    email_ready: bool = False
    whatsapp_ready: bool = False
    detail: str = ""
    consent_version: str = "market-regime-v1"


class DeliveryOut(Contract):
    id: str
    report_id: str
    channel: str
    status: str
    attempts: int
    created_at: dt.datetime
    detail: str


class DeliveriesOut(Contract):
    items: list[DeliveryOut]


class AccessIn(Contract):
    level: Literal["viewer", "operator"]


class AccessOut(Contract):
    user_id: str
    level: Literal["viewer", "operator"]


class AccessesOut(Contract):
    items: list[AccessOut]
