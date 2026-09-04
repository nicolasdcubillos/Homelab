"""Esquemas Pydantic de la API.

Están deliberadamente separados de los modelos ORM: así ningún campo sensible
(`password_hash`, `token_hash`) puede acabar en una respuesta por olvido, y el
esquema OpenAPI que consume el frontend describe solo el contrato público.
"""

from __future__ import annotations

import datetime as dt
import re
import zoneinfo
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    TypeAdapter,
    computed_field,
    field_validator,
    model_validator,
)

from ..models import CHANNELS, GENDER_UNISEX, GENDERS, HORIZONS, TOLERANCES
from ..security import LONGITUD_MAXIMA_PASSWORD, LONGITUD_MINIMA_PASSWORD, PasswordDebil
from ..security import validar_password as _validar_password


class Esquema(BaseModel):
    """Base común: prohíbe campos desconocidos para que un typo en el frontend
    falle ruidosamente en vez de guardarse a medias."""

    model_config = ConfigDict(extra="forbid")


class EsquemaORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


def _validar_timezone(valor: str) -> str:
    valor = (valor or "").strip()
    if not valor:
        raise ValueError("La zona horaria es obligatoria.")
    try:
        zoneinfo.ZoneInfo(valor)
    except Exception as exc:  # ZoneInfoNotFoundError y errores de ruta
        raise ValueError(f"Zona horaria desconocida: {valor}") from exc
    return valor


class _ConPassword(Esquema):
    """Mixin con la validación de política de contraseñas."""

    @staticmethod
    def _check(valor: str) -> str:
        try:
            _validar_password(valor)
        except PasswordDebil as exc:
            raise ValueError(str(exc)) from exc
        return valor


# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------


class RegistroIn(_ConPassword):
    email: EmailStr
    password: str = Field(min_length=LONGITUD_MINIMA_PASSWORD, max_length=LONGITUD_MAXIMA_PASSWORD)
    timezone: str = "America/Bogota"

    @field_validator("password")
    @classmethod
    def _password(cls, v: str) -> str:
        return cls._check(v)

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str) -> str:
        return _validar_timezone(v)


class LoginIn(Esquema):
    email: EmailStr
    password: str = Field(min_length=1, max_length=LONGITUD_MAXIMA_PASSWORD)


class CambioPasswordIn(_ConPassword):
    password_actual: str | None = Field(default=None, max_length=LONGITUD_MAXIMA_PASSWORD)
    password_nueva: str = Field(
        min_length=LONGITUD_MINIMA_PASSWORD, max_length=LONGITUD_MAXIMA_PASSWORD
    )

    @field_validator("password_nueva")
    @classmethod
    def _password(cls, v: str) -> str:
        return cls._check(v)


class PerfilIn(Esquema):
    timezone: str

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str) -> str:
        return _validar_timezone(v)


class UsuarioOut(EsquemaORM):
    """Representación pública del usuario en sesión."""

    id: str
    email: str
    role: str
    status: str
    must_change_password: bool
    timezone: str
    created_at: dt.datetime
    last_login_at: dt.datetime | None


class SesionOut(Esquema):
    """Respuesta de `/auth/me` y del login."""

    user: UsuarioOut
    csrf_token: str


class CsrfOut(Esquema):
    csrf_token: str


class RegistroOut(Esquema):
    user: UsuarioOut
    mensaje: str


class OkOut(Esquema):
    ok: bool = True
    mensaje: str = ""


# --------------------------------------------------------------------------
# Notificaciones
# --------------------------------------------------------------------------

#: E.164: un '+', dígito inicial distinto de cero y entre 8 y 15 dígitos.
RE_E164 = re.compile(r"^\+[1-9]\d{7,14}$")


def _validar_whatsapp(valor: str) -> str:
    limpio = re.sub(r"[\s()\-.]", "", (valor or "").strip())
    if not limpio:
        return ""
    if not limpio.startswith("+"):
        raise ValueError(
            "El número debe incluir el código de país, empezando por '+' "
            "(por ejemplo +573001112233)."
        )
    if not RE_E164.match(limpio):
        raise ValueError("El número de WhatsApp no tiene un formato válido (E.164).")
    return limpio


class NotificacionesIn(Esquema):
    """Destinos de notificación. Cadena vacía o `null` borra el canal."""

    whatsapp: str | None = ""
    email: str | None = ""

    @field_validator("whatsapp")
    @classmethod
    def _whatsapp(cls, v: str | None) -> str:
        return _validar_whatsapp(v or "")

    @field_validator("email")
    @classmethod
    def _email(cls, v: str | None) -> str:
        v = (v or "").strip().lower()
        if not v:
            return ""
        try:
            return str(TypeAdapter(EmailStr).validate_python(v))
        except Exception as exc:
            raise ValueError("El correo no es válido.") from exc


class PreferenciasIn(Esquema):
    """Canales activos de una app. Reemplaza el conjunto completo."""

    app_name: str
    channels: list[str] = Field(default_factory=list, max_length=8)

    @field_validator("channels")
    @classmethod
    def _canales(cls, v: list[str]) -> list[str]:
        limpios: list[str] = []
        for canal in v:
            canal = (canal or "").strip().lower()
            if not canal:
                continue
            if canal not in CHANNELS:
                raise ValueError("Canal de notificación desconocido.")
            if canal not in limpios:
                limpios.append(canal)
        return limpios


class NotificacionesOut(Esquema):
    """Forma plana, pensada para mapear directo a un formulario.

    `supported` existe para que la UI nunca tenga que hardcodear qué canales
    ofrece cada app: se deriva de `WatcherSpec.canales_soportados` en
    `watchers.py`, así que si algún watcher no implementara un canal (o deja
    de implementarlo), la UI lo refleja sin ningún cambio de frontend.
    """

    whatsapp: str | None = None
    email: str | None = None
    preferences: dict[str, list[str]] = Field(default_factory=dict)
    supported: dict[str, list[str]] = Field(default_factory=dict)


# --------------------------------------------------------------------------
# StockWatcher
# --------------------------------------------------------------------------

_MAX_TERMINOS = 30
_MAX_LARGO_TERMINO = 80


def _lista_limpia(valores: list[str], *, campo: str) -> list[str]:
    limpios: list[str] = []
    for bruto in valores:
        texto = (bruto or "").strip()
        if not texto:
            continue
        if len(texto) > _MAX_LARGO_TERMINO:
            raise ValueError(
                f"Cada valor de {campo} debe tener {_MAX_LARGO_TERMINO} caracteres o menos."
            )
        if texto not in limpios:
            limpios.append(texto)
    return limpios


def _validar_paises(valores: list[str]) -> list[str]:
    limpios: list[str] = []
    for bruto in valores:
        texto = (bruto or "").strip().upper()
        if not texto:
            continue
        if not re.fullmatch(r"[A-Z]{2}", texto):
            raise ValueError("Cada país debe ser un código ISO de dos letras, por ejemplo CO o US.")
        if texto not in limpios:
            limpios.append(texto)
    return limpios


class WatchIn(Esquema):
    name: str = Field(min_length=1, max_length=120)
    enabled: bool = True
    match_terms: list[str] = Field(min_length=1, max_length=_MAX_TERMINOS)
    exclude_terms: list[str] = Field(default_factory=list, max_length=_MAX_TERMINOS)
    variants: list[str] = Field(default_factory=list, max_length=_MAX_TERMINOS)
    colors: list[str] = Field(default_factory=list, max_length=_MAX_TERMINOS)
    countries: list[str] = Field(default_factory=list, max_length=_MAX_TERMINOS)
    notify_channels: list[str] = Field(default_factory=list, max_length=8)
    gender: str = GENDER_UNISEX
    max_price: str | None = None
    currency: str = "USD"

    @field_validator("name")
    @classmethod
    def _nombre(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("El nombre es obligatorio.")
        return v

    @field_validator("match_terms")
    @classmethod
    def _match(cls, v: list[str]) -> list[str]:
        limpios = _lista_limpia(v, campo="términos de búsqueda")
        if not limpios:
            raise ValueError("Agrega al menos un término de búsqueda.")
        return limpios

    @field_validator("exclude_terms")
    @classmethod
    def _exclude(cls, v: list[str]) -> list[str]:
        return _lista_limpia(v, campo="exclusiones")

    @field_validator("variants")
    @classmethod
    def _variants(cls, v: list[str]) -> list[str]:
        return _lista_limpia(v, campo="tallas")

    @field_validator("colors")
    @classmethod
    def _colors(cls, v: list[str]) -> list[str]:
        return _lista_limpia(v, campo="colores")

    @field_validator("countries")
    @classmethod
    def _countries(cls, v: list[str]) -> list[str]:
        return _validar_paises(v)

    @field_validator("gender")
    @classmethod
    def _gender(cls, v: str) -> str:
        v = (v or GENDER_UNISEX).strip().lower()
        if v not in GENDERS:
            raise ValueError("Género no válido: usa hombre, mujer o unisex.")
        return v

    @field_validator("notify_channels")
    @classmethod
    def _notify(cls, v: list[str]) -> list[str]:
        limpios = []
        for canal in v:
            canal = (canal or "").strip().lower()
            if canal and canal not in CHANNELS:
                raise ValueError("Canal de notificación desconocido.")
            if canal and canal not in limpios:
                limpios.append(canal)
        return limpios

    @field_validator("currency")
    @classmethod
    def _currency(cls, v: str) -> str:
        v = (v or "USD").strip().upper()
        if not re.fullmatch(r"[A-Z]{3}", v):
            raise ValueError("La moneda debe ser un código de tres letras, por ejemplo USD o COP.")
        return v

    @field_validator("max_price")
    @classmethod
    def _max_price(cls, v: str | None) -> str | None:
        if v is None:
            return None
        texto = str(v).strip().replace(",", "")
        if not texto:
            return None
        try:
            valor = Decimal(texto)
        except InvalidOperation as exc:
            raise ValueError("El precio máximo debe ser un número.") from exc
        if valor <= 0:
            raise ValueError("El precio máximo debe ser mayor que cero.")
        if valor > Decimal("100000000"):
            raise ValueError("El precio máximo es demasiado grande.")
        # Se guarda como texto normalizado para no perder precisión en SQLite.
        return format(valor.normalize(), "f")


class WatchOut(EsquemaORM):
    id: str
    name: str
    enabled: bool
    match_terms: list[str]
    exclude_terms: list[str]
    variants: list[str]
    colors: list[str]
    countries: list[str]
    notify_channels: list[str]
    gender: str
    max_price: str | None
    currency: str
    position: int
    created_at: dt.datetime
    updated_at: dt.datetime


class ReordenarIn(Esquema):
    ids: list[str] = Field(min_length=1, max_length=200)


# --------------------------------------------------------------------------
# PortfolioWatcher
# --------------------------------------------------------------------------


def _validar_ticker(valor: str) -> str:
    texto = (valor or "").strip().upper()
    if not texto:
        raise ValueError("El ticker es obligatorio.")
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9.\-]{0,15}", texto):
        raise ValueError("El ticker solo admite letras, números, punto y guion.")
    return texto


class HoldingIn(Esquema):
    ticker: str
    quantity: float = Field(gt=0)
    avg_cost: float = Field(ge=0)
    sector_hint: str = "unknown"

    @field_validator("ticker")
    @classmethod
    def _ticker(cls, v: str) -> str:
        return _validar_ticker(v)

    @field_validator("sector_hint")
    @classmethod
    def _sector(cls, v: str) -> str:
        return (v or "unknown").strip()[:64] or "unknown"

    @field_validator("quantity", "avg_cost")
    @classmethod
    def _finito(cls, v: float) -> float:
        if v != v or v in (float("inf"), float("-inf")):
            raise ValueError("El valor debe ser un número finito.")
        return v


class HoldingOut(EsquemaORM):
    id: str
    ticker: str
    quantity: float
    avg_cost: float
    sector_hint: str

    @computed_field
    @property
    def cost_basis(self) -> float:
        return round(self.quantity * self.avg_cost, 2)


class PosicionCerradaIn(Esquema):
    ticker: str
    note: str = ""

    @field_validator("ticker")
    @classmethod
    def _ticker(cls, v: str) -> str:
        return _validar_ticker(v)

    @field_validator("note")
    @classmethod
    def _note(cls, v: str) -> str:
        return (v or "").strip()[:500]


class PosicionCerradaOut(EsquemaORM):
    id: str
    ticker: str
    note: str


class PerfilRiesgoIn(Esquema):
    horizon: str = "long_term"
    tolerance: str = "moderate"
    notes: str = ""
    analysis_interval_days: int = Field(default=7, ge=1, le=365)

    @field_validator("horizon")
    @classmethod
    def _horizon(cls, v: str) -> str:
        if v not in HORIZONS:
            raise ValueError("Horizonte no válido.")
        return v

    @field_validator("tolerance")
    @classmethod
    def _tolerance(cls, v: str) -> str:
        if v not in TOLERANCES:
            raise ValueError("Tolerancia al riesgo no válida.")
        return v

    @field_validator("notes")
    @classmethod
    def _notes(cls, v: str) -> str:
        return (v or "").strip()[:2000]


class PerfilRiesgoOut(EsquemaORM):
    horizon: str
    tolerance: str
    notes: str
    analysis_interval_days: int


class PortafolioOut(Esquema):
    profile: PerfilRiesgoOut
    holdings: list[HoldingOut]
    closed_positions: list[PosicionCerradaOut]
    cost_basis_total: float


class WatchesOut(Esquema):
    """Sobre con `items` en vez de una lista desnuda: deja sitio para
    metadatos (límite, contador) sin romper el contrato."""

    items: list[WatchOut]
    limit: int


class PreviewOut(Esquema):
    app_name: str
    filename: str
    path: str
    yaml: str


class MotivoOut(Esquema):
    code: str
    message: str


class ReadinessOut(Esquema):
    ready: bool
    reasons: list[MotivoOut]


class ReadinessAppOut(ReadinessOut):
    app_name: str
    display_name: str


class ReadinessGlobalOut(Esquema):
    apps: dict[str, ReadinessAppOut]


class ConfirmarPasswordIn(Esquema):
    """Confirmación para acciones destructivas sobre datos propios."""

    password: str = Field(min_length=1, max_length=1024)


# --------------------------------------------------------------------------
# Ejecuciones
# --------------------------------------------------------------------------


class HitDetalleOut(Esquema):
    """Un hallazgo nuevo de StockWatcher, tal como lo publica ``hit_detail``.

    Espejo deliberado de lo que ya recibe el correo (mismo shape que
    ``notifiers.base.summarize`` + la imagen): la tarjeta que pinta la SPA y
    la del email deben mostrar lo mismo, solo que una en HTML de tabla y la
    otra en componentes React.
    """

    watch: str
    store: str
    product: str
    variant: str
    price: str | None = None
    url: str
    image: str | None = None
    color_matched: bool = True


class ResultadoOut(Esquema):
    """Subconjunto de ``RunSummary.as_dict()`` que vale la pena mostrar en la
    SPA. Ausente en corridas que no publican JSON estructurado (hoy, solo
    ``stockwatcher run``)."""

    new_hits: int = 0
    stores_scanned: int = 0
    stores_failed: int = 0
    hit_details: list[HitDetalleOut] = []


class EjecucionOut(EsquemaORM):
    id: int
    app_name: str
    command_key: str
    command_label: str
    status: str
    trigger: str
    started_at: dt.datetime | None
    finished_at: dt.datetime | None
    duration_seconds: float | None
    return_code: int | None
    skip_reason: str | None
    result: ResultadoOut | None = None


class EjecucionesOut(Esquema):
    items: list[EjecucionOut]


class LanzarIn(Esquema):
    command_key: str = Field(min_length=1, max_length=120)
    dry_run: bool = False


class LogOut(Esquema):
    run_id: int
    status: str
    content: str
    #: La SPA deja de refrescar cuando esto es falso.
    running: bool


class ComandoOut(Esquema):
    key: str
    label: str


class AppOut(Esquema):
    app_name: str
    display_name: str
    installed: bool
    running: bool
    commands: list[ComandoOut]
    readiness: ReadinessAppOut
    last_run: EjecucionOut | None = None
    #: Próximo disparo automático, de haberlo. La tarjeta de inicio lo muestra.
    next_run_at: dt.datetime | None = None


class AppsOut(Esquema):
    items: list[AppOut]


# ---------------------------------------------------------------------------
# Automatización
# ---------------------------------------------------------------------------


class ProgramacionOut(Esquema):
    app_name: str
    command_key: str
    command_label: str
    enabled: bool
    kind: str
    interval_minutes: int | None
    cron_expr: str | None
    next_run_at: dt.datetime | None
    last_run_at: dt.datetime | None


class ProgramacionesOut(Esquema):
    items: list[ProgramacionOut]
    timezone: str


class ProgramacionIn(Esquema):
    """Cómo debe automatizarse un comando concreto.

    `kind` decide qué campo manda: `interval` usa `interval_minutes` y `cron`
    usa `cron_expr`. La coherencia entre ambos la valida el scheduler, que es
    quien conoce los límites reales.
    """

    enabled: bool = True
    kind: Literal["interval", "cron"] = "interval"
    interval_minutes: int | None = Field(default=None, ge=5, le=60 * 24 * 30)
    cron_expr: str | None = Field(default=None, max_length=120)


class ZonaHorariaIn(Esquema):
    timezone: str = Field(min_length=1, max_length=64)

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str) -> str:
        return _validar_timezone(v)


# ---------------------------------------------------------------------------
# Administración
# ---------------------------------------------------------------------------


class UsuarioAdminOut(EsquemaORM):
    id: str
    email: str
    role: str
    status: str
    timezone: str
    must_change_password: bool
    created_at: dt.datetime
    last_login_at: dt.datetime | None
    locked_until: dt.datetime | None


class UsuariosAdminOut(Esquema):
    items: list[UsuarioAdminOut]
    total: int
    limit: int
    offset: int


class CanalResumenOut(Esquema):
    channel: str
    destination: str


class UsuarioDetalleOut(Esquema):
    user: UsuarioAdminOut
    watches: int
    watches_enabled: int
    holdings: int
    closed_positions: int
    total_runs: int
    channels: list[CanalResumenOut]
    schedules: list[ProgramacionOut]
    recent_runs: list[EjecucionOut]


class CambiarUsuarioIn(Esquema):
    """Cambios de estado y rol. Ambos campos son opcionales: la UI manda solo
    el que el admin tocó."""

    status: Literal["pending", "active", "suspended"] | None = None
    role: Literal["user", "admin"] | None = None


class PasswordAdminIn(_ConPassword):
    """O se fija una contraseña nueva, o se invalida la actual.

    `force_reset` existe para el caso «no quiero conocer su contraseña»: deja
    la cuenta sin acceso hasta que se le asigne una.
    """

    new_password: str | None = None
    force_reset: bool = False

    @model_validator(mode="after")
    def _coherente(self):
        if self.force_reset and self.new_password:
            raise ValueError(
                "Elige una sola opción: contraseña nueva o forzar el reseteo."
            )
        if not self.force_reset and not self.new_password:
            raise ValueError("Escribe una contraseña nueva o marca forzar el reseteo.")
        if self.new_password:
            self._check(self.new_password)
        return self


class MetricasOut(Esquema):
    users_total: int
    users_by_status: dict[str, int]
    admins: int
    jobs_running: int
    recent_failures: int
    runs_last_24h: int
    window_hours: int


class EntradaBitacoraOut(EsquemaORM):
    id: int
    actor_email: str
    action: str
    target_email: str
    detail_json: dict
    created_at: dt.datetime


class BitacoraOut(Esquema):
    items: list[EntradaBitacoraOut]


class EjecucionAdminOut(EjecucionOut):
    user_id: str | None
    user_email: str | None = None


class EjecucionesAdminOut(Esquema):
    items: list[EjecucionAdminOut]
