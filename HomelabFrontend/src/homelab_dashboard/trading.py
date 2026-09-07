"""Todo lo que el dashboard sabe de los motores de trading.

Este módulo es al trading lo que `watchers.py` es a StockWatcher y
PortfolioWatcher: **el único sitio donde vive el conocimiento del contrato** de
cada motor. Si mañana Freqtrade cambia su API o TradingLab cambia su esquema,
se toca aquí y en ningún otro lado.

Por qué dos motores
-------------------
No existe un bot open-source que haga bien cripto *y* acciones. Los más
maduros (Freqtrade, Hummingbot, Jesse, OctoBot) son **exclusivamente cripto**,
y los que operan acciones son librerías, no demonios. Así que se integran dos y
este módulo absorbe la diferencia:

- **Freqtrade** (`BOT_FREQTRADE`) — cripto. Es un demonio con API REST propia.
- **Lumibot**, vía la app hermana TradingLab (`BOT_LUMIBOT`) — acciones y ETFs.
  Es una librería embebida en un proceso nuestro, no un servicio.

Dos modelos de control, una sola interfaz
-----------------------------------------
Esa diferencia de naturaleza obliga a dos mecanismos de control distintos, y
conviene tenerlo claro porque es la asimetría central del módulo:

- **Freqtrade es imperativo**: se consulta por HTTP y solo se permite solicitar
  parada tras confirmar PAPER. El arranque está bloqueado: no existe un puente
  que aplique la configuración del dashboard al proceso.
- **TradingLab es declarativo**: el dashboard solo escribe la *intención* en
  `trading_bot_config.enabled`, y el proceso de TradingLab la consulta en cada
  ciclo y se ajusta. La intención vive en nuestra base; el estado observado y
  la versión procesada se publican en el latido de su propia SQLite.

`AdaptadorTrading` esconde las dos formas tras los mismos cinco métodos, de
modo que la API y la UI no sepan cuál es cuál.

Por qué nunca hay dinero real
-----------------------------
El módulo solo admite PAPER. No certifica la configuración de procesos externos:

1. **El esquema**: `trading_bot_config.mode` tiene un `CHECK` que solo admite
   `'paper'`. La base misma rechaza almacenar otra cosa (ver la migración
   `de02a901e6ae`).
2. **La validación**: `validar_config` rechaza cualquier clave que huela a
   ejecución real (`dry_run`, claves de API, `trading_mode`...), así que no se
   pueden colar por el JSON de configuración.
3. **El control cerrado**: Freqtrade no arranca desde el panel; sus lecturas y
   parada exigen `dry_run is True`. `config_freqtrade` genera un borrador PAPER,
   pero nadie lo aplica: no constituye una barrera de ejecución.

Es el mismo principio que en PortfolioWatcher ("nunca se genera una orden
ejecutable"), llevado a un módulo que sí opera: aquí se opera, pero contra una
cartera simulada, y el camino al dinero real no está construido.

Contrato de Freqtrade verificado en su documentación
----------------------------------------------------
Endpoints REST usados (`docs/rest-api.md` del repo de Freqtrade), todos bajo
`/api/v1` y con autenticación HTTP Basic:

- `GET  /ping`        — sonda de vida, es el único que no exige autenticación.
- `GET  /show_config` — `{"state": "running"|"stopped", "dry_run": true, ...}`.
- `POST /start`       — arranca el bucle de trading.
- `POST /stop`        — lo detiene (el proceso sigue vivo).
- `GET  /status`      — operaciones abiertas.
- `GET  /trades`      — histórico de operaciones cerradas.
- `GET  /profit`      — resumen de PnL acumulado.
"""

from __future__ import annotations

import datetime as dt
import logging
import math
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import httpx

from .db import utcnow
from .models import BOT_FREQTRADE, BOT_LUMIBOT, TRADING_MODE_PAPER

log = logging.getLogger(__name__)


class ErrorDeConfig(Exception):
    """La configuración propuesta no cumple el contrato del motor.

    Lleva `campos` con el mismo formato que usa `errors.error_de_validacion`
    para que la SPA pueda pintar cada mensaje junto a su input.
    """

    def __init__(self, campos: dict[str, str]) -> None:
        super().__init__("configuración de trading inválida")
        self.campos = campos


class ErrorDeMotor(Exception):
    """No se pudo hablar con el motor (caído, inalcanzable o respondió mal)."""


# ---------------------------------------------------------------------------
# Descripción declarativa de cada motor
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EstrategiaSpec:
    """Una estrategia que el motor sabe construir por nombre."""

    #: Identificador exacto que el motor espera. Va en la configuración.
    nombre: str
    #: Cómo se lee en la pantalla.
    etiqueta: str
    #: Una línea explicando cuándo compra y cuándo vende.
    descripcion: str


#: Estrategias que trae TradingLab. Duplican los `nombre` de
#: `tradinglab.estrategia.DISPONIBLES`: son un contrato entre dos procesos, y el
#: precio de que se desincronicen es rechazar una elección válida o guardar una
#: que el motor no construye. Un test compara contra el productor real del monorepo.
_ESTRATEGIAS_LUMIBOT = (
    EstrategiaSpec(
        nombre="cruce_medias",
        etiqueta="Cruce de medias",
        descripcion="Compra cuando la media corta cruza por encima de la larga.",
    ),
    EstrategiaSpec(
        nombre="reversion_rsi",
        etiqueta="Reversión RSI",
        descripcion="Compra en sobreventa y vende al recuperar el nivel medio.",
    ),
)


@dataclass(frozen=True)
class MotorSpec:
    """Lo que el dashboard necesita saber de un motor para tratarlo igual."""

    bot_name: str
    display_name: str
    #: Proyecto que hace el trabajo de verdad, para poder citarlo en la UI.
    proyecto: str
    #: "cripto" | "acciones". Determina el vocabulario de la UI.
    clase_activo: str
    #: Cómo se llama un instrumento en este motor, en singular y plural.
    termino_instrumento: tuple[str, str]
    #: Patrón que debe cumplir cada instrumento.
    patron_instrumento: re.Pattern[str]
    #: Ejemplo válido, que la UI muestra como placeholder.
    ejemplo_instrumento: str
    #: Marcos temporales admitidos, del más fino al más grueso.
    timeframes: tuple[str, ...]
    #: Tope de instrumentos simultáneos. No es capricho: cada par/ticker cuesta
    #: memoria y llamadas, y esto corre en una VM compartida con otras 3 apps.
    max_instrumentos: int
    #: Broker o exchange contra el que simula.
    simula_contra: str
    #: Estrategias conocidas, si el motor tiene un catálogo cerrado. Vacío
    #: significa "no lo tiene": en Freqtrade una estrategia es una clase Python
    #: que alguien deja en un directorio de la VM, así que el dashboard no puede
    #: saber cuáles existen y deja el campo abierto. Cuando la lista sí está,
    #: la UI muestra un selector y el backend rechaza cualquier otro valor.
    estrategias: tuple[EstrategiaSpec, ...] = ()
    permite_encender: bool = False
    motivo_bloqueo: str = "Este motor todavía no tiene un control seguro implementado."


_PATRON_PAR = re.compile(r"^[A-Z0-9]{2,10}/[A-Z0-9]{2,10}$")
_PATRON_TICKER = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


FREQTRADE = MotorSpec(
    bot_name=BOT_FREQTRADE,
    display_name="Cripto",
    proyecto="Freqtrade",
    clase_activo="cripto",
    termino_instrumento=("par", "pares"),
    patron_instrumento=_PATRON_PAR,
    ejemplo_instrumento="BTC/USDT",
    timeframes=("1m", "5m", "15m", "30m", "1h", "4h", "1d"),
    max_instrumentos=15,
    simula_contra="Binance (datos públicos, sin claves)",
    motivo_bloqueo=(
        "Activación bloqueada: la configuración guardada no se aplica a Freqtrade "
        "y el freno de pérdida diaria no está integrado."
    ),
)

LUMIBOT = MotorSpec(
    bot_name=BOT_LUMIBOT,
    display_name="Acciones y ETFs",
    proyecto="Lumibot",
    clase_activo="acciones",
    termino_instrumento=("ticker", "tickers"),
    patron_instrumento=_PATRON_TICKER,
    ejemplo_instrumento="AAPL",
    timeframes=("5m", "15m", "30m", "1h", "1d"),
    max_instrumentos=25,
    simula_contra="Simulador local; Alpaca Paper bloqueado preventivamente",
    estrategias=_ESTRATEGIAS_LUMIBOT,
    permite_encender=True,
    motivo_bloqueo="",
)

MOTORES: dict[str, MotorSpec] = {
    FREQTRADE.bot_name: FREQTRADE,
    LUMIBOT.bot_name: LUMIBOT,
}


def spec_de(bot_name: str) -> MotorSpec | None:
    return MOTORES.get(bot_name)


def es_motor_conocido(bot_name: str) -> bool:
    return bot_name in MOTORES


# ---------------------------------------------------------------------------
# Configuración compartida
# ---------------------------------------------------------------------------

#: Claves que jamás se aceptan en la configuración, con el motivo que se le
#: muestra a quien lo intente. Protegen la configuración compartida, no certifican
#: la de procesos externos (ver el docstring del módulo). Se rechazan de forma
#: explícita, y no ignorándolas en silencio, para que quede claro que es una
#: decisión de diseño y no un olvido.
CLAVES_PROHIBIDAS = {
    "dry_run": "El modo simulado no se puede desactivar desde aquí.",
    "live": "El modo real no está disponible en este módulo.",
    "trading_mode": "El modo de operación no es configurable.",
    "mode": "El modo de operación no es configurable.",
    "api_key": "Las credenciales no se guardan en la configuración.",
    "api_secret": "Las credenciales no se guardan en la configuración.",
    "secret": "Las credenciales no se guardan en la configuración.",
    "password": "Las credenciales no se guardan en la configuración.",
    "exchange_key": "Las credenciales no se guardan en la configuración.",
}

#: Valores por defecto de un motor recién creado. Deliberadamente conservadores:
#: pocos instrumentos, marco temporal amplio (menos ruido y menos CPU) y un
#: freno de pérdida diaria activo desde el minuto cero.
CONFIG_POR_DEFECTO: dict[str, Any] = {
    "instrumentos": [],
    "estrategia": "",
    "timeframe": "1h",
    "capital_simulado": 10_000.0,
    "max_posiciones_abiertas": 3,
    "stop_loss_pct": 5.0,
    "take_profit_pct": 10.0,
    "max_perdida_diaria_pct": 5.0,
}

_LIMITES_NUMERICOS = {
    # clave: (mínimo, máximo, etiqueta para el mensaje de error)
    "capital_simulado": (100.0, 10_000_000.0, "El capital simulado"),
    "stop_loss_pct": (0.1, 90.0, "El stop loss"),
    "take_profit_pct": (0.1, 500.0, "El take profit"),
    "max_perdida_diaria_pct": (0.1, 100.0, "La pérdida diaria máxima"),
}


def _es(valor: float) -> str:
    """Número legible en español: 10000000.0 -> «10.000.000»."""
    entero = f"{valor:,.2f}".rstrip("0").rstrip(".")
    # `,` y `.` van al revés que en inglés, así que se intercambian de una vez.
    return entero.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def validar_config(spec: MotorSpec, datos: dict[str, Any]) -> dict[str, Any]:
    """Normaliza y valida la configuración propuesta para un motor.

    Devuelve un diccionario limpio, listo para persistir, o lanza
    `ErrorDeConfig` con un mensaje por campo. Se validan **todos** los campos
    antes de lanzar, para que la UI pueda pintar de una vez todo lo que está
    mal en vez de obligar a descubrirlo error por error.
    """
    campos: dict[str, str] = {}

    for clave, motivo in CLAVES_PROHIBIDAS.items():
        if clave in datos:
            campos[clave] = motivo
    for clave in datos.keys() - CONFIG_POR_DEFECTO.keys() - CLAVES_PROHIBIDAS.keys():
        campos[clave] = "Este campo no forma parte de la configuración admitida."

    limpio: dict[str, Any] = {}
    singular, plural = spec.termino_instrumento

    # --- instrumentos ---
    crudos = datos.get("instrumentos", [])
    if not isinstance(crudos, list):
        campos["instrumentos"] = f"Debe ser una lista de {plural}."
    else:
        vistos: list[str] = []
        for bruto in crudos:
            if not isinstance(bruto, str):
                campos["instrumentos"] = f"Cada {singular} debe ser texto."
                break
            texto = bruto.strip().upper()
            if not texto:
                continue
            if not spec.patron_instrumento.fullmatch(texto):
                campos["instrumentos"] = (
                    f"«{texto}» no es un {singular} válido. "
                    f"Se espera algo como {spec.ejemplo_instrumento}."
                )
                break
            if texto not in vistos:
                vistos.append(texto)
        else:
            if len(vistos) > spec.max_instrumentos:
                campos["instrumentos"] = (
                    f"Máximo {spec.max_instrumentos} {plural}: el bot corre en una VM "
                    f"compartida y cada {singular} cuesta memoria y llamadas."
                )
            limpio["instrumentos"] = vistos

    # --- estrategia ---
    # Vacío siempre vale: significa "la que traiga el motor por defecto".
    cruda = datos.get("estrategia", "")
    estrategia = cruda.strip() if isinstance(cruda, str) else ""
    if not isinstance(cruda, str):
        campos["estrategia"] = "La estrategia debe ser texto."
    if not estrategia:
        pass
    elif spec.estrategias:
        conocidas = {e.nombre for e in spec.estrategias}
        if estrategia not in conocidas:
            # No se acepta una elección que el productor no sabe construir.
            campos["estrategia"] = "Elige una de las estrategias disponibles: " + ", ".join(
                f"{e.nombre} ({e.etiqueta})" for e in spec.estrategias
            )
    elif not re.match(r"^[A-Za-z][A-Za-z0-9_]{0,63}$", estrategia):
        # Sin catálogo (Freqtrade), este valor termina nombrando un archivo o
        # clase en la VM, así que se restringe a un identificador: sin puntos,
        # sin barras, sin traversal.
        campos["estrategia"] = "Solo letras, números y guion bajo, empezando por una letra."
    limpio["estrategia"] = estrategia

    # --- timeframe ---
    timeframe = str(datos.get("timeframe", "")).strip()
    if timeframe not in spec.timeframes:
        campos["timeframe"] = f"Debe ser uno de: {', '.join(spec.timeframes)}."
    else:
        limpio["timeframe"] = timeframe

    # --- numéricos con rango ---
    for clave, (minimo, maximo, etiqueta) in _LIMITES_NUMERICOS.items():
        try:
            crudo = datos.get(clave, CONFIG_POR_DEFECTO[clave])
            if isinstance(crudo, bool) or not isinstance(crudo, (int, float)):
                raise ValueError
            valor = float(crudo)
        except (TypeError, ValueError):
            campos[clave] = f"{etiqueta} debe ser un número."
            continue
        if not math.isfinite(valor) or not minimo <= valor <= maximo:
            campos[clave] = (
                f"{etiqueta} debe estar entre {_es(minimo)} y {_es(maximo)}."
            )
            continue
        limpio[clave] = valor

    # --- posiciones abiertas ---
    try:
        posiciones = datos.get("max_posiciones_abiertas", 3)
        if type(posiciones) is not int:
            raise ValueError
    except (TypeError, ValueError):
        campos["max_posiciones_abiertas"] = "Debe ser un número entero."
    else:
        if not 1 <= posiciones <= spec.max_instrumentos:
            campos["max_posiciones_abiertas"] = (
                f"Debe estar entre 1 y {spec.max_instrumentos}."
            )
        else:
            limpio["max_posiciones_abiertas"] = posiciones

    # Una coherencia que solo se puede comprobar con ambos valores ya validados:
    # arriesgar más por operación que el freno diario hace que el freno nunca
    # llegue a dispararse, lo que anula la única red de seguridad automática.
    if "stop_loss_pct" in limpio and "max_perdida_diaria_pct" in limpio:
        if limpio["stop_loss_pct"] > limpio["max_perdida_diaria_pct"]:
            campos["max_perdida_diaria_pct"] = (
                "La pérdida diaria máxima no puede ser menor que el stop loss: "
                "el freno nunca llegaría a activarse."
            )

    if campos:
        raise ErrorDeConfig(campos)
    return limpio


def config_freqtrade(config: dict[str, Any], *, estrategia_por_defecto: str) -> dict[str, Any]:
    """Traduce la configuración compartida al JSON que espera Freqtrade.

    Solo genera un borrador: ninguna ruta lo instala ni recarga el motor. No
    integra el freno diario y no debe usarse como prueba de configuración
    aplicada. `dry_run` se fija a `True`, sin leerlo del usuario.
    """
    return {
        "dry_run": True,
        "dry_run_wallet": config.get("capital_simulado", 10_000.0),
        "max_open_trades": config.get("max_posiciones_abiertas", 3),
        "timeframe": config.get("timeframe", "1h"),
        "stoploss": -abs(config.get("stop_loss_pct", 5.0)) / 100.0,
        "minimal_roi": {"0": config.get("take_profit_pct", 10.0) / 100.0},
        "strategy": config.get("estrategia") or estrategia_por_defecto,
        "exchange": {
            "name": "binance",
            # Sin claves: en dry-run Freqtrade solo necesita datos públicos.
            "key": "",
            "secret": "",
            "pair_whitelist": list(config.get("instrumentos", [])),
            "pair_blacklist": [],
        },
    }


# ---------------------------------------------------------------------------
# Lo que un motor devuelve
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EstadoMotor:
    """Foto del motor en este instante."""

    #: ¿Contesta? `False` significa proceso caído o mal configurado; el resto
    #: de campos no son de fiar cuando esto es `False`.
    alcanzable: bool
    #: ¿Está operando? Un motor puede estar vivo y en pausa.
    corriendo: bool
    detalle: str
    modo: str = TRADING_MODE_PAPER
    posiciones_abiertas: int | None = None
    version: str | None = None
    estado: str = "desconocido"
    config_version: int | None = None
    latido_en: str | None = None

    @classmethod
    def caido(cls, detalle: str) -> EstadoMotor:
        return cls(alcanzable=False, corriendo=False, detalle=detalle, modo="desconocido")


@dataclass(frozen=True)
class Operacion:
    """Una operación simulada, abierta o cerrada."""

    instrumento: str
    lado: str
    cantidad: float
    precio_entrada: float
    precio_salida: float | None
    pnl_absoluto: float | None
    pnl_pct: float | None
    abierta_en: str | None
    cerrada_en: str | None

    @property
    def abierta(self) -> bool:
        return self.cerrada_en is None


@dataclass(frozen=True)
class Rendimiento:
    """Resumen de desempeño de la cartera simulada.

    Todo lo que hace falta para responder la pregunta que motivó el módulo:
    *¿cuánto habría ganado o perdido si esto fuera dinero real?*
    """

    capital_inicial: float
    capital_actual: float
    pnl_absoluto: float
    pnl_pct: float
    operaciones_cerradas: int
    ganadoras: int
    perdedoras: int
    mejor_pct: float | None = None
    peor_pct: float | None = None
    #: Comisiones y deslizamiento ya descontados por el motor. Se expone aparte
    #: porque un backtest que los ignora miente sistemáticamente a favor, y
    #: verlos es lo que hace creíble al resto de la tabla.
    costos_simulados: float | None = None

    @property
    def win_rate(self) -> float | None:
        if self.operaciones_cerradas <= 0:
            return None
        return self.ganadoras / self.operaciones_cerradas

    @classmethod
    def vacio(cls, capital_inicial: float) -> Rendimiento:
        return cls(
            capital_inicial=capital_inicial,
            capital_actual=capital_inicial,
            pnl_absoluto=0.0,
            pnl_pct=0.0,
            operaciones_cerradas=0,
            ganadoras=0,
            perdedoras=0,
            costos_simulados=0.0,
        )


# ---------------------------------------------------------------------------
# Adaptadores
# ---------------------------------------------------------------------------


class AdaptadorTrading(Protocol):
    """Interfaz común. La API y la UI no distinguen qué motor hay detrás."""

    def estado(self) -> EstadoMotor: ...

    def encender(self) -> None: ...

    def apagar(self) -> None: ...

    def operaciones(self, limite: int = 50) -> list[Operacion]: ...

    def rendimiento(self, capital_inicial: float) -> Rendimiento: ...


class TransporteHttp(Protocol):
    """Mínimo que necesita `AdaptadorFreqtrade` para hablar por HTTP.

    Se declara como protocolo, y no se usa `httpx` directamente, para que los
    tests puedan sustituirlo por un doble sin levantar un servidor ni tocar la
    red — igual que `PriceProvider` en PortfolioWatcher.
    """

    def get(self, ruta: str, params: dict[str, Any] | None = None) -> Any: ...

    def post(self, ruta: str, cuerpo: dict[str, Any] | None = None) -> Any: ...


@dataclass
class TransporteHttpx:
    """Transporte real contra la API REST de Freqtrade."""

    base_url: str
    usuario: str
    password: str
    timeout: float = 5.0

    def _peticion(self, metodo: str, ruta: str, **kwargs) -> Any:
        url = f"{self.base_url.rstrip('/')}/api/v1/{ruta.lstrip('/')}"
        try:
            respuesta = httpx.request(
                metodo,
                url,
                auth=(self.usuario, self.password),
                timeout=self.timeout,
                **kwargs,
            )
            respuesta.raise_for_status()
            return respuesta.json()
        except Exception as exc:
            raise ErrorDeMotor(str(exc)) from exc

    def get(self, ruta: str, params: dict[str, Any] | None = None) -> Any:
        return self._peticion("GET", ruta, params=params)

    def post(self, ruta: str, cuerpo: dict[str, Any] | None = None) -> Any:
        return self._peticion("POST", ruta, json=cuerpo or {})


@dataclass
class AdaptadorFreqtrade:
    """Motor de cripto. Control **imperativo** por HTTP.

    Freqtrade es un proceso independiente con su propia API REST, así que la
    verdad sobre si está operando vive allí y no en nuestra base: por eso
    `estado()` pregunta en vez de deducir.
    """

    transporte: TransporteHttp

    def _config_paper(self) -> dict[str, Any]:
        config = self.transporte.get("show_config")
        if not isinstance(config, dict) or config.get("dry_run") is not True:
            raise ErrorDeMotor(
                "El motor NO está en modo simulado confirmado. "
                "No se enviaron órdenes; revisa su configuración."
            )
        return config

    def estado(self) -> EstadoMotor:
        try:
            config = self.transporte.get("show_config")
        except ErrorDeMotor as exc:
            log.warning("freqtrade inalcanzable: %s", exc)
            return EstadoMotor.caido(
                "No responde. Revisa que el servicio esté arriba en la VM."
            )

        if not isinstance(config, dict) or config.get("dry_run") is not True:
            return EstadoMotor(
                alcanzable=True,
                corriendo=False,
                detalle=(
                    "El motor NO está en modo simulado confirmado. "
                    "Control bloqueado; esto no significa que el proceso se haya detenido."
                ),
                modo="desconocido",
                estado="bloqueado",
            )

        estado_crudo = config.get("state")
        if not isinstance(estado_crudo, str):
            estado_crudo = ""
        corriendo = estado_crudo == "running"
        observado = {"running": "operando", "stopped": "pausado"}.get(
            estado_crudo, "desconocido"
        )
        abiertas = None
        try:
            estado_trades = self.transporte.get("status")
            if isinstance(estado_trades, list):
                abiertas = len(estado_trades)
        except ErrorDeMotor:
            # No es fatal: el estado principal ya se obtuvo.
            log.debug("no se pudo leer /status de freqtrade")

        return EstadoMotor(
            alcanzable=True,
            corriendo=corriendo,
            detalle=(
                f"Estado observado: {observado}. "
                "La configuración del dashboard no se ha aplicado a este motor."
                + (" No se pudieron consultar las posiciones abiertas." if abiertas is None else "")
            ),
            posiciones_abiertas=abiertas,
            version=config.get("version"),
            estado=observado,
        )

    def encender(self) -> None:
        raise ErrorDeMotor(FREQTRADE.motivo_bloqueo)

    def apagar(self) -> None:
        self._config_paper()
        self.transporte.post("stop")

    def operaciones(self, limite: int = 50) -> list[Operacion]:
        self._config_paper()
        datos = self.transporte.get("trades", {"limit": limite})
        abiertas = self.transporte.get("status")
        if (
            not isinstance(datos, dict) or not isinstance(datos.get("trades"), list)
            or not isinstance(abiertas, list)
        ):
            raise ErrorDeMotor("Freqtrade devolvió operaciones con formato inválido.")
        try:
            operaciones = [_operacion_freqtrade(t) for t in [*abiertas, *datos["trades"]]]
            return sorted(
                operaciones, key=lambda op: op.abierta_en or "", reverse=True
            )[:limite]
        except (TypeError, ValueError, KeyError, AttributeError) as exc:
            raise ErrorDeMotor("Freqtrade devolvió una operación ilegible.") from exc

    def rendimiento(self, capital_inicial: float) -> Rendimiento:
        self._config_paper()
        datos = self.transporte.get("profit")
        try:
            cerradas = _entero_no_negativo(datos["closed_trade_count"])
            ganadoras = _entero_no_negativo(datos["winning_trades"])
            perdedoras = _entero_no_negativo(datos["losing_trades"])
            pnl = _numero_finito(datos["profit_closed_coin"])
            # El capital guardado en el panel NO es el capital aplicado al motor.
            capital_inicial = _numero_finito(datos["starting_balance"])
            if capital_inicial <= 0 or ganadoras + perdedoras > cerradas:
                raise ValueError
        except (TypeError, ValueError, KeyError) as exc:
            raise ErrorDeMotor("Freqtrade devolvió resultados incompletos o inválidos.") from exc
        return Rendimiento(
            capital_inicial=capital_inicial,
            capital_actual=capital_inicial + pnl,
            pnl_absoluto=pnl,
            pnl_pct=(pnl / capital_inicial * 100.0) if capital_inicial else 0.0,
            operaciones_cerradas=cerradas,
            ganadoras=ganadoras,
            perdedoras=perdedoras,
            mejor_pct=_float_o_none(datos.get("best_rate")),
            peor_pct=_float_o_none(datos.get("worst_rate")),
        )


def _float_o_none(valor: Any) -> float | None:
    if valor is None:
        return None
    return _numero_finito(valor)


def _numero_finito(valor: Any) -> float:
    if isinstance(valor, bool):
        raise ValueError("Se esperaba un número, no un booleano.")
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        raise ValueError("Número ilegible.") from None
    if not math.isfinite(numero):
        raise ValueError("Número no finito.")
    return numero


def _entero_no_negativo(valor: Any) -> int:
    if type(valor) is not int or valor < 0:
        raise ValueError("Se esperaba un entero no negativo.")
    return valor


def _operacion_freqtrade(cruda: dict[str, Any]) -> Operacion:
    cerrada = cruda.get("close_date")
    return Operacion(
        instrumento=str(cruda["pair"]),
        lado="venta" if cruda.get("is_short") else "compra",
        cantidad=_numero_finito(cruda["amount"]),
        precio_entrada=_numero_finito(cruda["open_rate"]),
        precio_salida=_float_o_none(cruda.get("close_rate")),
        pnl_absoluto=_float_o_none(cruda.get("profit_abs")),
        # Freqtrade expresa el ratio en tanto por uno; la UI habla en porcentaje.
        pnl_pct=(
            valor * 100.0
            if (valor := _float_o_none(cruda.get("profit_ratio"))) is not None
            else None
        ),
        abierta_en=cruda.get("open_date"),
        cerrada_en=cerrada,
    )


@dataclass
class AdaptadorTradingLab:
    """Motor de acciones. Control **declarativo** vía la base compartida.

    TradingLab (Lumibot) no expone API: consulta `trading_bot_config.enabled`
    en cada ciclo y se ajusta solo. Por eso `encender`/`apagar` aquí no envían
    nada — la escritura del flag ya la hizo la capa de API — y se limitan a
    dejar constancia. Lo que sí se lee de su SQLite es el latido y las
    operaciones que va registrando.

    El dashboard abre esa base en **solo lectura** (`mode=ro`): es de otra app
    y no nos corresponde escribirla.
    """

    db_path: Path
    #: Intención declarada por el dashboard, para poder explicar en la UI la
    #: diferencia entre "lo pedimos" y "el proceso todavía no se ha enterado".
    habilitado: bool = False
    #: El supervisor late cada minuto, independientemente del timeframe.
    tolerancia_latido_min: int = 3

    def _abrir(self) -> sqlite3.Connection:
        if not self.db_path.exists():
            raise ErrorDeMotor(
                "TradingLab todavía no ha creado su base de estado. "
                "¿Está instalado y ha corrido al menos una vez?"
            )
        try:
            conexion = sqlite3.connect(
                f"{self.db_path.resolve().as_uri()}?mode=ro", uri=True, timeout=5.0
            )
            conexion.row_factory = sqlite3.Row
        except sqlite3.Error as exc:
            raise ErrorDeMotor(f"No se pudo leer el estado de TradingLab: {exc}") from exc
        return conexion

    def _leer(self, consulta: str, parametros: tuple = ()) -> list[sqlite3.Row]:
        try:
            with closing(self._abrir()) as conexion:
                return conexion.execute(consulta, parametros).fetchall()
        except sqlite3.Error as exc:
            raise ErrorDeMotor(f"No se pudo leer el estado de TradingLab: {exc}") from exc

    def estado(self) -> EstadoMotor:
        try:
            filas = self._leer(
                "SELECT * "
                "FROM estado_motor ORDER BY latido_en DESC LIMIT 1"
            )
        except ErrorDeMotor as exc:
            log.warning("tradinglab inalcanzable: %s", exc)
            return EstadoMotor.caido(str(exc))

        if not filas:
            return EstadoMotor.caido("TradingLab no ha reportado estado todavía.")
        fila = filas[0]
        try:
            posiciones = _entero_no_negativo(fila["posiciones_abiertas"])
            observado = fila["estado"] if "estado" in fila.keys() else "desconocido"
            if observado not in {
                "operando", "pausado", "esperando", "detenido", "error", "bloqueado",
            }:
                observado = "desconocido"
            version = fila["config_version"] if "config_version" in fila.keys() else None
            if version is not None:
                version = _entero_no_negativo(version)
            modo = fila["modo"] if "modo" in fila.keys() else None
        except (ValueError, KeyError, IndexError):
            return EstadoMotor.caido("TradingLab publicó un estado inválido.")

        fresco = _latido_fresco(fila["latido_en"], self.tolerancia_latido_min)
        if not fresco:
            return EstadoMotor(
                alcanzable=False,
                corriendo=False,
                detalle=(
                    f"Sin señales desde {fila['latido_en']}. "
                    f"Estado obsoleto o fecha inválida. Último detalle: {fila['detalle']}"
                ),
                estado="stale",
                version=fila["version"],
                config_version=version,
                latido_en=fila["latido_en"],
            )
        detalle = str(fila["detalle"] or "Sin detalle del motor.")
        if modo == "alpaca_paper":
            detalle += (
                " Alpaca Paper está bloqueado preventivamente para ejecutar operaciones; "
                "este aviso no sustituye el estado observado del supervisor."
            )
        elif modo != "simulado":
            observado = "desconocido"
            detalle += " El origen de ejecución no está confirmado."
        if observado == "desconocido":
            detalle += " El motor no publica estado observacional; ejecución sin confirmar."

        return EstadoMotor(
            alcanzable=observado != "detenido",
            corriendo=modo == "simulado" and observado == "operando",
            modo="paper" if modo in {"simulado", "alpaca_paper"} else "desconocido",
            detalle=detalle,
            posiciones_abiertas=posiciones,
            version=fila["version"],
            estado=observado,
            config_version=version,
            latido_en=fila["latido_en"],
        )

    def encender(self) -> None:
        """No-op deliberado: el flag en `trading_bot_config` es el control."""

    def apagar(self) -> None:
        """No-op deliberado: ver `encender`."""

    def operaciones(self, limite: int = 50) -> list[Operacion]:
        self._identidad_simulada()
        filas = self._leer(
            "SELECT instrumento, lado, cantidad, precio_entrada, precio_salida, "
            "pnl_absoluto, pnl_pct, abierta_en, cerrada_en "
            "FROM operaciones ORDER BY abierta_en DESC LIMIT ?",
            (limite,),
        )
        return [
            Operacion(
                instrumento=fila["instrumento"],
                lado=fila["lado"],
                cantidad=_numero_finito(fila["cantidad"]),
                precio_entrada=_numero_finito(fila["precio_entrada"]),
                precio_salida=_float_o_none(fila["precio_salida"]),
                pnl_absoluto=_float_o_none(fila["pnl_absoluto"]),
                pnl_pct=_float_o_none(fila["pnl_pct"]),
                abierta_en=fila["abierta_en"],
                cerrada_en=fila["cerrada_en"],
            )
            for fila in filas
        ]

    def rendimiento(self, capital_inicial: float) -> Rendimiento:
        identidad = self._identidad_simulada()
        try:
            capital_inicial = _numero_finito(identidad["capital_inicial"])
            if capital_inicial <= 0:
                raise ValueError
        except (ValueError, KeyError, IndexError) as exc:
            raise ErrorDeMotor("El motor no ha confirmado su capital inicial simulado.") from exc
        filas = self._leer(
            "SELECT COUNT(*) AS cerradas, "
            "COALESCE(SUM(pnl_absoluto), 0) AS pnl, "
            "COALESCE(SUM(costos), 0) AS costos, "
            "SUM(CASE WHEN pnl_absoluto > 0 THEN 1 ELSE 0 END) AS ganadoras, "
            "SUM(CASE WHEN pnl_absoluto <= 0 THEN 1 ELSE 0 END) AS perdedoras, "
            "MAX(pnl_pct) AS mejor, MIN(pnl_pct) AS peor "
            "FROM operaciones WHERE cerrada_en IS NOT NULL"
        )
        fila = filas[0] if filas else None

        if fila is None or not fila["cerradas"]:
            return Rendimiento.vacio(capital_inicial)

        pnl = _numero_finito(fila["pnl"])
        return Rendimiento(
            capital_inicial=capital_inicial,
            capital_actual=capital_inicial + pnl,
            pnl_absoluto=pnl,
            pnl_pct=(pnl / capital_inicial * 100.0) if capital_inicial else 0.0,
            operaciones_cerradas=int(fila["cerradas"] or 0),
            ganadoras=int(fila["ganadoras"] or 0),
            perdedoras=int(fila["perdedoras"] or 0),
            mejor_pct=_float_o_none(fila["mejor"]),
            peor_pct=_float_o_none(fila["peor"]),
            costos_simulados=_numero_finito(fila["costos"]),
        )

    def _identidad_simulada(self) -> sqlite3.Row:
        filas = self._leer("SELECT * FROM identidad_motor WHERE id = 1")
        if not filas or filas[0]["modo"] != "simulado":
            raise ErrorDeMotor("La base no identifica un simulador local aislado.")
        return filas[0]


def _latido_fresco(latido: Any, tolerancia_min: int) -> bool:
    """¿El último latido cae dentro de la ventana de tolerancia?

    Una fecha ilegible, sin zona o futura no confirma actividad.
    """
    if not latido:
        return False
    try:
        momento = dt.datetime.fromisoformat(str(latido).replace("Z", "+00:00"))
    except ValueError:
        log.debug("latido de tradinglab ilegible: %r", latido)
        return False
    if momento.tzinfo is None:
        return False
    antiguedad = utcnow() - momento
    return dt.timedelta(seconds=-5) <= antiguedad <= dt.timedelta(minutes=tolerancia_min)


def construir_adaptador(spec: MotorSpec, settings, *, habilitado: bool) -> AdaptadorTrading:
    """Crea el adaptador del motor a partir de la configuración del proceso."""
    if spec.bot_name == BOT_FREQTRADE:
        return AdaptadorFreqtrade(
            transporte=TransporteHttpx(
                base_url=settings.freqtrade_url,
                usuario=settings.freqtrade_user,
                password=settings.freqtrade_password,
                timeout=float(settings.trading_timeout_seconds),
            )
        )
    if spec.bot_name == BOT_LUMIBOT:
        return AdaptadorTradingLab(
            db_path=Path(settings.tradinglab_db),
            habilitado=habilitado,
        )
    raise ValueError(f"motor desconocido: {spec.bot_name}")
