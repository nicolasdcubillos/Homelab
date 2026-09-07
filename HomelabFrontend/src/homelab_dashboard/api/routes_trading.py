"""Rutas del módulo de trading: `/api/v1/trading/*`.

Este es el único rincón de la API que trabaja sobre un recurso **compartido**.
En `/me/*` el `user_id` sale de la sesión y nadie ve lo ajeno; aquí, en cambio,
todos los autorizados miran y editan la *misma* fila. Eso obliga a tres cosas
que el resto de la API no necesita:

1. **Bloqueo optimista.** Cada mutación manda la `version` que leyó. Si ya no
   coincide, se responde 409 en vez de pisar en silencio el cambio de otro.
   La `version` cubre la fila entera, no solo la configuración: encender el bot
   también la sube, porque también es un cambio que los demás deben ver.
2. **Auditoría de todo lo que muta.** En `/me/*` basta con que el dato quede
   guardado, porque su dueño es evidente. Aquí no: la única forma de responder
   "quién apagó el bot" es el `audit_log`.
3. **Dos niveles de permiso.** `viewer` mira, `operator` toca. Ver `deps.py`.

Reconciliación con el motor
---------------------------
El interruptor guarda **intención**, no resultado. Si el motor no responde al
encenderlo, la intención se guarda igual y la respuesta lo refleja en
`estado.alcanzable=false` con el detalle del fallo, en vez de devolver un error
y dejar al usuario sin saber qué quedó guardado. Es coherente con el diseño de
`trading.py`: la base declara lo que se quiere, el motor reporta lo que hay, y
la UI muestra ambas cosas cuando difieren.
"""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Query, Request
from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert

from .. import trading
from ..admin import registrar
from ..db import utcnow
from ..models import TradingAccess, TradingBotConfig, User
from . import schemas
from .deps import AdminDep, DbDep, SettingsDep, TradingLectorDep, TradingOperadorDep
from .errors import conflicto, error_de_validacion, no_encontrado

router = APIRouter(prefix="/trading", tags=["trading"])


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------


def _spec_o_404(bot_name: str) -> trading.MotorSpec:
    spec = trading.spec_de(bot_name)
    if spec is None:
        raise no_encontrado("Ese motor de trading no existe.")
    return spec


def _fila(db, spec: trading.MotorSpec) -> TradingBotConfig:
    """Devuelve la fila del motor, creándola apagada la primera vez.

    Se crea al vuelo en vez de sembrarla en la migración para que añadir un
    motor nuevo sea solo tocar el registro de `trading.py`, sin migración.
    """
    fila = db.get(TradingBotConfig, spec.bot_name)
    if fila is not None:
        return fila
    db.execute(
        insert(TradingBotConfig)
        .values(
            bot_name=spec.bot_name,
            enabled=False,
            config_json=dict(trading.CONFIG_POR_DEFECTO),
        )
        .on_conflict_do_nothing(index_elements=["bot_name"])
    )
    fila = db.get(TradingBotConfig, spec.bot_name)
    assert fila is not None
    return fila


def _adaptador(request: Request, spec: trading.MotorSpec, settings, *, habilitado: bool):
    """Construye el adaptador del motor, salvo que los tests hayan puesto otro.

    Mismo truco que usa `runner` con `app.state`: en producción se construye el
    adaptador real; en los tests se inyecta un doble y así la suite nunca abre
    un socket ni depende de que Freqtrade esté instalado.
    """
    fabrica = getattr(request.app.state, "trading_adaptadores", None)
    if fabrica is not None:
        return fabrica(spec, settings, habilitado=habilitado)
    return trading.construir_adaptador(spec, settings, habilitado=habilitado)


def _estado(adaptador) -> schemas.EstadoMotorOut:
    """Consulta el estado del motor sin dejar que un fallo tumbe la respuesta.

    Que el motor esté caído es información, no un error de la API: la UI tiene
    que poder pintar la configuración aunque el bot no esté arriba.
    """
    try:
        estado = adaptador.estado()
        return schemas.EstadoMotorOut(**asdict(estado))
    except (trading.ErrorDeMotor, ValueError, TypeError, KeyError) as exc:
        estado = trading.EstadoMotor.caido(str(exc))
        return schemas.EstadoMotorOut(**asdict(estado))


def _info(spec: trading.MotorSpec) -> schemas.MotorInfoOut:
    singular, plural = spec.termino_instrumento
    return schemas.MotorInfoOut(
        bot_name=spec.bot_name,
        display_name=spec.display_name,
        proyecto=spec.proyecto,
        clase_activo=spec.clase_activo,
        termino_singular=singular,
        termino_plural=plural,
        ejemplo_instrumento=spec.ejemplo_instrumento,
        timeframes=list(spec.timeframes),
        max_instrumentos=spec.max_instrumentos,
        simula_contra=spec.simula_contra,
        permite_encender=spec.permite_encender,
        motivo_bloqueo=spec.motivo_bloqueo,
        estrategias=[
            schemas.EstrategiaInfoOut(
                nombre=e.nombre, etiqueta=e.etiqueta, descripcion=e.descripcion
            )
            for e in spec.estrategias
        ],
    )


def _config_out(fila: TradingBotConfig) -> schemas.ConfigTradingOut:
    datos = {**trading.CONFIG_POR_DEFECTO, **(fila.config_json or {})}
    return schemas.ConfigTradingOut(**{
        campo: datos[campo] for campo in trading.CONFIG_POR_DEFECTO
    })


def _salida(
    spec: trading.MotorSpec, fila: TradingBotConfig, estado: schemas.EstadoMotorOut
) -> schemas.BotTradingOut:
    return schemas.BotTradingOut(
        motor=_info(spec),
        enabled=fila.enabled,
        modo=fila.mode,
        config=_config_out(fila),
        config_aplicada=(
            spec.bot_name == trading.BOT_LUMIBOT
            and estado.alcanzable
            and estado.estado in {"operando", "pausado", "esperando"}
            and estado.config_version == fila.version
        ),
        version=fila.version,
        estado=estado,
        updated_by_email=fila.updated_by_email or "",
        updated_at=fila.updated_at,
    )


def _exigir_version(fila: TradingBotConfig, version: int) -> None:
    if fila.version != version:
        raise conflicto(
            f"Otra persona modificó este bot mientras editabas "
            f"(iba por la versión {fila.version} y enviaste la {version}). "
            "Recarga para ver los cambios y vuelve a intentarlo.",
            code="trading_version_desactualizada",
        )


def _marcar(db, fila: TradingBotConfig, contexto, **cambios) -> None:
    """Compara y escribe en una sola sentencia; no basta comparar en Python."""
    resultado = db.execute(
        update(TradingBotConfig)
        .where(
            TradingBotConfig.bot_name == fila.bot_name,
            TradingBotConfig.version == fila.version,
        )
        .values(
            **cambios,
            version=fila.version + 1,
            updated_by_user_id=contexto.usuario.id,
            updated_by_email=contexto.usuario.email,
            updated_at=utcnow(),
        )
        .execution_options(synchronize_session=False)
    )
    if resultado.rowcount != 1:
        raise conflicto(
            "Otra persona modificó este bot. Recarga antes de volver a guardar.",
            code="trading_version_desactualizada",
        )
    db.refresh(fila)


def _exigir_datos_observados(adaptador) -> None:
    estado = _estado(adaptador)
    if (
        not estado.alcanzable or estado.modo != "paper"
        or estado.estado not in {"operando", "pausado", "esperando"}
    ):
        raise trading.ErrorDeMotor("El motor no confirma datos PAPER vigentes.")


# ---------------------------------------------------------------------------
# Lectura
# ---------------------------------------------------------------------------


@router.get("/bots", response_model=schemas.BotsTradingOut)
def listar_bots(request: Request, db: DbDep, settings: SettingsDep, acceso: TradingLectorDep):
    items = []
    for spec in trading.MOTORES.values():
        fila = _fila(db, spec)
        adaptador = _adaptador(request, spec, settings, habilitado=fila.enabled)
        items.append(_salida(spec, fila, _estado(adaptador)))
    return schemas.BotsTradingOut(items=items, nivel=acceso.nivel)


@router.get("/bots/{bot_name}", response_model=schemas.BotTradingOut)
def obtener_bot(
    bot_name: str,
    request: Request,
    db: DbDep,
    settings: SettingsDep,
    _acceso: TradingLectorDep,
):
    spec = _spec_o_404(bot_name)
    fila = _fila(db, spec)
    adaptador = _adaptador(request, spec, settings, habilitado=fila.enabled)
    return _salida(spec, fila, _estado(adaptador))


@router.get("/bots/{bot_name}/trades", response_model=schemas.OperacionesOut)
def listar_operaciones(
    bot_name: str,
    request: Request,
    db: DbDep,
    settings: SettingsDep,
    _acceso: TradingLectorDep,
    limit: int = Query(default=50, ge=1, le=200),
):
    spec = _spec_o_404(bot_name)
    fila = _fila(db, spec)
    adaptador = _adaptador(request, spec, settings, habilitado=fila.enabled)
    try:
        _exigir_datos_observados(adaptador)
        operaciones = adaptador.operaciones(limite=limit)
    except (trading.ErrorDeMotor, ValueError, TypeError, KeyError):
        # `disponible=False` distingue "no pude preguntar" de "no hay ninguna".
        return schemas.OperacionesOut(items=[], disponible=False)
    return schemas.OperacionesOut(
        items=[
            schemas.OperacionOut(
                instrumento=op.instrumento,
                lado=op.lado,
                cantidad=op.cantidad,
                precio_entrada=op.precio_entrada,
                precio_salida=op.precio_salida,
                pnl_absoluto=op.pnl_absoluto,
                pnl_pct=op.pnl_pct,
                abierta_en=op.abierta_en,
                cerrada_en=op.cerrada_en,
                abierta=op.abierta,
            )
            for op in operaciones
        ]
    )


@router.get("/bots/{bot_name}/performance", response_model=schemas.RendimientoOut)
def rendimiento(
    bot_name: str,
    request: Request,
    db: DbDep,
    settings: SettingsDep,
    _acceso: TradingLectorDep,
):
    spec = _spec_o_404(bot_name)
    fila = _fila(db, spec)
    capital = float(
        (fila.config_json or {}).get(
            "capital_simulado", trading.CONFIG_POR_DEFECTO["capital_simulado"]
        )
    )
    adaptador = _adaptador(request, spec, settings, habilitado=fila.enabled)
    try:
        _exigir_datos_observados(adaptador)
        datos = adaptador.rendimiento(capital)
        disponible = True
    except (trading.ErrorDeMotor, ValueError, TypeError, KeyError):
        datos = trading.Rendimiento.vacio(capital)
        disponible = False
    return schemas.RendimientoOut(
        capital_inicial=datos.capital_inicial,
        capital_actual=datos.capital_actual,
        pnl_absoluto=datos.pnl_absoluto,
        pnl_pct=datos.pnl_pct,
        operaciones_cerradas=datos.operaciones_cerradas,
        ganadoras=datos.ganadoras,
        perdedoras=datos.perdedoras,
        win_rate=datos.win_rate,
        mejor_pct=datos.mejor_pct,
        peor_pct=datos.peor_pct,
        costos_simulados=datos.costos_simulados,
        disponible=disponible,
    )


# ---------------------------------------------------------------------------
# Mutación
# ---------------------------------------------------------------------------


@router.put("/bots/{bot_name}/config", response_model=schemas.BotTradingOut)
def guardar_config(
    bot_name: str,
    datos: schemas.ConfigTradingIn,
    request: Request,
    db: DbDep,
    settings: SettingsDep,
    acceso: TradingOperadorDep,
):
    spec = _spec_o_404(bot_name)
    fila = _fila(db, spec)
    _exigir_version(fila, datos.version)

    propuesta = datos.model_dump(exclude={"version"})
    try:
        limpia = trading.validar_config(spec, propuesta)
    except trading.ErrorDeConfig as exc:
        raise error_de_validacion(exc.campos) from exc

    anterior = dict(fila.config_json or {})
    _marcar(db, fila, acceso, config_json=limpia)

    cambios = {
        clave: {"antes": anterior.get(clave), "despues": valor}
        for clave, valor in limpia.items()
        if anterior.get(clave) != valor
    }
    registrar(
        db,
        acceso.usuario,
        "trading.config_actualizada",
        bot_name=spec.bot_name,
        version=fila.version,
        por_admin=acceso.por_admin,
        cambios=cambios,
    )

    adaptador = _adaptador(request, spec, settings, habilitado=fila.enabled)
    return _salida(spec, fila, _estado(adaptador))


@router.post("/bots/{bot_name}/switch", response_model=schemas.BotTradingOut)
def interruptor(
    bot_name: str,
    datos: schemas.InterruptorIn,
    request: Request,
    db: DbDep,
    settings: SettingsDep,
    acceso: TradingOperadorDep,
):
    """Enciende o apaga el bot compartido.

    Encender exige que haya al menos un instrumento configurado: un motor sin
    nada que vigilar arrancaría, no haría nada y aparecería como "operando",
    que es la peor combinación posible para quien mira el panel.
    """
    spec = _spec_o_404(bot_name)
    fila = _fila(db, spec)
    _exigir_version(fila, datos.version)

    config = fila.config_json or {}
    if datos.enabled:
        try:
            trading.validar_config(spec, config)
        except trading.ErrorDeConfig as exc:
            raise error_de_validacion(exc.campos) from exc
    if datos.enabled and not config.get("instrumentos"):
        singular, plural = spec.termino_instrumento
        raise error_de_validacion(
            {"instrumentos": f"Agrega al menos un {singular} antes de encender el bot."},
            mensaje=f"El bot no tiene {plural} configurados.",
        )
    if datos.enabled and not spec.permite_encender:
        raise conflicto(spec.motivo_bloqueo, code="trading_activacion_bloqueada")

    _marcar(db, fila, acceso, enabled=datos.enabled)

    adaptador = _adaptador(request, spec, settings, habilitado=fila.enabled)
    fallo: str | None = None
    try:
        if datos.enabled:
            adaptador.encender()
        else:
            adaptador.apagar()
    except trading.ErrorDeMotor as exc:
        # La intención queda guardada igual: ver el docstring del módulo.
        fallo = str(exc)

    registrar(
        db,
        acceso.usuario,
        "trading.encendido" if datos.enabled else "trading.apagado",
        bot_name=spec.bot_name,
        version=fila.version,
        por_admin=acceso.por_admin,
        motor_respondio=fallo is None if spec.bot_name == trading.BOT_FREQTRADE else None,
        error=fallo,
    )

    estado = (
        schemas.EstadoMotorOut(
            alcanzable=False,
            corriendo=False,
            detalle=(
                f"Se guardó el cambio, pero el motor no respondió: {fallo}. "
                "El estado de ejecución no está confirmado."
            ),
            modo=fila.mode,
            posiciones_abiertas=None,
            estado="desconocido",
        )
        if fallo is not None
        else _estado(adaptador)
    )
    return _salida(spec, fila, estado)


# ---------------------------------------------------------------------------
# Accesos (solo admin)
# ---------------------------------------------------------------------------
#
# Viven aquí y no en `routes_admin.py` porque el permiso es del módulo de
# trading, no del panel de administración: quien mantenga esto espera
# encontrarlo junto al resto del trading. Se protegen con `AdminDep`, así que
# siguen siendo 404 para quien no es admin.


@router.get("/access", response_model=schemas.AccesosTradingOut)
def listar_accesos(db: DbDep, _admin: AdminDep):
    filas = db.scalars(
        select(TradingAccess).order_by(TradingAccess.granted_at.desc())
    ).all()
    return schemas.AccesosTradingOut(
        items=[
            schemas.AccesoTradingOut(
                user_id=fila.user_id,
                email=fila.user.email if fila.user else "",
                level=fila.level,
                granted_by_email=fila.granted_by_email or "",
                granted_at=fila.granted_at,
            )
            for fila in filas
        ]
    )


@router.put("/access/{user_id}", response_model=schemas.AccesoTradingOut)
def conceder_acceso(
    user_id: str,
    datos: schemas.AccesoTradingIn,
    db: DbDep,
    admin: AdminDep,
):
    objetivo = db.get(User, user_id)
    if objetivo is None:
        raise no_encontrado("No se encontró ese usuario.")

    fila = db.get(TradingAccess, user_id)
    nivel_anterior = fila.level if fila else None
    if fila is None:
        fila = TradingAccess(user_id=user_id, level=datos.level)
        db.add(fila)
    else:
        fila.level = datos.level
    fila.granted_by_user_id = admin.id
    fila.granted_by_email = admin.email
    fila.updated_at = utcnow()
    db.flush()

    registrar(
        db,
        admin,
        "trading.acceso_concedido",
        objetivo,
        level=datos.level,
        level_anterior=nivel_anterior,
    )
    return schemas.AccesoTradingOut(
        user_id=fila.user_id,
        email=objetivo.email,
        level=fila.level,
        granted_by_email=fila.granted_by_email or "",
        granted_at=fila.granted_at,
    )


@router.delete("/access/{user_id}", status_code=204)
def revocar_acceso(user_id: str, db: DbDep, admin: AdminDep):
    """Revocar es borrar la fila.

    No hay una columna `enabled` a propósito: un permiso "concedido pero
    desactivado" es un estado ambiguo que tarde o temprano alguien interpreta
    mal. O está la fila, o no hay acceso.
    """
    fila = db.get(TradingAccess, user_id)
    if fila is None:
        raise no_encontrado("Ese usuario no tiene acceso al trading.")
    objetivo = db.get(User, user_id)
    nivel = fila.level
    db.delete(fila)
    registrar(db, admin, "trading.acceso_revocado", objetivo, level=nivel)
