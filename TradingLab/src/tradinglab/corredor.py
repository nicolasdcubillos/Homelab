"""La frontera con el corredor: por dónde entra el mercado y salen las órdenes.

Todo lo que TradingLab sabe del mundo exterior pasa por aquí. El resto del
paquete depende de este `Protocol` y no de Lumibot ni de Alpaca, lo que compra
tres cosas concretas: los tests corren sin red ni credenciales, se puede probar
el sistema entero contra un corredor de mentira antes de conectar nada, y el día
que Lumibot cambie de API hay exactamente un archivo que tocar
(`corredor_alpaca.py`).

El corredor es también quien decide **cuánto cuesta operar**, y por eso el costo
viaja dentro de la ejecución en vez de aplicarse fuera. Contra Alpaca Paper el
precio de llenado ya viene con el deslizamiento real incorporado, así que añadir
un costo sintético encima lo contaría dos veces; en el corredor simulado, en
cambio, el llenado nos lo inventamos nosotros y el deslizamiento hay que ponerlo
a mano o la simulación miente sistemáticamente a favor.
"""

from __future__ import annotations

import logging
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Protocol, TypeVar

log = logging.getLogger("tradinglab.corredor")

T = TypeVar("T")


class ErrorDeCorredor(RuntimeError):
    """El corredor no pudo atender la petición."""


@dataclass(frozen=True)
class Ejecucion:
    """Una orden que se llenó."""

    instrumento: str
    cantidad: float
    precio: float
    #: Comisión más deslizamiento, ya en dinero. Puede ser 0 legítimamente:
    #: Alpaca no cobra comisión por acciones de EE. UU.
    costos: float = 0.0
    identificador: str | None = None


class Corredor(Protocol):
    """Lo mínimo que TradingLab necesita de un corredor."""

    def mercado_abierto(self) -> bool:
        """¿Se puede operar ahora mismo?

        Existe para no acumular órdenes que quedarían encoladas al cierre. Un
        corredor sin horario (cripto, o el simulado) puede devolver siempre
        `True`.
        """
        ...

    def cierres(self, instrumento: str, velas: int, timeframe: str) -> list[float]:
        """Precios de cierre, del más antiguo al más reciente.

        Devolver menos velas de las pedidas es válido —un ticker recién listado
        no tiene historia— y la estrategia se abstendrá por su cuenta.
        """
        ...

    def precio(self, instrumento: str) -> float | None:
        """Último precio conocido, o `None` si el corredor no lo tiene."""
        ...

    def comprar(self, instrumento: str, cantidad: float) -> Ejecucion: ...

    def vender(self, instrumento: str, cantidad: float) -> Ejecucion: ...

    def efectivo(self) -> float:
        """Dinero simulado disponible."""
        ...

    def cerrar(self) -> None:
        """Suelta conexiones. Debe poder llamarse más de una vez."""
        ...


class Motor(Protocol):
    """Quien decide *cuándo* y *dentro de qué sesión* corre una tarea de trading.

    Existe por una razón concreta y no por simetría. Lumibot no se deja usar
    como una librería a la que se le piden precios: es él quien abre la sesión,
    comprueba el horario del mercado y llama a nuestro código desde dentro. Es
    decir, invierte el control.

    En vez de pelear con eso —envolviendo sus objetos internos, que no son API
    pública— se le da la vuelta al ciclo: `ejecutar` recibe la tarea y la mete
    donde el motor sepa meterla. El motor simulado, que no tiene sesión ni
    horario, simplemente la llama.

    Devolver `None` significa «no llegué a ejecutar la tarea», y el caso normal
    en que eso ocurre es que el mercado esté cerrado. No es un error.
    """

    def ejecutar(self, tarea: Callable[[Corredor], T]) -> T | None: ...

    def cerrar(self) -> None: ...


# ---------------------------------------------------------------------------
# Corredor simulado
# ---------------------------------------------------------------------------


@dataclass
class CorredorSimulado:
    """Corredor de mentira, determinista, sin red.

    Tiene dos usos que justifican su existencia por separado. En los tests
    permite fijar una serie de precios exacta y comprobar qué hace el ciclo ante
    ella. Y en la VM permite arrancar TradingLab **antes** de tener credenciales
    de Alpaca: el dashboard empieza a recibir latidos y operaciones de verdad
    contra precios inventados, lo que verifica todo el contrato menos la última
    milla. Se activa con `tradinglab correr --simulado`.

    Los precios que no se le pasen explícitamente se generan con un paseo
    aleatorio de semilla fija: dos ejecuciones con la misma semilla producen las
    mismas series, así que un fallo se puede reproducir.
    """

    #: Series de cierre por instrumento, de la más antigua a la más reciente.
    series: dict[str, list[float]] = field(default_factory=dict)
    saldo: float = 10_000.0
    #: Coste de operar, en porcentaje del importe. El valor por defecto (5
    #: puntos básicos) es un deslizamiento plausible para un valor líquido, no
    #: una comisión: sirve para que la simulación no salga gratis.
    costo_pct: float = 0.05
    semilla: int = 20260904
    velas_generadas: int = 400
    precio_inicial: float = 100.0
    volatilidad_pct: float = 1.2
    _abierto: bool = True

    def __post_init__(self) -> None:
        self._azar = random.Random(self.semilla)

    # ------------------------------------------------------------------- datos

    def _serie(self, instrumento: str) -> list[float]:
        if instrumento not in self.series:
            self.series[instrumento] = self._generar(instrumento)
        return self.series[instrumento]

    def _generar(self, instrumento: str) -> list[float]:
        """Paseo aleatorio reproducible, distinto por instrumento.

        La semilla se combina con el nombre del ticker para que dos
        instrumentos no tengan la misma serie —lo que haría que cualquier
        estrategia comprara todo a la vez y ocultara errores de reparto.
        """
        azar = random.Random(f"{self.semilla}:{instrumento}")
        precio = self.precio_inicial
        serie = [precio]
        for _ in range(self.velas_generadas - 1):
            precio = max(0.01, precio * (1 + azar.gauss(0, self.volatilidad_pct / 100.0)))
            serie.append(round(precio, 4))
        return serie

    def mercado_abierto(self) -> bool:
        return self._abierto

    def cierres(self, instrumento: str, velas: int, timeframe: str) -> list[float]:
        del timeframe  # el corredor simulado no distingue marcos temporales
        serie = self._serie(instrumento)
        return list(serie[-velas:]) if velas > 0 else list(serie)

    def precio(self, instrumento: str) -> float | None:
        serie = self._serie(instrumento)
        return serie[-1] if serie else None

    def avanzar(self, pasos: int = 1) -> None:
        """Mueve todas las series hacia adelante. Solo para pruebas y demos."""
        for instrumento, serie in self.series.items():
            azar = random.Random(f"{self.semilla}:{instrumento}:{len(serie)}")
            for _ in range(pasos):
                ultimo = serie[-1]
                serie.append(
                    round(max(0.01, ultimo * (1 + azar.gauss(0, self.volatilidad_pct / 100.0))), 4)
                )

    # ------------------------------------------------------------------ órdenes

    def _ejecutar(self, instrumento: str, cantidad: float, signo: int) -> Ejecucion:
        precio = self.precio(instrumento)
        if precio is None:
            raise ErrorDeCorredor(f"sin precio para {instrumento}")
        # El deslizamiento siempre juega en contra: se compra un poco más caro
        # y se vende un poco más barato. Aplicarlo con signo, y no como un
        # costo aparte, es lo que hace que un viaje de ida y vuelta pierda
        # dinero en un mercado plano, tal como ocurre de verdad.
        efectivo = precio * (1 + signo * self.costo_pct / 100.0)
        costo = abs(efectivo - precio) * cantidad
        self.saldo -= signo * efectivo * cantidad
        return Ejecucion(
            instrumento=instrumento,
            cantidad=cantidad,
            precio=round(efectivo, 6),
            costos=round(costo, 6),
            identificador=f"sim-{instrumento}-{len(self._serie(instrumento))}",
        )

    def comprar(self, instrumento: str, cantidad: float) -> Ejecucion:
        return self._ejecutar(instrumento, cantidad, 1)

    def vender(self, instrumento: str, cantidad: float) -> Ejecucion:
        return self._ejecutar(instrumento, cantidad, -1)

    def efectivo(self) -> float:
        return self.saldo

    def cerrar(self) -> None:
        self._abierto = False


def serie_desde(valores: Sequence[float]) -> list[float]:
    """Azúcar para los tests: una serie explícita, sin sorpresas."""
    return [float(v) for v in valores]


@dataclass
class MotorSimulado:
    """Motor sin sesión: ejecuta la tarea aquí y ahora.

    Es la contrapartida trivial de `MotorAlpaca`, y esa trivialidad es
    justamente su valor: prueba que la inversión de control no obliga a fingir
    una sesión donde no la hay.
    """

    corredor: CorredorSimulado = field(default_factory=CorredorSimulado)

    def ejecutar(self, tarea: Callable[[Corredor], T]) -> T | None:
        return tarea(self.corredor)

    def cerrar(self) -> None:
        self.corredor.cerrar()
