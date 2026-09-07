"""Modelos ORM del dashboard.

Todo dato de usuario cuelga de `users` con `ON DELETE CASCADE`, de modo que
"eliminar un usuario con todos sus datos" sea una sola sentencia y no dependa
de que la capa de aplicación recuerde limpiar cada tabla.

La excepción deliberada es `audit_log`: sus filas sobreviven al borrado del
usuario (`ON DELETE SET NULL`) y guardan el correo desnormalizado, porque una
bitácora que desaparece junto con lo que auditaba no sirve de nada.

La segunda excepción es `trading_bot_config`, que **no cuelga de nadie**: el
módulo de trading es un recurso compartido por diseño (un solo bot que varios
usuarios autorizados miran y operan), no una configuración por persona. Esa
diferencia obliga a bloqueo optimista (`version`) y a registrar quién fue el
último en tocar cada motor; ver la clase para el razonamiento completo.

Las columnas JSON guardan listas simples. SQLAlchemy no detecta mutaciones en
sitio sobre ellas, así que la capa de servicio siempre **reasigna** la lista
completa en vez de hacer `.append(...)`.
"""

from __future__ import annotations

import datetime as dt
import json
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
from .market_regime.models import RegimeAccess

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

# ------------------------------------------------------------------- trading

#: Motores de trading soportados. Uno por clase de activo: el ecosistema no
#: tiene un solo bot que haga bien cripto y acciones, así que se integran dos
#: y `trading.py` absorbe la diferencia tras una interfaz común.
BOT_FREQTRADE = "freqtrade"
BOT_LUMIBOT = "lumibot"
TRADING_BOTS = (BOT_FREQTRADE, BOT_LUMIBOT)

#: Niveles de acceso al módulo de trading. A diferencia del resto de la app
#: —donde cada usuario solo ve lo suyo— el trading es un recurso **compartido**:
#: todos los que tengan acceso miran y operan la misma configuración. Por eso
#: hace falta un permiso explícito que concede un admin, y por eso se distingue
#: entre mirar y operar.
TRADING_VIEWER = "viewer"
TRADING_OPERATOR = "operator"
TRADING_LEVELS = (TRADING_VIEWER, TRADING_OPERATOR)

#: Modos de operación. **Deliberadamente tiene un solo valor.**
#:
#: El módulo opera exclusivamente con dinero simulado. Que "paper" sea el único
#: valor admitido por el `CHECK` de la tabla convierte esa promesa en una
#: invariante del esquema y no en una preferencia: la base de datos misma se
#: niega a almacenar un bot en modo real. Habilitar dinero real exigiría una
#: migración —un acto deliberado y revisable en un PR— y nunca un toggle en la
#: UI ni un descuido de validación. Es el mismo principio que hace que
#: PortfolioWatcher nunca emita una orden ejecutable.
TRADING_MODE_PAPER = "paper"
TRADING_MODES = (TRADING_MODE_PAPER,)


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
    #: Permiso sobre el módulo de trading, o `None` si no tiene acceso.
    #: `foreign_keys` es obligatorio aquí: `TradingAccess` apunta dos veces a
    #: `users` (el titular y el admin que concedió), y sin desambiguar
    #: SQLAlchemy no puede resolver el join.
    trading_access: Mapped[TradingAccess | None] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
        foreign_keys="TradingAccess.user_id",
    )
    regime_access: Mapped[RegimeAccess | None] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
        foreign_keys="RegimeAccess.user_id",
    )

    @property
    def regime_level(self) -> str | None:
        if self.status != USER_ACTIVE or self.must_change_password:
            return None
        if self.role == ROLE_ADMIN:
            return "operator"
        return self.regime_access.level if self.regime_access is not None else None

    @property
    def is_admin(self) -> bool:
        return self.role == ROLE_ADMIN

    @property
    def can_run_jobs(self) -> bool:
        """Solo un usuario aprobado y sin reset pendiente puede ejecutar."""
        return self.status == USER_ACTIVE and not self.must_change_password

    @property
    def trading_level(self) -> str | None:
        """Nivel efectivo sobre el módulo de trading, o `None` si no tiene acceso.

        Única fuente de verdad del permiso: la consultan tanto la dependencia
        que protege las rutas (`deps.acceso_trading`) como la respuesta de
        `/auth/me`, para que la barra de navegación no pueda ofrecer una
        sección a la que la API le va a responder 404.

        Un admin cuenta como operador sin concesión explícita, igual que en el
        resto de la app. Una cuenta que no está activa no tiene acceso aunque
        conserve su fila: el permiso no salta la aprobación.
        """
        if self.status != USER_ACTIVE:
            return None
        if self.role == ROLE_ADMIN:
            return TRADING_OPERATOR
        acceso = self.trading_access
        return acceso.level if acceso is not None else None


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
    #: Resultado estructurado (JSON), cuando el watcher lo publica en su
    #: salida — hoy solo StockWatcher, con el detalle de cada hallazgo nuevo.
    #: Se guarda aparte del log de texto para no tener que re-parsearlo cada
    #: vez que la SPA pide una ejecución.
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    @property
    def is_terminal(self) -> bool:
        return self.status != JOB_RUNNING

    @property
    def result(self) -> dict | None:
        if not self.result_json:
            return None
        try:
            return json.loads(self.result_json)
        except (TypeError, ValueError):  # pragma: no cover - defensive
            return None


# ------------------------------------------------------------------- trading


class TradingAccess(Base):
    """Permiso de un usuario sobre el módulo de trading, concedido por un admin.

    Una fila por usuario con acceso; su ausencia significa "sin acceso". No
    lleva columna `enabled` a propósito: revocar es borrar la fila, de modo que
    no exista un estado intermedio ("tiene fila pero apagada") que alguien
    pueda malinterpretar al leer la tabla.

    `granted_by_email` está desnormalizado por la misma razón que en
    `audit_log`: si el admin que concedió el permiso se elimina, seguir sabiendo
    quién lo concedió es justamente el dato que importa.
    """

    __tablename__ = "trading_access"
    __table_args__ = (_enum_check("level", TRADING_LEVELS),)

    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    level: Mapped[str] = mapped_column(String(16), nullable=False, default=TRADING_VIEWER)

    granted_by_user_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    granted_by_email: Mapped[str] = mapped_column(String(320), nullable=False, default="")
    granted_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow)

    user: Mapped[User] = relationship(
        back_populates="trading_access", foreign_keys=[user_id]
    )

    @property
    def puede_operar(self) -> bool:
        return self.level == TRADING_OPERATOR


class TradingBotConfig(Base):
    """Configuración **compartida** de un motor de trading.

    Rompe a propósito la regla del resto del esquema: no cuelga de `users`
    porque no pertenece a nadie. Hay exactamente una fila por motor y todos los
    usuarios con acceso ven y editan esa misma fila — que es justo lo que se
    pidió: un bot común, no uno por persona.

    Eso obliga a resolver dos problemas que el modelo por usuario no tenía:

    1. **Ediciones concurrentes.** `version` implementa bloqueo optimista: quien
       guarda manda la versión que leyó y, si ya no coincide, la API rechaza el
       cambio en vez de pisar en silencio el trabajo de otro.
    2. **Trazabilidad.** `updated_by_email` (desnormalizado, como en
       `audit_log`) responde "quién dejó el bot así" sin depender de que el
       usuario siga existiendo. El detalle de cada cambio va además al
       `audit_log`.
    """

    __tablename__ = "trading_bot_config"
    __table_args__ = (
        _enum_check("bot_name", TRADING_BOTS),
        _enum_check("mode", TRADING_MODES),
        CheckConstraint("version > 0", name="ck_version_positiva"),
    )

    bot_name: Mapped[str] = mapped_column(String(32), primary_key=True)

    #: Interruptor que los operadores encienden y apagan desde la UI. Es la
    #: *intención* declarada; `trading.py` la reconcilia con el motor real.
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    #: Siempre `"paper"`. Ver `TRADING_MODES`: el `CHECK` de la tabla impide
    #: almacenar cualquier otro valor, así que el modo real no es representable.
    mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default=TRADING_MODE_PAPER, server_default=TRADING_MODE_PAPER
    )

    #: Parámetros del motor (pares/tickers, timeframe, capital simulado,
    #: límites de riesgo). El esquema concreto lo valida `trading.py`, que es
    #: quien conoce el contrato de cada motor.
    config_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    updated_by_user_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_by_email: Mapped[str] = mapped_column(String(320), nullable=False, default="")
    updated_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow)
    created_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow)
