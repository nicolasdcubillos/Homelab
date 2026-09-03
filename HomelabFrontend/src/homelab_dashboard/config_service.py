"""Servicio de configuración por usuario.

Traduce lo que el usuario configuró en el panel a los archivos que cada watcher
espera, en su workspace aislado, justo antes de cada corrida. La base es la
única fuente de verdad: no hay YAML almacenado que pueda quedar desincronizado.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import watchers
from .models import (
    USER_ACTIVE,
    AppChannelPref,
    NotificationChannel,
    PortfolioClosedPosition,
    PortfolioHolding,
    PortfolioProfile,
    StockWatch,
    User,
)
from .settings import Settings
from .watchers import WatcherSpec
from .workspace import UserWorkspace


@dataclass(frozen=True)
class ConfigGenerada:
    """Resultado de preparar el workspace para una corrida."""

    config_path: str
    state_path: str
    entorno: dict[str, str]
    argumentos: list[str]


@dataclass(frozen=True)
class Motivo:
    """Una razón por la que no se puede ejecutar.

    Lleva `code` además del texto para que la UI pueda enlazar a la pantalla
    que resuelve el problema en vez de limitarse a mostrar un mensaje.
    """

    code: str
    message: str


@dataclass(frozen=True)
class Readiness:
    """Por qué un usuario puede (o no) ejecutar una app.

    Se expone en la API para que la UI explique la causa en vez de dejar un
    botón que falla, y la usa el scheduler como pre-vuelo: ambos watchers
    abortan con `ConfigError` si les falta lo básico.
    """

    listo: bool
    motivos: list[Motivo]

    @property
    def motivo(self) -> str:
        """Resumen en una línea, para el historial de ejecuciones."""
        return " ".join(m.message for m in self.motivos)


# ---------------------------------------------------------------------------
# Lecturas
# ---------------------------------------------------------------------------


def destinos_de(db: Session, user_id: str) -> dict[str, str]:
    """Canal -> destino configurado por el usuario."""
    filas = db.scalars(
        select(NotificationChannel).where(NotificationChannel.user_id == user_id)
    )
    return {f.channel: f.destination for f in filas if f.destination}


def canales_activos_de(db: Session, user_id: str, app_name: str) -> set[str]:
    """Canales encendidos para una app concreta.

    Sin preferencia explícita se asume encendido: un usuario que configuró su
    WhatsApp espera recibir avisos sin tener que activarlos app por app.
    """
    filas = db.scalars(
        select(AppChannelPref).where(
            AppChannelPref.user_id == user_id, AppChannelPref.app_name == app_name
        )
    ).all()
    explicitas = {f.channel: f.enabled for f in filas}
    spec = watchers.spec_de(app_name)
    soportados = spec.canales_soportados if spec else ()
    return {c for c in soportados if explicitas.get(c, True)}


def watches_de(db: Session, user_id: str) -> list[StockWatch]:
    return list(
        db.scalars(
            select(StockWatch)
            .where(StockWatch.user_id == user_id)
            .order_by(StockWatch.position, StockWatch.created_at)
        )
    )


def holdings_de(db: Session, user_id: str) -> list[PortfolioHolding]:
    return list(
        db.scalars(
            select(PortfolioHolding)
            .where(PortfolioHolding.user_id == user_id)
            .order_by(PortfolioHolding.ticker)
        )
    )


def cerradas_de(db: Session, user_id: str) -> list[PortfolioClosedPosition]:
    return list(
        db.scalars(
            select(PortfolioClosedPosition)
            .where(PortfolioClosedPosition.user_id == user_id)
            .order_by(PortfolioClosedPosition.ticker)
        )
    )


def perfil_de(db: Session, user_id: str) -> PortfolioProfile | None:
    return db.get(PortfolioProfile, user_id)


# ---------------------------------------------------------------------------
# Readiness
# ---------------------------------------------------------------------------


def evaluar_readiness(db: Session, usuario: User, app_name: str) -> Readiness:
    """Comprueba si una corrida tiene sentido antes de lanzarla."""
    motivos: list[Motivo] = []
    spec = watchers.spec_de(app_name)

    if spec is None:
        return Readiness(
            listo=False,
            motivos=[Motivo("app_desconocida", "Esta aplicación no está soportada por el panel.")],
        )

    if usuario.status != USER_ACTIVE:
        motivos.append(
            Motivo("cuenta_no_activa", "Tu cuenta todavía no está activa.")
        )

    destinos = destinos_de(db, usuario.id)
    activos = canales_activos_de(db, usuario.id, app_name)
    if not [c for c in activos if destinos.get(c)]:
        if spec.canales_soportados == (watchers.CHANNEL_WHATSAPP,):
            texto = (
                "Configura tu número de WhatsApp para recibir los avisos de "
                f"{spec.display_name}."
            )
        else:
            texto = f"Activa al menos un canal de notificación para {spec.display_name}."
        motivos.append(Motivo("sin_destino", texto))

    if app_name == watchers.APP_STOCKWATCHER:
        if not [w for w in watches_de(db, usuario.id) if w.enabled]:
            motivos.append(
                Motivo("sin_watches", "Agrega al menos un producto para vigilar.")
            )
    elif app_name == watchers.APP_PORTFOLIOWATCHER:
        # PortfolioWatcher aborta con ConfigError si `holdings` está vacío
        # (hallazgo 5 del contrato), así que se comprueba antes de lanzar.
        if not holdings_de(db, usuario.id):
            motivos.append(
                Motivo("sin_holdings", "Agrega al menos una posición a tu portafolio.")
            )

    return Readiness(listo=not motivos, motivos=motivos)


# ---------------------------------------------------------------------------
# Generación
# ---------------------------------------------------------------------------


def _contenido_para(db: Session, usuario: User, spec: WatcherSpec, state_path: str) -> str:
    if spec.app_name == watchers.APP_STOCKWATCHER:
        return watchers.generar_watches_yaml(
            watches_de(db, usuario.id),
            state_path=state_path,
            canales_activos=canales_activos_de(db, usuario.id, spec.app_name),
        )
    if spec.app_name == watchers.APP_PORTFOLIOWATCHER:
        return watchers.generar_portfolio_yaml(
            perfil_de(db, usuario.id),
            holdings_de(db, usuario.id),
            cerradas_de(db, usuario.id),
        )
    raise ValueError(f"App sin generador de configuración: {spec.app_name}")


def previsualizar(db: Session, settings: Settings, usuario: User, app_name: str) -> str:
    """El YAML que se generaría, sin escribir nada.

    Da transparencia al usuario sobre qué se le envía al watcher, sin
    reabrir la puerta a editar YAML a mano.
    """
    spec = watchers.spec_de(app_name)
    if spec is None:
        raise ValueError(f"App desconocida: {app_name}")
    ws = UserWorkspace.para(settings, usuario.id)
    state_path = str(ws.ruta_estado(app_name, spec.state_filename))
    return _contenido_para(db, usuario, spec, state_path)


def preparar(
    db: Session,
    settings: Settings,
    usuario: User,
    app_name: str,
    *,
    stores_path: str | None = None,
) -> ConfigGenerada:
    """Escribe la config del usuario y devuelve todo lo que necesita el job."""
    spec = watchers.spec_de(app_name)
    if spec is None:
        raise ValueError(f"App desconocida: {app_name}")

    ws = UserWorkspace.para(settings, usuario.id)
    ws.preparar(app_name)

    state_path = str(ws.ruta_estado(app_name, spec.state_filename))
    contenido = _contenido_para(db, usuario, spec, state_path)
    config_path = str(ws.escribir_config(app_name, spec.config_filename, contenido))

    destinos = destinos_de(db, usuario.id)
    canales_activos = canales_activos_de(db, usuario.id, app_name)
    entorno = watchers.construir_entorno(
        spec,
        destinos=destinos,
        canales_activos=canales_activos,
        state_path=state_path,
        config_path=config_path,
    )
    argumentos = watchers.construir_argumentos(
        spec,
        config_path=config_path,
        state_path=state_path,
        stores_path=stores_path,
        destinos=destinos,
        canales_activos=canales_activos,
    )
    return ConfigGenerada(
        config_path=config_path,
        state_path=state_path,
        entorno=entorno,
        argumentos=argumentos,
    )
