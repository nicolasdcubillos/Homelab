"""Rutas de configuración del propio usuario: `/api/v1/me/*`.

Regla invariable de todo el módulo: el `user_id` sale de `usuario.id`, que
viene de la cookie de sesión. Ninguna ruta lo acepta por URL ni por cuerpo, así
que no existe la posibilidad de pedir los datos de otra persona.
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from sqlalchemy import delete, func, select

from .. import config_service, watchers
from ..db import utcnow
from ..models import (
    CHANNEL_EMAIL,
    CHANNEL_WHATSAPP,
    CHANNELS,
    JOB_RUNNING,
    SCHEDULE_CRON,
    SCHEDULE_INTERVAL,
    AppChannelPref,
    JobRun,
    NotificationChannel,
    PortfolioClosedPosition,
    PortfolioHolding,
    PortfolioProfile,
    Schedule,
    StockWatch,
)
from ..runner import (
    AppNoDisponible,
    DemasiadosJobs,
    ErrorDeEjecucion,
    JobRunner,
    NoEstaListo,
    YaEstaCorriendo,
)
from ..scheduler import (
    ErrorDeProgramacion,
    calcular_siguiente,
    validar_programacion,
    zona_de,
)
from ..security import verificar_password
from ..workspace import UserWorkspace
from . import schemas
from .deps import ConfiguradorDep, DbDep, SettingsDep, UsuarioOperativoDep
from .errors import (
    ApiError,
    conflicto,
    error_de_validacion,
    no_encontrado,
    prohibido,
    solicitud_invalida,
)

router = APIRouter(prefix="/me", tags=["me"])

LIMITE_WATCHES = 100
LIMITE_HOLDINGS = 200


# ---------------------------------------------------------------------------
# Notificaciones
# ---------------------------------------------------------------------------


def _salida_notificaciones(db, user_id: str) -> schemas.NotificacionesOut:
    destinos = config_service.destinos_de(db, user_id)
    preferencias: dict[str, list[str]] = {}
    soportados: dict[str, list[str]] = {}
    for app_name, spec in watchers.WATCHERS.items():
        activos = config_service.canales_activos_de(db, user_id, app_name)
        preferencias[app_name] = [c for c in CHANNELS if c in activos]
        soportados[app_name] = list(spec.canales_soportados)
    return schemas.NotificacionesOut(
        whatsapp=destinos.get(CHANNEL_WHATSAPP) or None,
        email=destinos.get(CHANNEL_EMAIL) or None,
        preferences=preferencias,
        supported=soportados,
    )


@router.get("/notifications", response_model=schemas.NotificacionesOut)
def ver_notificaciones(db: DbDep, usuario: ConfiguradorDep):
    return _salida_notificaciones(db, usuario.id)


@router.put("/notifications", response_model=schemas.NotificacionesOut)
def guardar_notificaciones(
    datos: schemas.NotificacionesIn, db: DbDep, usuario: ConfiguradorDep
):
    """Guarda los destinos. Una cadena vacía borra el canal."""
    destinos = {"whatsapp": datos.whatsapp, "email": datos.email}
    existentes = {
        c.channel: c
        for c in db.scalars(
            select(NotificationChannel).where(NotificationChannel.user_id == usuario.id)
        )
    }
    for canal, destino in destinos.items():
        fila = existentes.get(canal)
        if not destino:
            if fila is not None:
                db.delete(fila)
            continue
        if fila is None:
            db.add(
                NotificationChannel(
                    user_id=usuario.id, channel=canal, destination=destino
                )
            )
        elif fila.destination != destino:
            fila.destination = destino
            fila.updated_at = utcnow()
            # Cambiar el destino invalida cualquier verificación previa.
            fila.verified_at = None
    db.flush()
    return _salida_notificaciones(db, usuario.id)


@router.put("/notifications/preferences", response_model=schemas.NotificacionesOut)
def guardar_preferencias(
    datos: schemas.PreferenciasIn, db: DbDep, usuario: ConfiguradorDep
):
    """Reemplaza los canales activos de una app."""
    spec = watchers.spec_de(datos.app_name)
    if spec is None:
        raise no_encontrado("Esa aplicación no existe.")

    no_soportados = [c for c in datos.channels if c not in spec.canales_soportados]
    if no_soportados:
        # Aceptarlo en silencio haría creer que el aviso va a llegar.
        raise error_de_validacion(
            {
                "channels": f"{spec.display_name} no puede notificar por "
                f"{', '.join(no_soportados)}."
            }
        )

    existentes = {
        p.channel: p
        for p in db.scalars(
            select(AppChannelPref).where(
                AppChannelPref.user_id == usuario.id,
                AppChannelPref.app_name == datos.app_name,
            )
        )
    }
    for canal in CHANNELS:
        activo = canal in datos.channels
        fila = existentes.get(canal)
        if fila is None:
            db.add(
                AppChannelPref(
                    user_id=usuario.id,
                    app_name=datos.app_name,
                    channel=canal,
                    enabled=activo,
                )
            )
        else:
            fila.enabled = activo
    db.flush()
    return _salida_notificaciones(db, usuario.id)


# ---------------------------------------------------------------------------
# StockWatcher: watches
# ---------------------------------------------------------------------------


def _buscar_watch(db, user_id: str, watch_id: str) -> StockWatch:
    """Busca un watch **del usuario**.

    Si el id existe pero es de otra persona se devuelve 404 igual que si no
    existiera: un 403 confirmaría que el recurso existe.
    """
    watch = db.get(StockWatch, watch_id)
    if watch is None or watch.user_id != user_id:
        raise no_encontrado("No se encontró ese producto vigilado.")
    return watch


def _aplicar_watch(watch: StockWatch, datos: schemas.WatchIn) -> None:
    watch.name = datos.name
    watch.enabled = datos.enabled
    watch.match_terms = datos.match_terms
    watch.exclude_terms = datos.exclude_terms
    watch.variants = datos.variants
    watch.colors = datos.colors
    watch.countries = datos.countries or ["US"]
    watch.notify_channels = datos.notify_channels or [watchers.CHANNEL_WHATSAPP]
    watch.gender = datos.gender
    watch.max_price = datos.max_price
    watch.currency = datos.currency
    watch.updated_at = utcnow()


def _exigir_nombre_libre(db, user_id: str, nombre: str, *, excepto: str = "") -> None:
    """Dos watches con el mismo nombre son indistinguibles en los avisos."""
    choque = db.scalar(
        select(StockWatch).where(
            StockWatch.user_id == user_id,
            func.lower(StockWatch.name) == nombre.lower(),
            StockWatch.id != excepto,
        )
    )
    if choque is not None:
        raise conflicto(
            f"Ya tienes un producto vigilado llamado «{nombre}».",
            code="nombre_duplicado",
        )


@router.get("/stockwatcher/watches", response_model=schemas.WatchesOut)
def listar_watches(db: DbDep, usuario: ConfiguradorDep):
    return schemas.WatchesOut(
        items=config_service.watches_de(db, usuario.id), limit=LIMITE_WATCHES
    )


@router.post("/stockwatcher/watches", response_model=schemas.WatchOut, status_code=201)
def crear_watch(datos: schemas.WatchIn, db: DbDep, usuario: ConfiguradorDep):
    actuales = config_service.watches_de(db, usuario.id)
    if len(actuales) >= LIMITE_WATCHES:
        raise conflicto(
            f"Has alcanzado el límite de {LIMITE_WATCHES} productos vigilados.",
            code="limite_alcanzado",
        )
    _exigir_nombre_libre(db, usuario.id, datos.name)
    watch = StockWatch(user_id=usuario.id, position=len(actuales))
    _aplicar_watch(watch, datos)
    db.add(watch)
    db.flush()
    return watch


@router.get("/stockwatcher/watches/{watch_id}", response_model=schemas.WatchOut)
def ver_watch(watch_id: str, db: DbDep, usuario: ConfiguradorDep):
    return _buscar_watch(db, usuario.id, watch_id)


@router.put("/stockwatcher/watches/{watch_id}", response_model=schemas.WatchOut)
def editar_watch(
    watch_id: str, datos: schemas.WatchIn, db: DbDep, usuario: ConfiguradorDep
):
    watch = _buscar_watch(db, usuario.id, watch_id)
    _exigir_nombre_libre(db, usuario.id, datos.name, excepto=watch.id)
    _aplicar_watch(watch, datos)
    db.flush()
    return watch


@router.delete("/stockwatcher/watches/{watch_id}", status_code=204)
def borrar_watch(watch_id: str, db: DbDep, usuario: ConfiguradorDep) -> None:
    db.delete(_buscar_watch(db, usuario.id, watch_id))


@router.put("/stockwatcher/watches", response_model=schemas.WatchesOut)
def reordenar_watches(datos: schemas.ReordenarIn, db: DbDep, usuario: ConfiguradorDep):
    watches = {w.id: w for w in config_service.watches_de(db, usuario.id)}
    if set(datos.ids) != set(watches):
        raise solicitud_invalida(
            "La lista de orden debe incluir exactamente tus productos vigilados."
        )
    for posicion, watch_id in enumerate(datos.ids):
        watches[watch_id].position = posicion
    db.flush()
    return schemas.WatchesOut(
        items=config_service.watches_de(db, usuario.id), limit=LIMITE_WATCHES
    )


# ---------------------------------------------------------------------------
# PortfolioWatcher
# ---------------------------------------------------------------------------


def _perfil_o_crear(db, user_id: str) -> PortfolioProfile:
    perfil = db.get(PortfolioProfile, user_id)
    if perfil is None:
        perfil = PortfolioProfile(user_id=user_id)
        db.add(perfil)
        db.flush()
    return perfil


def _salida_portafolio(db, user_id: str) -> schemas.PortafolioOut:
    holdings = config_service.holdings_de(db, user_id)
    return schemas.PortafolioOut(
        profile=schemas.PerfilRiesgoOut.model_validate(_perfil_o_crear(db, user_id)),
        holdings=[schemas.HoldingOut.model_validate(h) for h in holdings],
        closed_positions=[
            schemas.PosicionCerradaOut.model_validate(c)
            for c in config_service.cerradas_de(db, user_id)
        ],
        cost_basis_total=round(sum(h.quantity * h.avg_cost for h in holdings), 2),
    )


@router.get("/portfolio", response_model=schemas.PortafolioOut)
def ver_portafolio(db: DbDep, usuario: ConfiguradorDep):
    return _salida_portafolio(db, usuario.id)


@router.put("/portfolio/profile", response_model=schemas.PerfilRiesgoOut)
def guardar_perfil(datos: schemas.PerfilRiesgoIn, db: DbDep, usuario: ConfiguradorDep):
    perfil = _perfil_o_crear(db, usuario.id)
    perfil.horizon = datos.horizon
    perfil.tolerance = datos.tolerance
    perfil.notes = datos.notes
    perfil.analysis_interval_days = datos.analysis_interval_days
    perfil.updated_at = utcnow()
    db.flush()
    return perfil


def _buscar_holding(db, user_id: str, holding_id: str) -> PortfolioHolding:
    holding = db.get(PortfolioHolding, holding_id)
    if holding is None or holding.user_id != user_id:
        raise no_encontrado("No se encontró esa posición.")
    return holding


@router.post("/portfolio/holdings", response_model=schemas.HoldingOut, status_code=201)
def crear_holding(datos: schemas.HoldingIn, db: DbDep, usuario: ConfiguradorDep):
    actuales = config_service.holdings_de(db, usuario.id)
    if len(actuales) >= LIMITE_HOLDINGS:
        raise conflicto(
            f"Has alcanzado el límite de {LIMITE_HOLDINGS} posiciones.",
            code="limite_alcanzado",
        )
    if any(h.ticker == datos.ticker for h in actuales):
        raise conflicto(
            f"Ya tienes una posición en {datos.ticker}. Edítala en vez de duplicarla.",
            code="ticker_duplicado",
        )
    holding = PortfolioHolding(
        user_id=usuario.id,
        ticker=datos.ticker,
        quantity=datos.quantity,
        avg_cost=datos.avg_cost,
        sector_hint=datos.sector_hint,
    )
    db.add(holding)
    db.flush()
    return holding


@router.put("/portfolio/holdings/{holding_id}", response_model=schemas.HoldingOut)
def editar_holding(
    holding_id: str, datos: schemas.HoldingIn, db: DbDep, usuario: ConfiguradorDep
):
    holding = _buscar_holding(db, usuario.id, holding_id)
    duplicado = any(
        h.ticker == datos.ticker and h.id != holding_id
        for h in config_service.holdings_de(db, usuario.id)
    )
    if duplicado:
        raise conflicto(
            f"Ya tienes otra posición en {datos.ticker}.", code="ticker_duplicado"
        )
    holding.ticker = datos.ticker
    holding.quantity = datos.quantity
    holding.avg_cost = datos.avg_cost
    holding.sector_hint = datos.sector_hint
    holding.updated_at = utcnow()
    db.flush()
    return holding


@router.delete("/portfolio/holdings/{holding_id}", status_code=204)
def borrar_holding(holding_id: str, db: DbDep, usuario: ConfiguradorDep) -> None:
    db.delete(_buscar_holding(db, usuario.id, holding_id))
    return schemas.OkOut(mensaje="Posición eliminada.")


def _buscar_cerrada(db, user_id: str, cerrada_id: str) -> PortfolioClosedPosition:
    fila = db.get(PortfolioClosedPosition, cerrada_id)
    if fila is None or fila.user_id != user_id:
        raise no_encontrado("No se encontró esa posición cerrada.")
    return fila


@router.post(
    "/portfolio/closed-positions",
    response_model=schemas.PosicionCerradaOut,
    status_code=201,
)
def crear_cerrada(datos: schemas.PosicionCerradaIn, db: DbDep, usuario: ConfiguradorDep):
    if any(c.ticker == datos.ticker for c in config_service.cerradas_de(db, usuario.id)):
        raise conflicto(
            f"{datos.ticker} ya está en tus posiciones cerradas.",
            code="ticker_duplicado",
        )
    fila = PortfolioClosedPosition(
        user_id=usuario.id, ticker=datos.ticker, note=datos.note
    )
    db.add(fila)
    db.flush()
    return fila


@router.put(
    "/portfolio/closed-positions/{cerrada_id}",
    response_model=schemas.PosicionCerradaOut,
)
def editar_cerrada(
    cerrada_id: str, datos: schemas.PosicionCerradaIn, db: DbDep, usuario: ConfiguradorDep
):
    fila = _buscar_cerrada(db, usuario.id, cerrada_id)
    fila.ticker = datos.ticker
    fila.note = datos.note
    db.flush()
    return fila


@router.delete("/portfolio/closed-positions/{cerrada_id}", status_code=204)
def borrar_cerrada(cerrada_id: str, db: DbDep, usuario: ConfiguradorDep) -> None:
    db.delete(_buscar_cerrada(db, usuario.id, cerrada_id))


# ---------------------------------------------------------------------------
# Transparencia
# ---------------------------------------------------------------------------


@router.get("/apps/{app_name}/config-preview", response_model=schemas.PreviewOut)
def previsualizar_config(
    app_name: str, db: DbDep, settings: SettingsDep, usuario: ConfiguradorDep
):
    """El YAML que se le pasaría al watcher con la configuración actual.

    Devuelve transparencia sin reabrir la edición de YAML a mano. No escribe
    nada en disco: solo calcula la ruta de destino para mostrarla.
    """
    spec = watchers.spec_de(app_name)
    if spec is None:
        raise no_encontrado("Esa aplicación no existe.")
    destino = UserWorkspace.para(settings, usuario.id).ruta_config(
        app_name, spec.config_filename
    )
    return schemas.PreviewOut(
        app_name=app_name,
        filename=spec.config_filename,
        path=str(destino),
        yaml=config_service.previsualizar(db, settings, usuario, app_name),
    )


def _readiness_out(db, usuario, app_name: str) -> schemas.ReadinessAppOut:
    spec = watchers.spec_de(app_name)
    estado = config_service.evaluar_readiness(db, usuario, app_name)
    return schemas.ReadinessAppOut(
        app_name=app_name,
        display_name=spec.display_name if spec else app_name,
        ready=estado.listo,
        reasons=[
            schemas.MotivoOut(code=m.code, message=m.message) for m in estado.motivos
        ],
    )


@router.get("/readiness", response_model=schemas.ReadinessGlobalOut)
def ver_readiness_global(db: DbDep, usuario: ConfiguradorDep):
    """Estado de todas las apps de una sola vez.

    La pantalla de inicio las necesita juntas; pedirlas una por una
    multiplicaría las peticiones desde el móvil.
    """
    return schemas.ReadinessGlobalOut(
        apps={
            nombre: _readiness_out(db, usuario, nombre) for nombre in watchers.WATCHERS
        }
    )


@router.get("/apps/{app_name}/readiness", response_model=schemas.ReadinessAppOut)
def ver_readiness(app_name: str, db: DbDep, usuario: ConfiguradorDep):
    if not watchers.es_watcher_conocido(app_name):
        raise no_encontrado("Esa aplicación no existe.")
    return _readiness_out(db, usuario, app_name)


@router.delete("/data", status_code=204)
def borrar_mis_datos(
    datos: schemas.ConfirmarPasswordIn,
    db: DbDep,
    settings: SettingsDep,
    usuario: ConfiguradorDep,
) -> None:
    """Borra toda la configuración del usuario sin borrar la cuenta.

    Se exige la contraseña: es una acción irreversible y la cookie de sesión
    por sí sola no basta para autorizarla.
    """
    if not verificar_password(usuario.password_hash, datos.password):
        raise prohibido("La contraseña no es correcta.", code="password_invalida")

    for modelo in (
        StockWatch,
        PortfolioHolding,
        PortfolioClosedPosition,
        NotificationChannel,
        AppChannelPref,
        PortfolioProfile,
        # Sin esto la automatización seguiría disparándose contra una
        # configuración que ya no existe.
        Schedule,
    ):
        db.execute(delete(modelo).where(modelo.user_id == usuario.id))
    UserWorkspace.para(settings, usuario.id).eliminar()


# ---------------------------------------------------------------------------
# Ejecuciones
# ---------------------------------------------------------------------------


def _runner(request: Request) -> JobRunner:
    return request.app.state.runner


def _app_out(request: Request, db, usuario, app_name: str) -> schemas.AppOut:
    runner = _runner(request)
    spec = watchers.spec_de(app_name)
    definicion = runner.app_de(app_name)
    ultima = db.scalars(
        select(JobRun)
        .where(JobRun.user_id == usuario.id, JobRun.app_name == app_name)
        .order_by(JobRun.started_at.desc())
        .limit(1)
    ).first()
    proxima = db.scalars(
        select(Schedule.next_run_at)
        .where(
            Schedule.user_id == usuario.id,
            Schedule.app_name == app_name,
            Schedule.enabled.is_(True),
            Schedule.next_run_at.is_not(None),
        )
        .order_by(Schedule.next_run_at)
        .limit(1)
    ).first()
    return schemas.AppOut(
        app_name=app_name,
        display_name=spec.display_name if spec else app_name,
        installed=bool(definicion and definicion.is_installed),
        running=runner.esta_corriendo(usuario.id, app_name),
        commands=[
            schemas.ComandoOut(key=c.key, label=c.label)
            for c in (definicion.commands if definicion else [])
        ],
        readiness=_readiness_out(db, usuario, app_name),
        last_run=schemas.EjecucionOut.model_validate(ultima) if ultima else None,
        next_run_at=proxima,
    )


@router.get("/apps", response_model=schemas.AppsOut)
def listar_apps(request: Request, db: DbDep, usuario: ConfiguradorDep):
    """Todo lo que la pantalla de inicio necesita, en una sola llamada."""
    return schemas.AppsOut(
        items=[
            _app_out(request, db, usuario, nombre) for nombre in watchers.WATCHERS
        ]
    )


@router.post(
    "/apps/{app_name}/runs", response_model=schemas.EjecucionOut, status_code=201
)
def lanzar_ejecucion(
    app_name: str,
    datos: schemas.LanzarIn,
    request: Request,
    db: DbDep,
    usuario: UsuarioOperativoDep,
):
    if not watchers.es_watcher_conocido(app_name):
        raise no_encontrado("Esa aplicación no existe.")
    try:
        return _runner(request).lanzar(
            db, usuario, app_name, datos.command_key, dry_run=datos.dry_run
        )
    except YaEstaCorriendo as exc:
        raise conflicto(str(exc), code=exc.codigo) from exc
    except DemasiadosJobs as exc:
        raise ApiError(503, exc.codigo, str(exc)) from exc
    except NoEstaListo as exc:
        raise conflicto(str(exc), code=exc.codigo) from exc
    except AppNoDisponible as exc:
        raise no_encontrado(str(exc)) from exc
    except ErrorDeEjecucion as exc:
        raise ApiError(500, exc.codigo, str(exc)) from exc


@router.delete("/apps/{app_name}/runs/current", status_code=204)
def cancelar_ejecucion(
    app_name: str, request: Request, usuario: UsuarioOperativoDep
) -> None:
    if not _runner(request).cancelar(usuario.id, app_name):
        raise no_encontrado("No tienes ninguna ejecución en curso para esa app.")


@router.get("/runs", response_model=schemas.EjecucionesOut)
def listar_ejecuciones(
    db: DbDep,
    usuario: ConfiguradorDep,
    app_name: str | None = None,
    status: str | None = None,
    limit: int = Query(default=30, ge=1, le=200),
):
    consulta = select(JobRun).where(JobRun.user_id == usuario.id)
    if app_name:
        consulta = consulta.where(JobRun.app_name == app_name)
    if status:
        consulta = consulta.where(JobRun.status == status)
    filas = db.scalars(
        consulta.order_by(JobRun.started_at.desc(), JobRun.id.desc()).limit(limit)
    ).all()
    return schemas.EjecucionesOut(items=list(filas))


def _buscar_run(db, user_id: str, run_id: int) -> JobRun:
    """Una corrida ajena responde 404: un 403 confirmaría que existe."""
    run = db.get(JobRun, run_id)
    if run is None or run.user_id != user_id:
        raise no_encontrado("No se encontró esa ejecución.")
    return run


@router.get("/runs/{run_id}", response_model=schemas.EjecucionOut)
def ver_ejecucion(run_id: int, db: DbDep, usuario: ConfiguradorDep):
    return _buscar_run(db, usuario.id, run_id)


@router.get("/runs/{run_id}/log", response_model=schemas.LogOut)
def ver_log(
    run_id: int,
    request: Request,
    db: DbDep,
    usuario: ConfiguradorDep,
    lines: int = Query(default=200, ge=1, le=5000),
):
    run = _buscar_run(db, usuario.id, run_id)
    return schemas.LogOut(
        run_id=run.id,
        status=run.status,
        content=_runner(request).tail(run, lines),
        running=run.status == JOB_RUNNING,
    )


# ---------------------------------------------------------------------------
# Automatización
# ---------------------------------------------------------------------------


def _comandos_de(request: Request, app_name: str) -> dict[str, str]:
    definicion = _runner(request).app_de(app_name)
    return {c.key: c.label for c in (definicion.commands if definicion else [])}


def _programacion_out(
    schedule: Schedule, etiquetas: dict[str, str]
) -> schemas.ProgramacionOut:
    return schemas.ProgramacionOut(
        app_name=schedule.app_name,
        command_key=schedule.command_key,
        command_label=etiquetas.get(schedule.command_key, schedule.command_key),
        enabled=schedule.enabled,
        kind=schedule.kind,
        interval_minutes=schedule.interval_minutes,
        cron_expr=schedule.cron_expr,
        next_run_at=schedule.next_run_at,
        last_run_at=schedule.last_run_at,
    )


@router.get("/schedules", response_model=schemas.ProgramacionesOut)
def listar_programaciones(request: Request, db: DbDep, usuario: ConfiguradorDep):
    filas = db.scalars(
        select(Schedule)
        .where(Schedule.user_id == usuario.id)
        .order_by(Schedule.app_name, Schedule.command_key)
    ).all()
    etiquetas = {
        nombre: _comandos_de(request, nombre) for nombre in watchers.WATCHERS
    }
    return schemas.ProgramacionesOut(
        items=[
            _programacion_out(s, etiquetas.get(s.app_name, {})) for s in filas
        ],
        timezone=usuario.timezone,
    )


@router.put(
    "/schedules/{app_name}/{command_key}", response_model=schemas.ProgramacionOut
)
def guardar_programacion(
    app_name: str,
    command_key: str,
    datos: schemas.ProgramacionIn,
    request: Request,
    db: DbDep,
    usuario: ConfiguradorDep,
):
    """Crea o actualiza la programación de un comando.

    Se acepta programar aunque el usuario todavía no esté listo para ejecutar:
    dejar la automatización armada mientras se completa la configuración es
    parte del onboarding. El pre-vuelo del scheduler decide en cada disparo.
    """
    if not watchers.es_watcher_conocido(app_name):
        raise no_encontrado("Esa aplicación no existe.")

    etiquetas = _comandos_de(request, app_name)
    if etiquetas and command_key not in etiquetas:
        raise error_de_validacion(
            {"command_key": "Comando desconocido."},
            "Ese comando no existe para esta aplicación.",
        )

    try:
        validar_programacion(datos.kind, datos.interval_minutes, datos.cron_expr)
    except ErrorDeProgramacion as exc:
        campo = "cron_expr" if datos.kind == SCHEDULE_CRON else "interval_minutes"
        raise error_de_validacion({campo: str(exc)}, str(exc)) from exc

    schedule = db.scalars(
        select(Schedule).where(
            Schedule.user_id == usuario.id,
            Schedule.app_name == app_name,
            Schedule.command_key == command_key,
        )
    ).first()
    if schedule is None:
        schedule = Schedule(
            user_id=usuario.id, app_name=app_name, command_key=command_key
        )
        db.add(schedule)

    schedule.enabled = datos.enabled
    schedule.kind = datos.kind
    schedule.interval_minutes = (
        datos.interval_minutes if datos.kind == SCHEDULE_INTERVAL else None
    )
    schedule.cron_expr = datos.cron_expr if datos.kind == SCHEDULE_CRON else None
    schedule.next_run_at = calcular_siguiente(
        schedule, zona_de(usuario, request.app.state.settings)
    )
    schedule.updated_at = utcnow()
    db.flush()
    return _programacion_out(schedule, etiquetas)


@router.delete("/schedules/{app_name}/{command_key}", status_code=204)
def borrar_programacion(
    app_name: str, command_key: str, db: DbDep, usuario: ConfiguradorDep
) -> None:
    schedule = db.scalars(
        select(Schedule).where(
            Schedule.user_id == usuario.id,
            Schedule.app_name == app_name,
            Schedule.command_key == command_key,
        )
    ).first()
    if schedule is None:
        raise no_encontrado("No tienes esa automatización configurada.")
    db.delete(schedule)


@router.put("/timezone", response_model=schemas.ProgramacionesOut)
def cambiar_zona_horaria(
    datos: schemas.ZonaHorariaIn,
    request: Request,
    db: DbDep,
    usuario: ConfiguradorDep,
):
    """Cambia la zona horaria y recalcula lo programado con cron.

    Sin el recálculo, un «diario a las 8:00» seguiría disparándose a la hora
    de la zona anterior hasta la siguiente edición manual.
    """
    usuario.timezone = datos.timezone
    zona = zona_de(usuario, request.app.state.settings)
    filas = db.scalars(
        select(Schedule)
        .where(Schedule.user_id == usuario.id)
        .order_by(Schedule.app_name, Schedule.command_key)
    ).all()
    for schedule in filas:
        if schedule.kind == SCHEDULE_CRON:
            schedule.next_run_at = calcular_siguiente(schedule, zona)
            schedule.updated_at = utcnow()
    db.flush()
    etiquetas = {
        nombre: _comandos_de(request, nombre) for nombre in watchers.WATCHERS
    }
    return schemas.ProgramacionesOut(
        items=[
            _programacion_out(s, etiquetas.get(s.app_name, {})) for s in filas
        ],
        timezone=usuario.timezone,
    )
