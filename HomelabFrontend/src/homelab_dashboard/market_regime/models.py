"""Tablas del modulo: evidencia compartida y entregas privadas por separado."""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base, UtcDateTime, utcnow


def new_id() -> str:
    return uuid.uuid4().hex


class RegimeAccess(Base):
    __tablename__ = "regime_access"
    __table_args__ = (CheckConstraint("level IN ('viewer', 'operator')"),)
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    level: Mapped[str] = mapped_column(String(16), nullable=False)
    granted_by: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, default=utcnow)
    user = relationship("User", foreign_keys=[user_id], back_populates="regime_access")


class RegimeConfig(Base):
    __tablename__ = "regime_config"
    __table_args__ = (CheckConstraint("id = 1 AND version >= 1"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    version: Mapped[int] = mapped_column(Integer, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, default=utcnow)
    updated_by: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="SET NULL")
    )


class RegimeModelVersion(Base):
    __tablename__ = "regime_model_versions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    data: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, default=utcnow)


class RegimeSourceState(Base):
    __tablename__ = "regime_source_state"
    source_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(32))
    detail: Mapped[str] = mapped_column(Text, default="")
    last_attempt_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime)
    last_success_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime)
    budget_day: Mapped[str] = mapped_column(String(10), default="")
    daily_requests: Mapped[int] = mapped_column(Integer, default=0)


class RegimeLicense(Base):
    __tablename__ = "regime_licenses"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    source_id: Mapped[str] = mapped_column(String(64), index=True)
    reference: Mapped[str] = mapped_column(Text)
    evidence_sha256: Mapped[str | None] = mapped_column(String(64))
    permissions: Mapped[dict] = mapped_column(JSON)
    valid_until: Mapped[dt.datetime | None] = mapped_column(UtcDateTime)
    created_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, default=utcnow)
    revoked_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime)


class RegimeRawPayload(Base):
    __tablename__ = "regime_raw_payloads"
    __table_args__ = (UniqueConstraint("source_id", "sha256", name="uq_regime_raw"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[str] = mapped_column(String(64))
    sha256: Mapped[str] = mapped_column(String(64))
    source_url: Mapped[str] = mapped_column(Text)
    compressed: Mapped[bytes] = mapped_column(LargeBinary)
    ingested_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, default=utcnow)


class RegimePayloadLicense(Base):
    __tablename__ = "regime_payload_licenses"
    raw_id: Mapped[int] = mapped_column(ForeignKey("regime_raw_payloads.id"), primary_key=True)
    license_id: Mapped[str] = mapped_column(ForeignKey("regime_licenses.id"))


class RegimeObservation(Base):
    __tablename__ = "regime_observations"
    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "series_id",
            "period",
            "vintage",
            "raw_hash",
            name="uq_regime_observation",
        ),
        Index("ix_regime_observation_asof", "series_id", "available_at", "observed_at"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    raw_id: Mapped[int] = mapped_column(ForeignKey("regime_raw_payloads.id"))
    source_id: Mapped[str] = mapped_column(String(64))
    series_id: Mapped[str] = mapped_column(String(64))
    period: Mapped[str] = mapped_column(String(32))
    value: Mapped[str] = mapped_column(String(80))
    unit: Mapped[str] = mapped_column(String(64))
    frequency: Mapped[str] = mapped_column(String(16))
    observed_at: Mapped[dt.datetime] = mapped_column(UtcDateTime)
    published_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime)
    available_at: Mapped[dt.datetime] = mapped_column(UtcDateTime)
    ingested_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, default=utcnow)
    vintage: Mapped[str] = mapped_column(String(120))
    timestamp_precision: Mapped[str] = mapped_column(String(16))
    source_url: Mapped[str] = mapped_column(Text)
    raw_hash: Mapped[str] = mapped_column(String(64))
    quality: Mapped[str] = mapped_column(String(16), default="OK")


class RegimeEvent(Base):
    __tablename__ = "regime_events"
    __table_args__ = (
        UniqueConstraint("source_id", "event_id", "raw_hash", name="uq_regime_event"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[str] = mapped_column(String(64))
    event_id: Mapped[str] = mapped_column(String(120))
    raw_id: Mapped[int] = mapped_column(ForeignKey("regime_raw_payloads.id"))
    raw_hash: Mapped[str] = mapped_column(String(64))
    available_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, index=True)
    ingested_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, default=utcnow)
    data: Mapped[dict] = mapped_column(JSON)


class RegimeRun(Base):
    __tablename__ = "regime_runs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(32), default="PENDIENTE", index=True)
    created_by: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="SET NULL")
    )
    requested_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, default=utcnow)
    cutoff: Mapped[dt.datetime | None] = mapped_column(UtcDateTime)
    dedupe_key: Mapped[str | None] = mapped_column(String(120), unique=True)
    lease_until: Mapped[dt.datetime | None] = mapped_column(UtcDateTime)
    started_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime)
    finished_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    detail: Mapped[str] = mapped_column(Text, default="")
    result: Mapped[dict] = mapped_column(JSON, default=dict)


class RegimeSnapshot(Base):
    __tablename__ = "regime_snapshots"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    as_of: Mapped[dt.datetime] = mapped_column(UtcDateTime, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, default=utcnow)
    model_id: Mapped[str] = mapped_column(ForeignKey("regime_model_versions.id"))
    mode: Mapped[str] = mapped_column(String(24), default="OPERACIONAL")
    data: Mapped[dict] = mapped_column(JSON)
    sha256: Mapped[str] = mapped_column(String(64))


class RegimeTransition(Base):
    __tablename__ = "regime_transitions"
    horizon: Mapped[str] = mapped_column(String(16), primary_key=True)
    state: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, default=utcnow)


class RegimeReport(Base):
    __tablename__ = "regime_reports"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    week_key: Mapped[str] = mapped_column(String(16), unique=True)
    snapshot_id: Mapped[str] = mapped_column(ForeignKey("regime_snapshots.id"))
    created_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, default=utcnow)
    data: Mapped[dict] = mapped_column(JSON)
    sha256: Mapped[str] = mapped_column(String(64))


class RegimeSubscription(Base):
    __tablename__ = "regime_subscriptions"
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    email: Mapped[bool] = mapped_column(Boolean, default=False)
    whatsapp: Mapped[bool] = mapped_column(Boolean, default=False)
    consents: Mapped[dict] = mapped_column(JSON, default=dict)
    horizons: Mapped[list] = mapped_column(JSON, default=lambda: ["SHORT", "MEDIUM", "LONG"])
    updated_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, default=utcnow)


class RegimeOutbox(Base):
    __tablename__ = "regime_outbox"
    __table_args__ = (
        UniqueConstraint("report_id", "user_id", "channel", name="uq_regime_delivery"),
    )
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    report_id: Mapped[str] = mapped_column(ForeignKey("regime_reports.id"))
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    channel: Mapped[str] = mapped_column(String(16))
    destination_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="PENDIENTE")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, default=utcnow)
    next_attempt_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime)
    lease_until: Mapped[dt.datetime | None] = mapped_column(UtcDateTime)
    provider_id: Mapped[str | None] = mapped_column(String(256))
    detail: Mapped[str] = mapped_column(Text, default="")


class RegimeBacktestRun(Base):
    __tablename__ = "regime_backtest_runs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    created_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, default=utcnow)
    data: Mapped[dict] = mapped_column(JSON)
