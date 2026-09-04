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

- **Freqtrade es imperativo**: el dashboard le *ordena* arrancar o parar por
  HTTP (`POST /api/v1/start` y `/stop`) y le pregunta el estado. La verdad vive
  en el proceso de Freqtrade.
- **TradingLab es declarativo**: el dashboard solo escribe la *intención* en
  `trading_bot_config.enabled`, y el proceso de TradingLab la consulta en cada
  ciclo y se ajusta. La verdad vive en nuestra base; TradingLab publica su
  latido (heartbeat) en su propia SQLite para que sepamos si sigue vivo.

`AdaptadorTrading` esconde las dos formas tras los mismos cinco métodos, de
modo que la API y la UI no sepan cuál es cuál.

Por qué nunca hay dinero real
-----------------------------
El módulo opera solo con dinero simulado, y eso se sostiene en **tres capas
independientes** para que ningún descuido aislado las atraviese:

1. **El esquema**: `trading_bot_config.mode` tiene un `CHECK` que solo admite
   `'paper'`. La base misma rechaza almacenar otra cosa (ver la migración
   `de02a901e6ae`).
2. **La validación**: `validar_config` rechaza cualquier clave que huela a
   ejecución real (`dry_run`, claves de API, `trading_mode`...), así que no se
   pueden colar por el JSON de configuración.
3. **La generación**: `config_freqtrade` fija `dry_run: True` en el JSON que
   se le entrega al motor, sin leerlo de la configuración del usuario.

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
import re
import sqlite3
from dataclasses import dataclass, field
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
    simula_contra="Alpaca Paper",
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
#: muestra a quien lo intente. Son la segunda de las tres capas que impiden
#: operar con dinero real (ver el docstring del módulo). Se rechazan de forma
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

    limpio: dict[str, Any] = {}
    singular, plural = spec.termino_instrumento

    # --- instrumentos ---
    crudos = datos.get("instrumentos", [])
    if not isinstance(crudos, list):
        campos["instrumentos"] = f"Debe ser una lista de {plural}."
    else:
        vistos: list[str] = []
        for bruto in crudos:
            texto = str(bruto).strip().upper()
            if not texto:
                continue
            if not spec.patron_instrumento.match(texto):
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
    estrategia = str(datos.get("estrategia", "")).strip()
    if estrategia and not re.match(r"^[A-Za-z][A-Za-z0-9_]{0,63}$", estrategia):
        # Este valor termina nombrando un archivo/clase en la VM, así que se
        # restringe a un identificador: sin puntos, sin barras, sin traversal.
        campos["estrategia"] = (
            "Solo letras, números y guion bajo, empezando por una letra."
        )
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
            valor = float(datos.get(clave, CONFIG_POR_DEFECTO[clave]))
        except (TypeError, ValueError):
            campos[clave] = f"{etiqueta} debe ser un número."
            continue
        if not minimo <= valor <= maximo:
            campos[clave] = (
                f"{etiqueta} debe estar entre {_es(minimo)} y {_es(maximo)}."
            )
            continue
        limpio[clave] = valor

    # --- posiciones abiertas ---
    try:
        posiciones = int(datos.get("max_posiciones_abiertas", 3))
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

    `dry_run` se fija aquí a `True` de forma literal y **no** se lee de
    `config`: es la tercera de las tres capas que impiden operar con dinero
    real. Aunque alguien lograra escribir `dry_run: false` en la base saltándose
    el `CHECK` y la validación, este archivo lo sobreescribiría igual.
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
    posiciones_abiertas: int = 0
    version: str | None = None

    @classmethod
    def caido(cls, detalle: str) -> EstadoMotor:
        return cls(alcanzable=False, corriendo=False, detalle=detalle)


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
    costos_simulados: float = 0.0

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

    def estado(self) -> EstadoMotor:
        try:
            config = self.transporte.get("show_config")
        except ErrorDeMotor as exc:
            log.warning("freqtrade inalcanzable: %s", exc)
            return EstadoMotor.caido(
                "No responde. Revisa que el servicio esté arriba en la VM."
            )

        estado_crudo = str(config.get("state", "")).lower()
        corriendo = estado_crudo == "running"

        # Cinturón y tirantes: si el motor dijera que NO está en dry-run,
        # tratamos eso como una anomalía grave y no como un estado normal.
        # Preferimos alarmar en la UI antes que mostrar como simulada una
        # cartera que no lo es.
        if config.get("dry_run") is False:
            log.error("freqtrade reporta dry_run=false; se marca como no operable")
            return EstadoMotor(
                alcanzable=True,
                corriendo=False,
                detalle=(
                    "El motor NO está en modo simulado. Se bloqueó por seguridad: "
                    "revisa su configuración en la VM antes de continuar."
                ),
                modo="desconocido",
            )

        abiertas = 0
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
            detalle="Operando" if corriendo else "En pausa",
            posiciones_abiertas=abiertas,
            version=config.get("version"),
        )

    def encender(self) -> None:
        self.transporte.post("start")

    def apagar(self) -> None:
        self.transporte.post("stop")

    def operaciones(self, limite: int = 50) -> list[Operacion]:
        datos = self.transporte.get("trades", {"limit": limite})
        crudas = datos.get("trades", []) if isinstance(datos, dict) else (datos or [])
        return [_operacion_freqtrade(t) for t in crudas]

    def rendimiento(self, capital_inicial: float) -> Rendimiento:
        datos = self.transporte.get("profit")
        cerradas = int(datos.get("closed_trade_count", 0) or 0)
        ganadoras = int(datos.get("winning_trades", 0) or 0)
        perdedoras = int(datos.get("losing_trades", 0) or 0)
        pnl = float(datos.get("profit_closed_coin", 0.0) or 0.0)
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
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def _operacion_freqtrade(cruda: dict[str, Any]) -> Operacion:
    cerrada = cruda.get("close_date")
    return Operacion(
        instrumento=str(cruda.get("pair", "")),
        lado="venta" if cruda.get("is_short") else "compra",
        cantidad=float(cruda.get("amount", 0.0) or 0.0),
        precio_entrada=float(cruda.get("open_rate", 0.0) or 0.0),
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
    #: Minutos sin latido tras los que se considera caído. Generoso a
    #: propósito: TradingLab late una vez por ciclo, y un ciclo diario es
    #: legítimo.
    tolerancia_latido_min: int = 90
    _conexion: sqlite3.Connection | None = field(default=None, init=False, repr=False)

    def _abrir(self) -> sqlite3.Connection:
        if self._conexion is not None:
            return self._conexion
        if not self.db_path.exists():
            raise ErrorDeMotor(
                "TradingLab todavía no ha creado su base de estado. "
                "¿Está instalado y ha corrido al menos una vez?"
            )
        try:
            conexion = sqlite3.connect(
                f"file:{self.db_path}?mode=ro", uri=True, timeout=5.0
            )
            conexion.row_factory = sqlite3.Row
        except sqlite3.Error as exc:
            raise ErrorDeMotor(f"No se pudo leer el estado de TradingLab: {exc}") from exc
        self._conexion = conexion
        return conexion

    def cerrar(self) -> None:
        if self._conexion is not None:
            self._conexion.close()
            self._conexion = None

    def estado(self) -> EstadoMotor:
        try:
            conexion = self._abrir()
            fila = conexion.execute(
                "SELECT latido_en, detalle, posiciones_abiertas, version "
                "FROM estado_motor ORDER BY latido_en DESC LIMIT 1"
            ).fetchone()
        except (ErrorDeMotor, sqlite3.Error) as exc:
            log.warning("tradinglab inalcanzable: %s", exc)
            return EstadoMotor.caido(str(exc))

        if fila is None:
            return EstadoMotor.caido("TradingLab no ha reportado estado todavía.")

        fresco = _latido_fresco(fila["latido_en"], self.tolerancia_latido_min)
        if not fresco:
            return EstadoMotor(
                alcanzable=False,
                corriendo=False,
                detalle=(
                    f"Sin señales desde {fila['latido_en']}. "
                    "El proceso puede estar caído."
                ),
                posiciones_abiertas=int(fila["posiciones_abiertas"] or 0),
            )

        return EstadoMotor(
            alcanzable=True,
            corriendo=self.habilitado,
            detalle="Operando" if self.habilitado else "En pausa",
            posiciones_abiertas=int(fila["posiciones_abiertas"] or 0),
            version=fila["version"],
        )

    def encender(self) -> None:
        """No-op deliberado: el flag en `trading_bot_config` es el control."""

    def apagar(self) -> None:
        """No-op deliberado: ver `encender`."""

    def operaciones(self, limite: int = 50) -> list[Operacion]:
        conexion = self._abrir()
        try:
            filas = conexion.execute(
                "SELECT instrumento, lado, cantidad, precio_entrada, precio_salida, "
                "pnl_absoluto, pnl_pct, abierta_en, cerrada_en "
                "FROM operaciones ORDER BY abierta_en DESC LIMIT ?",
                (limite,),
            ).fetchall()
        except sqlite3.Error as exc:
            raise ErrorDeMotor(f"No se pudieron leer las operaciones: {exc}") from exc
        return [
            Operacion(
                instrumento=fila["instrumento"],
                lado=fila["lado"],
                cantidad=float(fila["cantidad"] or 0.0),
                precio_entrada=float(fila["precio_entrada"] or 0.0),
                precio_salida=_float_o_none(fila["precio_salida"]),
                pnl_absoluto=_float_o_none(fila["pnl_absoluto"]),
                pnl_pct=_float_o_none(fila["pnl_pct"]),
                abierta_en=fila["abierta_en"],
                cerrada_en=fila["cerrada_en"],
            )
            for fila in filas
        ]

    def rendimiento(self, capital_inicial: float) -> Rendimiento:
        conexion = self._abrir()
        try:
            fila = conexion.execute(
                "SELECT COUNT(*) AS cerradas, "
                "COALESCE(SUM(pnl_absoluto), 0) AS pnl, "
                "COALESCE(SUM(costos), 0) AS costos, "
                "SUM(CASE WHEN pnl_absoluto > 0 THEN 1 ELSE 0 END) AS ganadoras, "
                "SUM(CASE WHEN pnl_absoluto <= 0 THEN 1 ELSE 0 END) AS perdedoras, "
                "MAX(pnl_pct) AS mejor, MIN(pnl_pct) AS peor "
                "FROM operaciones WHERE cerrada_en IS NOT NULL"
            ).fetchone()
        except sqlite3.Error as exc:
            raise ErrorDeMotor(f"No se pudo calcular el rendimiento: {exc}") from exc

        if fila is None or not fila["cerradas"]:
            return Rendimiento.vacio(capital_inicial)

        pnl = float(fila["pnl"] or 0.0)
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
            costos_simulados=float(fila["costos"] or 0.0),
        )


def _latido_fresco(latido: Any, tolerancia_min: int) -> bool:
    """¿El último latido cae dentro de la ventana de tolerancia?

    Ante una marca de tiempo ilegible se responde `True`: preferimos mostrar el
    estado que reportó el motor a declararlo caído por un problema de formato.
    """
    if not latido:
        return False
    try:
        momento = dt.datetime.fromisoformat(str(latido))
    except ValueError:
        log.debug("latido de tradinglab ilegible: %r", latido)
        return True
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=dt.timezone.utc)
    return (utcnow() - momento) <= dt.timedelta(minutes=tolerancia_min)


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
