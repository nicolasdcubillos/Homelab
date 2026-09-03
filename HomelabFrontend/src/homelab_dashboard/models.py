"""Modelos ORM del dashboard.

Todo dato de usuario cuelga de `users` con `ON DELETE CASCADE`, de modo que
"eliminar un usuario con todos sus datos" sea una sola sentencia y no dependa
de que la capa de aplicación recuerde limpiar cada tabla.

La excepción deliberada es `audit_log`: sus filas sobreviven al borrado del
usuario (`ON DELETE SET NULL`) y guardan el correo desnormalizado, porque una
bitácora que desaparece junto con lo que auditaba no sirve de nada.

Las columnas JSON guardan listas simples. SQLAlchemy no detecta mutaciones en
sitio sobre ellas, así que la capa de servicio siempre **reasigna** la lista
completa en vez de hacer `.append(...)`.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base, UtcDateTime, utcnow

# --------------------------------------------------------------------- enums

ROLE_USER = "user"
ROLE_ADMIN = "admin"
ROLES = (ROLE_USER, ROLE_ADMIN)

USER_PENDING = "pending"
USER_ACTIVE = "active"
USER_SUSPENDED = "suspended"
USER_STATUSES = (USER_PENDING, USER_ACTIVE, USER_SUSPENDED)

CHANNEL_WHATSAPP = "whatsapp"
CHANNEL_EMAIL = "email"
CHANNELS = (CHANNEL_WHATSAPP, CHANNEL_EMAIL)

SCHEDULE_INTERVAL = "interval"
SCHEDULE_CRON = "cron"
SCHEDULE_KINDS = (SCHEDULE_INTERVAL, SCHEDULE_CRON)

TRIGGER_MANUAL = "manual"
TRIGGER_SCHEDULE = "schedule"
TRIGGERS = (TRIGGER_MANUAL, TRIGGER_SCHEDULE)

JOB_RUNNING = "running"
JOB_SUCCESS = "success"
JOB_ERROR = "error"
JOB_SKIPPED = "skipped"
JOB_CANCELLED = "cancelled"
JOB_STATUSES = (JOB_RUNNING, JOB_SUCCESS, JOB_ERROR, JOB_SKIPPED, JOB_CANCELLED)

GENDER_MENS = "mens"
GENDER_WOMENS = "womens"
GENDER_UNISEX = "unisex"
GENDERS = (GENDER_MENS, GENDER_WOMENS, GENDER_UNISEX)

TOLERANCES = ("conservative", "moderate", "aggressive")
HORIZONS = ("short_term", "medium_term", "long_term")


def _new_id() -> str:
    return uuid.uuid4().hex


def _enum_check(column: str, values: tuple[str, ...]) -> CheckConstraint:
    allowed = ", ".join(f"'{v}'" for v in values)
    return CheckConstraint(f"{column} IN ({allowed})", name=f"ck_{column}_valido")


# ---------------------------------------------------------------- identidad


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        _enum_check("role", ROLES),
        _enum_check("status", USER_STATUSES),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    #: Siempre normalizado a minúsculas por la capa de servicio.
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default=ROLE_USER)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=USER_PENDING)
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="America/Bogota")

    created_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow)
    last_login_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime, nullable=True)
    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[dt.datetime | None] = mapped_column(UtcDateTime, nullable=True)

    sessions: Mapped[list[AuthSession]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    notification_channels: Mapped[list[NotificationChannel]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    watches: Mapped[list[StockWatch]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    holdings: Mapped[list[PortfolioHolding]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )

    @property
    def is_admin(self) -> bool:
        return self.role == ROLE_ADMIN

    @property
    def can_run_jobs(self) -> bool:
        """Solo un usuario aprobado y sin reset pendiente puede ejecutar."""
        return self.status == USER_ACTIVE and not self.must_change_password


class AuthSession(Base):
    """Sesión de navegador. Guarda el *hash* del token, nunca el token."""

    __tablename__ = "auth_sessions"
    __table_args__ = (Index("ix_auth_sessions_user", "user_id"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    #: Token CSRF de doble envío, asociado a esta sesión concreta.
    csrf_token: Mapped[str] = mapped_column(String(64), nullable=False)

    created_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow)
    expires_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False)
    last_seen_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow)
    revoked_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime, nullable=True)

    user_agent: Mapped[str | None] = mapped_column(String(256), nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)

    user: Mapped[User] = relationship(back_populates="sessions")

    def is_valid(self, now: dt.datetime | None = None) -> bool:
        now = now or utcnow()
        return self.revoked_at is None and self.expires_at > now


class LoginAttempt(Base):
    """Intentos de login, para el rate limiting sin depender de Redis."""

    __tablename__ = "login_attempts"
    __table_args__ = (
        Index("ix_login_attempts_email_time", "email", "created_at"),
        Index("ix_login_attempts_ip_time", "ip", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    ip: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    successful: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow)


class AuditLog(Base):
    """Bitácora de acciones administrativas. Sobrevive al borrado de usuarios."""

    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_log_created", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_user_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    actor_email: Mapped[str] = mapped_column(String(320), nullable=False, default="")
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_user_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    target_email: Mapped[str] = mapped_column(String(320), nullable=False, default="")
    detail_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow)


# ----------------------------------------------------------- notificaciones


class NotificationChannel(Base):
    """Destino de notificación del usuario para un canal concreto."""

    __tablename__ = "notification_channels"
    __table_args__ = (
        UniqueConstraint("user_id", "channel", name="uq_notification_channel"),
        _enum_check("channel", CHANNELS),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    #: Correo electrónico o número en E.164, según el canal.
    destination: Mapped[str] = mapped_column(String(320), nullable=False)
    verified_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow)

    user: Mapped[User] = relationship(back_populates="notification_channels")


class AppChannelPref(Base):
    """Qué canales están activos para una app concreta de un usuario."""

    __tablename__ = "app_channel_prefs"
    __table_args__ = (
        UniqueConstraint("user_id", "app_name", "channel", name="uq_app_channel_pref"),
        _enum_check("channel", CHANNELS),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    app_name: Mapped[str] = mapped_column(String(64), nullable=False)
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


# ------------------------------------------------------------- StockWatcher


class StockWatch(Base):
    """Un producto que el usuario quiere vigilar."""

    __tablename__ = "stock_watches"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_stock_watch_nombre"),
        _enum_check("gender", GENDERS),
        Index("ix_stock_watches_user", "user_id"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    match_terms: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    exclude_terms: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    variants: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    colors: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    countries: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    notify_channels: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)

    gender: Mapped[str] = mapped_column(String(16), nullable=False, default=GENDER_UNISEX)
    #: Texto decimal (p. ej. "250.00") para no perder precisión monetaria en
    #: el ida y vuelta por float de SQLite. Se valida como Decimal en la API.
    max_price: Mapped[str | None] = mapped_column(String(32), nullable=True)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")

    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow)

    user: Mapped[User] = relationship(back_populates="watches")


# --------------------------------------------------------- PortfolioWatcher


class PortfolioProfile(Base):
    """Perfil de riesgo e intervalo de análisis del usuario."""

    __tablename__ = "portfolio_profiles"
    __table_args__ = (
        _enum_check("tolerance", TOLERANCES),
        _enum_check("horizon", HORIZONS),
        CheckConstraint("analysis_interval_days > 0", name="ck_intervalo_positivo"),
    )

    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    horizon: Mapped[str] = mapped_column(String(24), nullable=False, default="long_term")
    tolerance: Mapped[str] = mapped_column(String(24), nullable=False, default="moderate")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    analysis_interval_days: Mapped[int] = mapped_column(Integer, nullable=False, default=7)
    updated_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow)


class PortfolioHolding(Base):
    """Posición activa. Una fila por ticker: `avg_cost` es el costo promedio."""

    __tablename__ = "portfolio_holdings"
    __table_args__ = (
        UniqueConstraint("user_id", "ticker", name="uq_holding_ticker"),
        CheckConstraint("quantity > 0", name="ck_cantidad_positiva"),
        CheckConstraint("avg_cost >= 0", name="ck_costo_no_negativo"),
        Index("ix_portfolio_holdings_user", "user_id"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    ticker: Mapped[str] = mapped_column(String(16), nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    avg_cost: Mapped[float] = mapped_column(Float, nullable=False)
    sector_hint: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown")
    created_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow)

    user: Mapped[User] = relationship(back_populates="holdings")


class PortfolioClosedPosition(Base):
    """Posición cerrada: referencia histórica, excluida del análisis activo."""

    __tablename__ = "portfolio_closed_positions"
    __table_args__ = (
        UniqueConstraint("user_id", "ticker", name="uq_closed_ticker"),
        Index("ix_portfolio_closed_user", "user_id"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    ticker: Mapped[str] = mapped_column(String(16), nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow)


# ------------------------------------------------------------- programación


class Schedule(Base):
    """Programación de un comando concreto de una app para un usuario."""

    __tablename__ = "schedules"
    __table_args__ = (
        UniqueConstraint("user_id", "app_name", "command_key", name="uq_schedule"),
        _enum_check("kind", SCHEDULE_KINDS),
        Index("ix_schedules_due", "enabled", "next_run_at"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    app_name: Mapped[str] = mapped_column(String(64), nullable=False)
    command_key: Mapped[str] = mapped_column(String(128), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    kind: Mapped[str] = mapped_column(String(16), nullable=False, default=SCHEDULE_INTERVAL)
    interval_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cron_expr: Mapped[str | None] = mapped_column(String(128), nullable=True)

    next_run_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime, nullable=True)
    last_run_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow)


class JobRun(Base):
    """Una ejecución concreta de un comando, manual o programada.

    `user_id` es nullable a propósito: las filas anteriores a la migración
    multiusuario no pertenecen a nadie y solo las ve el admin como historial
    heredado.
    """

    __tablename__ = "job_runs"
    __table_args__ = (
        _enum_check("status", JOB_STATUSES),
        _enum_check("trigger", TRIGGERS),
        Index("ix_job_runs_user_app", "user_id", "app_name", "id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    app_name: Mapped[str] = mapped_column(String(64), nullable=False)
    # `server_default` y no solo `default`: la tabla la escriben tanto el ORM
    # como el `JobManager` con sqlite3 crudo, así que el valor por defecto
    # tiene que vivir en el esquema y no en la capa de Python.
    command_key: Mapped[str] = mapped_column(
        String(128), nullable=False, default="", server_default=""
    )
    command_label: Mapped[str] = mapped_column(String(128), nullable=False)
    args_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="[]")
    log_path: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")

    started_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow)
    finished_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=JOB_RUNNING)
    return_code: Mapped[int | None] = mapped_column(Integer, nullable=True)

    trigger: Mapped[str] = mapped_column(
        String(16), nullable=False, default=TRIGGER_MANUAL, server_default=TRIGGER_MANUAL
    )
    schedule_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("schedules.id", ondelete="SET NULL"), nullable=True
    )
    #: Motivo cuando `status == "skipped"` (p. ej. ya había un job corriendo).
    skip_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    @property
    def is_terminal(self) -> bool:
        return self.status != JOB_RUNNING
