"""Frontera de Alpaca Paper, bloqueada hasta disponer de conciliación durable.

No se abre una sesión Lumibot ni se envían órdenes. Un timeout de envío no
demuestra que no hubo ejecución; reintentarlo sin un diario de intenciones y
client_order_id puede duplicar posiciones. Véase docs/fiabilidad.md.
"""

from __future__ import annotations

import importlib.util
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

from .corredor import Corredor, Ejecucion, ErrorDeCorredor

T = TypeVar("T")

BLOQUEO_ALPACA = (
    "Alpaca Paper bloqueado: falta conciliación durable de órdenes y posiciones "
    "(llenados parciales, cancelación, timeout y reinicio). No se envían órdenes. "
    "Las posiciones existentes no se liquidan ni tienen stop loss gestionado por TradingLab."
)

_TIMESTEP = {
    "5m": "5 minutes",
    "15m": "15 minutes",
    "30m": "30 minutes",
    "1h": "1 hour",
    "1d": "day",
}


class AlpacaBloqueado(ErrorDeCorredor):
    """El motor no cumple aún las garantías necesarias para enviar órdenes."""


def disponible() -> bool:
    """Detecta el paquete sin importarlo ni iniciar conexiones o hooks del SDK."""
    return importlib.util.find_spec("lumibot") is not None


@dataclass
class CorredorLumibot:
    """Adaptador de lectura para pruebas de contrato; las mutaciones se rechazan."""

    estrategia: Any
    timeframe: str = "1d"

    def mercado_abierto(self) -> bool:
        raise AlpacaBloqueado(BLOQUEO_ALPACA)

    def cierres(self, instrumento: str, velas: int, timeframe: str) -> list[float]:
        marco = timeframe or self.timeframe
        if marco not in _TIMESTEP:
            raise ErrorDeCorredor(f"timeframe no soportado: {marco}")
        # Los errores del SDK se propagan: no son un histórico vacío.
        barras = self.estrategia.get_historical_prices(instrumento, velas, _TIMESTEP[marco])
        if barras is None:
            raise ErrorDeCorredor(f"sin histórico para {instrumento}")
        tabla = barras.pandas_df
        if "close" not in tabla.columns:
            raise ErrorDeCorredor(f"el histórico de {instrumento} no trae cierres")
        return [_numero_positivo(v, "cierre") for v in tabla["close"].tolist()]

    def precio(self, instrumento: str) -> float:
        return _numero_positivo(self.estrategia.get_last_price(instrumento), "precio")

    def comprar(self, instrumento: str, cantidad: float) -> Ejecucion:
        raise AlpacaBloqueado(BLOQUEO_ALPACA)

    def vender(self, instrumento: str, cantidad: float) -> Ejecucion:
        raise AlpacaBloqueado(BLOQUEO_ALPACA)

    def efectivo(self) -> float:
        # El patrimonio incluye posiciones: nunca sustituye al efectivo.
        valor = self.estrategia.get_cash()
        try:
            numero = float(valor)
        except (TypeError, ValueError) as exc:
            raise ErrorDeCorredor("efectivo desconocido") from exc
        if not math.isfinite(numero) or numero < 0:
            raise ErrorDeCorredor("efectivo inválido")
        return numero

    def costo_compra(self, instrumento: str, cantidad: float) -> float:
        raise AlpacaBloqueado(BLOQUEO_ALPACA)

    def cerrar(self) -> None:
        return None


def _numero_positivo(valor: Any, nombre: str) -> float:
    try:
        numero = float(valor)
    except (TypeError, ValueError) as exc:
        raise ErrorDeCorredor(f"{nombre} desconocido") from exc
    if not math.isfinite(numero) or numero <= 0:
        raise ErrorDeCorredor(f"{nombre} inválido")
    return numero


@dataclass
class MotorAlpaca:
    """Mantiene el contrato del motor, sin abrir recursos ni importar Lumibot."""

    api_key: str = field(default="", repr=False)
    api_secret: str = field(default="", repr=False)
    timeframe: str = "1d"
    directorio_logs: Path = field(default_factory=lambda: Path("logs"))

    @classmethod
    def desde_entorno(cls, timeframe: str = "1d", **extra: Any) -> MotorAlpaca:
        # No leer credenciales: el bloqueo no se resuelve instalando el SDK.
        return cls(timeframe=timeframe, **extra)

    def ejecutar(self, tarea: Callable[[Corredor], T]) -> T | None:
        raise AlpacaBloqueado(BLOQUEO_ALPACA)

    def cerrar(self) -> None:
        return None
