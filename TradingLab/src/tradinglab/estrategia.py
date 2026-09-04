"""Las estrategias: la única parte que opina sobre el mercado.

Está deliberadamente aislada. No conoce el corredor, ni la base de datos, ni la
configuración compartida: recibe una serie de precios y devuelve una señal. Esa
frontera es lo que permite probar las decisiones sin red, sin credenciales y sin
esperar a que abra la bolsa.

Sobre las estrategias que hay aquí conviene ser honesto, porque la pantalla ya
lo es: **son ejemplos didácticos, no una fuente de rentabilidad**. El cruce de
medias y la reversión por RSI son los dos casos canónicos de manual; están
implementados con cuidado y sin trampas de mirada al futuro, pero la evidencia
sobre operativa frecuente con reglas así de simples es mala. Existen para que el
sistema tenga algo real que ejecutar y medir, y para que quien quiera probar una
idea propia tenga dónde enchufarla.

Los indicadores se calculan a mano y no con pandas. Son medias y variaciones
sobre unas pocas decenas de valores: traer un motor numérico entero para eso
costaría memoria en una VM compartida y volvería lentos unos tests que ahora son
instantáneos.

**Solo se abren posiciones largas.** El esquema admite `venta` porque el
contrato es común con Freqtrade, que sí opera en corto con cripto; pero vender
en corto acciones exige localización de títulos y trae costos que una simulación
honesta no puede ignorar. Aquí una señal bajista cierra la posición, no abre una
inversa.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

#: Las tres únicas cosas que una estrategia puede querer.
ENTRAR = "entrar"
SALIR = "salir"
MANTENER = "mantener"


@dataclass(frozen=True)
class Senal:
    """Lo que la estrategia opina sobre un instrumento, con su porqué.

    El motivo no es decorativo: acaba escrito en `operaciones.motivo_salida` y
    es lo que permite, semanas después, distinguir una salida por señal de una
    por stop loss sin tener que reconstruir el estado del mercado de ese día.
    """

    accion: str
    motivo: str = ""

    @property
    def quiere_entrar(self) -> bool:
        return self.accion == ENTRAR

    @property
    def quiere_salir(self) -> bool:
        return self.accion == SALIR


MANTENERSE = Senal(MANTENER)


class Estrategia(Protocol):
    """Contrato mínimo de una estrategia."""

    #: Identificador que se escribe en el campo «Estrategia» del dashboard.
    #: En minúsculas y con guion bajo, porque se teclea desde el celular.
    nombre: str
    #: Cómo se llama en el panel. Separado del identificador para que el detalle
    #: del latido se lea como una frase y no como una variable.
    etiqueta: str

    @property
    def velas_necesarias(self) -> int:
        """Cuántas velas hay que pedirle al corredor para poder decidir."""
        ...

    def evaluar(self, cierres: Sequence[float], *, con_posicion: bool) -> Senal:
        """Opina sobre un instrumento a la vista de sus precios de cierre.

        `cierres` va del más antiguo al más reciente. `con_posicion` indica si
        ya hay una posición abierta: la misma lectura del mercado significa
        cosas distintas según se esté dentro o fuera.
        """
        ...


# ---------------------------------------------------------------------------
# Indicadores
# ---------------------------------------------------------------------------


def media_simple(valores: Sequence[float], ventana: int) -> float | None:
    """Media aritmética de los últimos `ventana` valores."""
    if ventana <= 0 or len(valores) < ventana:
        return None
    return sum(valores[-ventana:]) / ventana


def rsi(valores: Sequence[float], periodo: int = 14) -> float | None:
    """Índice de fuerza relativa de Wilder.

    Se usa la media simple de ganancias y pérdidas sobre los últimos `periodo`
    movimientos. Wilder original suaviza exponencialmente, lo que da un valor
    algo distinto; para decidir por encima o debajo de umbrales tan anchos como
    30 y 70 la diferencia es irrelevante, y esta versión no arrastra estado
    entre llamadas, que es lo que la hace verificable de un vistazo.
    """
    if periodo <= 0 or len(valores) < periodo + 1:
        return None
    ganancias = 0.0
    perdidas = 0.0
    for anterior, actual in zip(valores[-periodo - 1 : -1], valores[-periodo:], strict=True):
        cambio = actual - anterior
        if cambio >= 0:
            ganancias += cambio
        else:
            perdidas -= cambio
    if perdidas == 0:
        # Sin una sola bajada no hay cociente que calcular. 100 es el límite al
        # que tiende el indicador, y significa exactamente lo que parece:
        # sobrecompra total.
        return 100.0
    fuerza = (ganancias / periodo) / (perdidas / periodo)
    return 100.0 - (100.0 / (1.0 + fuerza))


# ---------------------------------------------------------------------------
# Estrategias
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CruceDeMedias:
    """Entra cuando la media rápida cruza por encima de la lenta, y sale al revés.

    Requiere el valor de ambas medias en la vela actual **y en la anterior**,
    porque lo que dispara la señal es el cruce y no la posición relativa: sin
    comparar con el paso anterior, un mercado que lleva semanas alcista emitiría
    una orden de compra en cada ciclo.
    """

    ventana_rapida: int = 20
    ventana_lenta: int = 50
    nombre: str = "cruce_medias"
    etiqueta: str = "Cruce de medias"

    def __post_init__(self) -> None:
        if self.ventana_rapida >= self.ventana_lenta:
            raise ValueError("la ventana rápida debe ser menor que la lenta")

    @property
    def velas_necesarias(self) -> int:
        # Una vela extra para poder mirar el paso anterior.
        return self.ventana_lenta + 1

    def evaluar(self, cierres: Sequence[float], *, con_posicion: bool) -> Senal:
        if len(cierres) < self.velas_necesarias:
            return MANTENERSE

        previos = cierres[:-1]
        rapida_hoy = media_simple(cierres, self.ventana_rapida)
        lenta_hoy = media_simple(cierres, self.ventana_lenta)
        rapida_ayer = media_simple(previos, self.ventana_rapida)
        lenta_ayer = media_simple(previos, self.ventana_lenta)
        if None in (rapida_hoy, lenta_hoy, rapida_ayer, lenta_ayer):
            return MANTENERSE
        assert rapida_hoy is not None and lenta_hoy is not None
        assert rapida_ayer is not None and lenta_ayer is not None

        cruce_alcista = rapida_ayer <= lenta_ayer and rapida_hoy > lenta_hoy
        cruce_bajista = rapida_ayer >= lenta_ayer and rapida_hoy < lenta_hoy

        if con_posicion and cruce_bajista:
            return Senal(
                SALIR,
                f"la media de {self.ventana_rapida} cruzó por debajo de la de {self.ventana_lenta}",
            )
        if not con_posicion and cruce_alcista:
            return Senal(
                ENTRAR,
                f"la media de {self.ventana_rapida} cruzó por encima de la de {self.ventana_lenta}",
            )
        return MANTENERSE


@dataclass(frozen=True)
class ReversionRSI:
    """Compra la sobreventa y suelta en la sobrecompra.

    Apuesta por que un movimiento exagerado se corrige. Funciona en rangos y
    pierde con constancia en tendencias fuertes, que es justo cuando el cruce de
    medias acierta; por eso están las dos y no una sola.
    """

    periodo: int = 14
    umbral_compra: float = 30.0
    umbral_venta: float = 70.0
    nombre: str = "reversion_rsi"
    etiqueta: str = "Reversión RSI"

    def __post_init__(self) -> None:
        if not 0 < self.umbral_compra < self.umbral_venta < 100:
            raise ValueError("los umbrales deben cumplir 0 < compra < venta < 100")

    @property
    def velas_necesarias(self) -> int:
        return self.periodo + 1

    def evaluar(self, cierres: Sequence[float], *, con_posicion: bool) -> Senal:
        valor = rsi(cierres, self.periodo)
        if valor is None:
            return MANTENERSE
        if con_posicion and valor >= self.umbral_venta:
            return Senal(SALIR, f"RSI en {valor:.1f}, sobrecompra")
        if not con_posicion and valor <= self.umbral_compra:
            return Senal(ENTRAR, f"RSI en {valor:.1f}, sobreventa")
        return MANTENERSE


#: Estrategias disponibles, por el nombre que se escribe en el dashboard. El
#: campo «estrategia» de la configuración compartida se valida allí como
#: identificador (letras, números y guion bajo), así que encaja tal cual.
DISPONIBLES: dict[str, Estrategia] = {
    CruceDeMedias().nombre: CruceDeMedias(),
    ReversionRSI().nombre: ReversionRSI(),
}

POR_DEFECTO = CruceDeMedias().nombre


def construir(nombre: str) -> tuple[Estrategia, str]:
    """Resuelve el nombre escrito en el dashboard a una estrategia concreta.

    Devuelve también un aviso cuando hubo que sustituir, en vez de fallar. Un
    nombre desconocido suele ser una errata de quien configuró, y dejar el bot
    muerto por una errata es peor que operar la estrategia por defecto
    diciéndolo bien claro en el panel.
    """
    limpio = (nombre or "").strip()
    if not limpio:
        return DISPONIBLES[POR_DEFECTO], ""
    if limpio in DISPONIBLES:
        return DISPONIBLES[limpio], ""
    return (
        DISPONIBLES[POR_DEFECTO],
        f"«{limpio}» no existe; se usa {POR_DEFECTO}. "
        f"Disponibles: {', '.join(sorted(DISPONIBLES))}.",
    )
