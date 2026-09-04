"""El motor real: Lumibot sobre Alpaca Paper.

Este es el único archivo del paquete que sabe que Lumibot existe. Todo lo demás
habla con los protocolos `Motor` y `Corredor` de `corredor.py`, así que un cambio
de API de Lumibot se arregla aquí y en ningún otro sitio.

Por qué hay un `Motor` y no solo un `Corredor`
----------------------------------------------
Lumibot invierte el control. Uno no le pide precios: uno le entrega una
`Strategy`, un `Trader` la arranca, y es Lumibot quien llama a
`on_trading_iteration` cuando considera que toca operar. Sus objetos internos
(el broker, el data source) no son API pública y usarlos por fuera de esa
llamada es pedir problemas.

En vez de pelear con eso, `MotorAlpaca.ejecutar` mete nuestra tarea **dentro** de
esa llamada: construye una `Strategy` puente, la corre una sola vez con
`run_all(run_once=True)` y devuelve lo que la tarea produjo. Si Lumibot decide
que no toca operar —el caso normal es que la bolsa esté cerrada— la tarea no
corre y `ejecutar` devuelve `None`, que es exactamente lo que el supervisor
espera para no ensuciar el panel con un error que no lo es.

Advertencia honesta
-------------------
Este camino **no se ha podido probar de extremo a extremo** sin credenciales de
Alpaca ni las dependencias de Lumibot instaladas. La forma de validarlo en la VM
es `tradinglab doctor`, que comprueba import, credenciales, conexión y horario
sin enviar ninguna orden. Los tests del paquete no importan Lumibot a propósito.
"""

from __future__ import annotations

import inspect
import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

from .corredor import Corredor, Ejecucion, ErrorDeCorredor

log = logging.getLogger("tradinglab.alpaca")

T = TypeVar("T")

#: Los marcos temporales que ofrece el dashboard, traducidos al vocabulario de
#: Lumibot. Lo que no esté en el mapa cae a velas diarias, que es el marco menos
#: propenso a quedarse sin datos.
_TIMESTEP = {
    "5m": "5 minutes",
    "15m": "15 minutes",
    "30m": "30 minutes",
    "1h": "1 hour",
    "1d": "day",
}

#: Cuánto se espera a que una orden de mercado se llene antes de darla por
#: perdida. En Alpaca Paper con valores líquidos esto ocurre en menos de un
#: segundo; el margen es para el arranque del stream de órdenes.
ESPERA_LLENADO_SEG = 20.0

_ESTADOS_LLENA = {"fill", "filled", "fill_partial", "partial_fill", "closed"}


class LumibotNoDisponible(RuntimeError):
    """Lumibot no está instalado. Se instala con el extra `alpaca`."""


# ---------------------------------------------------------------------------
# Carga perezosa
# ---------------------------------------------------------------------------


def _preparar_entorno() -> None:
    """Apaga los efectos secundarios de importar Lumibot.

    Importar `lumibot.credentials` dispara un escaneo recursivo del sistema de
    archivos buscando un `.env`. En un portátil es una molestia; en la VM, con
    los discos de las otras apps montados, es una lectura larga y ruidosa cada
    vez que arranca el proceso.
    """
    os.environ.setdefault("LUMIBOT_DISABLE_DOTENV", "1")


def _cargar() -> tuple[Any, Any, Any]:
    """Devuelve `(Strategy, Alpaca, Trader)` o explica por qué no puede."""
    _preparar_entorno()
    try:
        from lumibot.brokers import Alpaca
        from lumibot.strategies import Strategy
        from lumibot.traders import Trader
    except ImportError as exc:  # pragma: no cover - depende del entorno
        raise LumibotNoDisponible(
            "lumibot no está instalado; instala TradingLab con el extra 'alpaca' "
            "(pip install -e '.[alpaca]')"
        ) from exc
    return Strategy, Alpaca, Trader


def disponible() -> bool:
    """¿Se puede usar el motor real en este entorno?"""
    try:
        _cargar()
    except LumibotNoDisponible:
        return False
    return True


def _kwargs_soportados(fabrica: Any, **kwargs: Any) -> dict[str, Any]:
    """Descarta los argumentos que esta versión de Lumibot no conoce.

    Lumibot mueve su firma entre versiones menores y varias de las opciones que
    aquí interesan —las que apagan escrituras a disco y a bases externas— son
    relativamente nuevas. Filtrar es preferible a un `try/except TypeError` que
    acabaría descartando *todas* las opciones por culpa de una sola.
    """
    try:
        parametros = inspect.signature(fabrica).parameters
    except (TypeError, ValueError):  # pragma: no cover - objetos sin firma
        return dict(kwargs)
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in parametros.values()):
        return dict(kwargs)
    return {k: v for k, v in kwargs.items() if k in parametros}


# ---------------------------------------------------------------------------
# Corredor
# ---------------------------------------------------------------------------


@dataclass
class CorredorLumibot:
    """Adapta la `Strategy` de Lumibot al protocolo `Corredor`.

    Solo es válido **dentro** de `on_trading_iteration`: fuera de ahí la sesión
    no existe y los métodos de la estrategia fallan o mienten. Por eso no se
    construye ni se guarda en ningún sitio salvo dentro de la tarea.
    """

    estrategia: Any
    timeframe: str = "1d"
    espera_llenado_seg: float = ESPERA_LLENADO_SEG

    def mercado_abierto(self) -> bool:
        # Si estamos aquí es porque Lumibot ya decidió que toca operar; volver a
        # preguntar sería duplicar su criterio con uno peor.
        return True

    def cierres(self, instrumento: str, velas: int, timeframe: str) -> list[float]:
        paso = _TIMESTEP.get(timeframe or self.timeframe, "day")
        try:
            barras = self.estrategia.get_historical_prices(instrumento, velas, paso)
        except Exception as exc:
            log.warning("sin histórico para %s: %s", instrumento, exc)
            return []
        if barras is None:
            return []
        marco = getattr(barras, "pandas_df", None)
        if marco is None:
            # `bars.df` puede ser un DataFrame de polars según la fuente de
            # datos; `pandas_df` es el que Lumibot garantiza que es pandas.
            marco = getattr(barras, "df", None)
        if marco is None or len(marco) == 0:
            return []
        columna = next((c for c in ("close", "Close", "close_price") if c in marco.columns), None)
        if columna is None:
            log.warning("el histórico de %s no trae columna de cierre", instrumento)
            return []
        return [float(v) for v in marco[columna].tolist() if v is not None]

    def precio(self, instrumento: str) -> float | None:
        try:
            valor = self.estrategia.get_last_price(instrumento)
        except Exception as exc:
            log.warning("sin precio para %s: %s", instrumento, exc)
            return None
        if valor is None:
            return None
        try:
            return float(valor)
        except (TypeError, ValueError):  # pragma: no cover - Decimal raro
            return None

    # ------------------------------------------------------------------ órdenes

    def comprar(self, instrumento: str, cantidad: float) -> Ejecucion:
        return self._operar(instrumento, cantidad, "buy")

    def vender(self, instrumento: str, cantidad: float) -> Ejecucion:
        return self._operar(instrumento, cantidad, "sell")

    def _operar(self, instrumento: str, cantidad: float, lado: str) -> Ejecucion:
        unidades = int(cantidad)
        if unidades <= 0:
            raise ErrorDeCorredor(f"cantidad inválida para {instrumento}: {cantidad}")
        try:
            # El primer parámetro de `create_order` es `asset`, no `symbol`, y
            # el método no acepta `**kwargs`: pasarlo por nombre falla.
            orden = self.estrategia.create_order(instrumento, unidades, lado)
            enviada = self.estrategia.submit_order(orden)
        except Exception as exc:
            raise ErrorDeCorredor(f"no se pudo enviar la orden de {instrumento}: {exc}") from exc

        orden = enviada if enviada is not None else orden
        precio = self._esperar_llenado(orden)
        if precio is None:
            # Sin precio de llenado no se puede contabilizar la operación, y
            # anotarla con el último precio conocido metería una mentira en el
            # histórico que luego nadie sabría distinguir.
            raise ErrorDeCorredor(
                f"la orden de {instrumento} no se llenó en {self.espera_llenado_seg:.0f} s"
            )
        return Ejecucion(
            instrumento=instrumento,
            cantidad=unidades,
            precio=precio,
            # Alpaca no cobra comisión por acciones de EE. UU. y el precio de
            # llenado ya trae el deslizamiento incorporado: sumar un costo
            # sintético encima lo contaría dos veces.
            costos=0.0,
            identificador=str(getattr(orden, "identifier", "") or "") or None,
        )

    def _esperar_llenado(self, orden: Any) -> float | None:
        limite = time.monotonic() + self.espera_llenado_seg
        while True:
            precio = _precio_de_llenado(orden)
            if precio is not None and _esta_llena(orden):
                return precio
            if time.monotonic() >= limite:
                return precio if _esta_llena(orden) else None
            time.sleep(0.5)

    def efectivo(self) -> float:
        for nombre in ("get_cash", "get_portfolio_value"):
            metodo = getattr(self.estrategia, nombre, None)
            if metodo is None:
                continue
            try:
                valor = metodo()
            except Exception:
                continue
            # Ambos pueden devolver `None` en vivo, y eso no es un cero: es
            # «todavía no lo sé». Por eso se prueba el siguiente antes de
            # rendirse.
            if valor is not None:
                return float(valor)
        return 0.0

    def cerrar(self) -> None:
        # La sesión la abre y la cierra el motor; el corredor no es dueño de
        # nada que pueda soltar.
        return None


def _precio_de_llenado(orden: Any) -> float | None:
    for nombre in ("avg_fill_price", "get_fill_price"):
        valor = getattr(orden, nombre, None)
        if callable(valor):
            try:
                valor = valor()
            except Exception:
                valor = None
        if valor:
            try:
                return float(valor)
            except (TypeError, ValueError):
                return None
    return None


def _esta_llena(orden: Any) -> bool:
    comprobar = getattr(orden, "is_filled", None)
    if callable(comprobar):
        try:
            return bool(comprobar())
        except Exception:
            pass
    # `Order.OrderStatus.FILLED` vale `"fill"`, no `"filled"`: comparar contra
    # la cadena obvia daría siempre falso.
    estado = str(getattr(orden, "status", "") or "").lower()
    return estado in _ESTADOS_LLENA


# ---------------------------------------------------------------------------
# Motor
# ---------------------------------------------------------------------------


@dataclass
class MotorAlpaca:
    """Abre una sesión de Lumibot, corre una tarea dentro y la cierra."""

    api_key: str
    api_secret: str
    timeframe: str = "1d"
    #: Lumibot escribe logs relativos al directorio de trabajo. Fijarlo aquí
    #: evita que acaben donde sea que systemd haya dejado el CWD.
    directorio_logs: Path = field(default_factory=lambda: Path("logs"))
    espera_llenado_seg: float = ESPERA_LLENADO_SEG

    _broker: Any = field(default=None, init=False, repr=False)

    @classmethod
    def desde_entorno(cls, timeframe: str = "1d", **extra: Any) -> MotorAlpaca:
        """Construye el motor con las credenciales del entorno de la unidad.

        Las claves viven en el `Environment=` de systemd y nunca en la base de
        datos: la configuración compartida la puede editar cualquier usuario
        autorizado desde el celular, y unas credenciales ahí serían legibles por
        todos ellos.
        """
        clave = os.environ.get("ALPACA_API_KEY", "").strip()
        secreto = os.environ.get("ALPACA_API_SECRET", "").strip()
        if not clave or not secreto:
            raise ErrorDeCorredor(
                "faltan ALPACA_API_KEY y/o ALPACA_API_SECRET en el entorno del proceso"
            )
        return cls(api_key=clave, api_secret=secreto, timeframe=timeframe, **extra)

    # ------------------------------------------------------------------ público

    def ejecutar(self, tarea: Callable[[Corredor], T]) -> T | None:
        Strategy, Alpaca, Trader = _cargar()

        # `Alpaca()` sin argumentos falla pese a lo que dicen los docs: `config`
        # es posicional y obligatorio. Las claves del diccionario son literales
        # y sensibles a mayúsculas; cualquier clave que contenga "paper" activa
        # el modo simulado, que es el único que este proyecto usa.
        if self._broker is None:
            self._broker = Alpaca(
                {"API_KEY": self.api_key, "API_SECRET": self.api_secret, "PAPER": True}
            )

        caja: dict[str, Any] = {}
        puente = self._construir_puente(Strategy, tarea, caja)

        estrategia = puente(
            broker=self._broker,
            **_kwargs_soportados(
                puente,
                should_backup_variables_to_database=False,
                save_logfile=False,
                quiet_logs=True,
            ),
        )

        self.directorio_logs.mkdir(parents=True, exist_ok=True)
        trader = Trader(
            **_kwargs_soportados(
                Trader,
                logfile=str(self.directorio_logs / "tradinglab-lumibot.log"),
                backtest=False,
                quiet_logs=True,
            )
        )
        trader.add_strategy(estrategia)
        # `run_once=True` corre una sola iteración de forma síncrona y sale. Está
        # pensado justo para esto: un despliegue con planificador externo, que
        # aquí es el supervisor.
        trader.run_all(**_kwargs_soportados(trader.run_all, run_once=True, show_plot=False))

        if "error" in caja:
            raise caja["error"]
        # Ausente significa que Lumibot nunca llamó a `on_trading_iteration`, y
        # el motivo habitual es que la bolsa esté cerrada.
        return caja.get("valor")

    def cerrar(self) -> None:
        broker, self._broker = self._broker, None
        if broker is None:
            return
        for nombre in ("disconnect", "close_connection", "stop"):
            metodo = getattr(broker, nombre, None)
            if callable(metodo):
                try:
                    metodo()
                except Exception:
                    log.warning("el broker no cerró limpiamente", exc_info=True)
                return

    # ------------------------------------------------------------------ interno

    def _construir_puente(
        self,
        Strategy: Any,
        tarea: Callable[[Corredor], T],
        caja: dict[str, Any],
    ) -> Any:
        motor = self

        class Puente(Strategy):
            """Estrategia mínima cuyo único trabajo es cederle el turno a la tarea."""

            def initialize(self) -> None:
                self.sleeptime = motor.timeframe
                self.should_backup_variables_to_database = False

            def on_trading_iteration(self) -> None:
                if "valor" in caja or "error" in caja:
                    # `run_once` debería llamarnos una sola vez, pero si alguna
                    # versión llamara dos, operar de nuevo duplicaría posiciones
                    # de verdad. Es barato blindarlo.
                    return
                corredor = CorredorLumibot(
                    estrategia=self,
                    timeframe=motor.timeframe,
                    espera_llenado_seg=motor.espera_llenado_seg,
                )
                try:
                    caja["valor"] = tarea(corredor)
                except Exception as exc:
                    # Lumibot atrapa y registra las excepciones de la iteración,
                    # así que dejarla subir aquí la haría desaparecer del panel.
                    # Se guarda y se relanza fuera de la sesión.
                    caja["error"] = exc

        return Puente
