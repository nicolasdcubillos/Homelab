"""El ciclo: riesgo, órdenes y contabilidad.

Las reglas que se prueban aquí son las que no se negocian. Una estrategia puede
ser mala y perder dinero simulado sin que pase nada; si el freno de pérdida
diaria no funciona, el bot puede perderlo todo en una sesión mientras nadie
mira.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import pytest

from conftest import CONFIG_BASE
from tradinglab.ciclo import (
    POR_RETIRADA,
    POR_STOP_LOSS,
    POR_TAKE_PROFIT,
    Ciclo,
)
from tradinglab.config import ConfigCompartida
from tradinglab.corredor import CorredorSimulado, Ejecucion, ErrorDeCorredor
from tradinglab.estado import COMPRA, AlmacenEstado, Apertura
from tradinglab.estrategia import ENTRAR, MANTENER, SALIR, Senal

# ---------------------------------------------------------------------------
# Dobles
# ---------------------------------------------------------------------------


@dataclass
class EstrategiaFija:
    """Dice siempre lo mismo, para poder probar el riesgo sin ruido de mercado."""

    accion_fuera: str = MANTENER
    accion_dentro: str = MANTENER
    nombre: str = "fija"
    etiqueta: str = "Estrategia fija"
    velas: int = 5

    @property
    def velas_necesarias(self) -> int:
        return self.velas

    def evaluar(self, cierres, *, con_posicion: bool) -> Senal:
        accion = self.accion_dentro if con_posicion else self.accion_fuera
        return Senal(accion, "porque sí")


@dataclass
class CorredorFijo:
    """Corredor con precios que el test decide, y que registra lo que se le pidió."""

    precios: dict[str, float]
    abierto: bool = True
    fallar_compra: bool = False
    fallar_venta: bool = False

    def __post_init__(self) -> None:
        self.compras: list[tuple[str, float]] = []
        self.ventas: list[tuple[str, float]] = []

    def mercado_abierto(self) -> bool:
        return self.abierto

    def cierres(self, instrumento: str, velas: int, timeframe: str) -> list[float]:
        return [self.precios.get(instrumento, 100.0)] * velas

    def precio(self, instrumento: str) -> float | None:
        return self.precios.get(instrumento)

    def comprar(self, instrumento: str, cantidad: float) -> Ejecucion:
        if self.fallar_compra:
            raise ErrorDeCorredor("el corredor dijo que no")
        self.compras.append((instrumento, cantidad))
        return Ejecucion(instrumento, cantidad, self.precios[instrumento], costos=0.0)

    def vender(self, instrumento: str, cantidad: float) -> Ejecucion:
        if self.fallar_venta:
            raise ErrorDeCorredor("el corredor dijo que no")
        self.ventas.append((instrumento, cantidad))
        return Ejecucion(instrumento, cantidad, self.precios[instrumento], costos=0.0)

    def efectivo(self) -> float:
        return 1_000_000.0

    def cerrar(self) -> None:
        self.abierto = False


def _config(**cambios) -> ConfigCompartida:
    base = ConfigCompartida(
        habilitado=True,
        version=1,
        instrumentos=("AAPL", "MSFT"),
        estrategia="fija",
        timeframe="1h",
        capital_simulado=float(CONFIG_BASE["capital_simulado"]),
        max_posiciones_abiertas=int(CONFIG_BASE["max_posiciones_abiertas"]),
        stop_loss_pct=float(CONFIG_BASE["stop_loss_pct"]),
        take_profit_pct=float(CONFIG_BASE["take_profit_pct"]),
        max_perdida_diaria_pct=float(CONFIG_BASE["max_perdida_diaria_pct"]),
    )
    return replace(base, **cambios)


def _ciclo(almacen, corredor, estrategia=None, config=None, **extra) -> Ciclo:
    return Ciclo(
        config=config or _config(),
        estrategia=estrategia or EstrategiaFija(),
        corredor=corredor,
        almacen=almacen,
        **extra,
    )


# ---------------------------------------------------------------------------
# Salidas
# ---------------------------------------------------------------------------


def test_el_stop_loss_cierra_la_posicion(almacen: AlmacenEstado) -> None:
    almacen.registrar_apertura(
        Apertura(instrumento="AAPL", lado=COMPRA, cantidad=10, precio_entrada=100.0)
    )
    corredor = CorredorFijo({"AAPL": 94.0, "MSFT": 100.0})

    resultado = _ciclo(almacen, corredor).ejecutar()

    assert resultado.cierres == 1
    assert corredor.ventas == [("AAPL", 10.0)]
    fila = almacen.ultimas(1)[0]
    assert fila["motivo_salida"] == POR_STOP_LOSS
    assert fila["cerrada_en"] is not None


def test_el_take_profit_cierra_la_posicion(almacen: AlmacenEstado) -> None:
    almacen.registrar_apertura(
        Apertura(instrumento="AAPL", lado=COMPRA, cantidad=10, precio_entrada=100.0)
    )
    corredor = CorredorFijo({"AAPL": 111.0})

    resultado = _ciclo(almacen, corredor).ejecutar()

    assert resultado.cierres == 1
    assert almacen.ultimas(1)[0]["motivo_salida"] == POR_TAKE_PROFIT


def test_quitar_un_ticker_de_la_lista_cierra_su_posicion(almacen: AlmacenEstado) -> None:
    """Quitarlo de la configuración es una orden de salida implícita.

    Dejar la posición viva sin vigilarla sería lo peor de ambos mundos:
    expuesta, y fuera del alcance de la estrategia.
    """
    almacen.registrar_apertura(
        Apertura(instrumento="TSLA", lado=COMPRA, cantidad=5, precio_entrada=100.0)
    )
    corredor = CorredorFijo({"TSLA": 101.0})

    resultado = _ciclo(almacen, corredor, config=_config(instrumentos=("AAPL",))).ejecutar()

    assert resultado.cierres == 1
    assert almacen.ultimas(1)[0]["motivo_salida"] == POR_RETIRADA


def test_la_senal_de_salida_cierra_con_su_motivo(almacen: AlmacenEstado) -> None:
    almacen.registrar_apertura(
        Apertura(instrumento="AAPL", lado=COMPRA, cantidad=10, precio_entrada=100.0)
    )
    corredor = CorredorFijo({"AAPL": 101.0})

    _ciclo(almacen, corredor, estrategia=EstrategiaFija(accion_dentro=SALIR)).ejecutar()

    assert "porque sí" in almacen.ultimas(1)[0]["motivo_salida"]


def test_sin_precio_no_se_toca_la_posicion(almacen: AlmacenEstado) -> None:
    """Un hueco de datos no puede convertirse en una venta.

    Sin precio no se puede saber si el stop está tocado, y cerrar «por si acaso»
    materializaría una pérdida que quizá no existe.
    """
    almacen.registrar_apertura(
        Apertura(instrumento="AAPL", lado=COMPRA, cantidad=10, precio_entrada=100.0)
    )
    corredor = CorredorFijo({})

    resultado = _ciclo(almacen, corredor).ejecutar()

    assert resultado.cierres == 0
    assert corredor.ventas == []


def test_un_fallo_al_cerrar_se_cuenta_pero_no_rompe(almacen: AlmacenEstado) -> None:
    almacen.registrar_apertura(
        Apertura(instrumento="AAPL", lado=COMPRA, cantidad=10, precio_entrada=100.0)
    )
    corredor = CorredorFijo({"AAPL": 90.0}, fallar_venta=True)

    resultado = _ciclo(almacen, corredor).ejecutar()

    assert resultado.cierres == 0
    assert resultado.abiertas == 1
    assert any("no se pudo cerrar" in incidencia for incidencia in resultado.incidencias)
    assert "no se pudo cerrar" in resultado.detalle


# ---------------------------------------------------------------------------
# Entradas
# ---------------------------------------------------------------------------


def test_la_senal_de_entrada_abre_una_posicion(almacen: AlmacenEstado) -> None:
    corredor = CorredorFijo({"AAPL": 100.0, "MSFT": 200.0})

    resultado = _ciclo(almacen, corredor, estrategia=EstrategiaFija(accion_fuera=ENTRAR)).ejecutar()

    assert resultado.aperturas == 2
    # Capital 10.000 entre 3 posiciones = 3.333,33 por posición.
    assert corredor.compras == [("AAPL", 33.0), ("MSFT", 16.0)]


def test_solo_se_compran_acciones_enteras(almacen: AlmacenEstado) -> None:
    """Alpaca admite fraccionarias solo en algunos tickers y con reglas propias.

    Redondear hacia abajo es aburrido, funciona siempre y deja la contabilidad
    exacta.
    """
    corredor = CorredorFijo({"AAPL": 999.0})

    _ciclo(
        almacen,
        corredor,
        estrategia=EstrategiaFija(accion_fuera=ENTRAR),
        config=_config(instrumentos=("AAPL",)),
    ).ejecutar()

    assert corredor.compras == [("AAPL", 3.0)]


def test_un_ticker_mas_caro_que_el_cupo_se_explica(almacen: AlmacenEstado) -> None:
    corredor = CorredorFijo({"BRK.A": 700_000.0})

    resultado = _ciclo(
        almacen,
        corredor,
        estrategia=EstrategiaFija(accion_fuera=ENTRAR),
        config=_config(instrumentos=("BRK.A",)),
    ).ejecutar()

    assert resultado.aperturas == 0
    assert any("no alcanza para una acción" in i for i in resultado.incidencias)


def test_no_se_pasa_del_maximo_de_posiciones(almacen: AlmacenEstado) -> None:
    corredor = CorredorFijo({"A": 10.0, "B": 10.0, "C": 10.0, "D": 10.0})

    resultado = _ciclo(
        almacen,
        corredor,
        estrategia=EstrategiaFija(accion_fuera=ENTRAR),
        config=_config(instrumentos=("A", "B", "C", "D"), max_posiciones_abiertas=2),
    ).ejecutar()

    assert resultado.aperturas == 2
    assert resultado.abiertas == 2


def test_no_se_duplica_una_posicion_ya_abierta(almacen: AlmacenEstado) -> None:
    almacen.registrar_apertura(
        Apertura(instrumento="AAPL", lado=COMPRA, cantidad=1, precio_entrada=100.0)
    )
    corredor = CorredorFijo({"AAPL": 100.0, "MSFT": 100.0})

    _ciclo(almacen, corredor, estrategia=EstrategiaFija(accion_fuera=ENTRAR)).ejecutar()

    assert [instrumento for instrumento, _ in corredor.compras] == ["MSFT"]


def test_con_el_mercado_cerrado_no_se_abre_nada(almacen: AlmacenEstado) -> None:
    """Evita acumular órdenes que quedarían encoladas hasta la apertura.

    Una orden encolada se ejecuta a un precio que nadie evaluó, horas después de
    que la señal tuviera sentido.
    """
    corredor = CorredorFijo({"AAPL": 100.0}, abierto=False)

    resultado = _ciclo(almacen, corredor, estrategia=EstrategiaFija(accion_fuera=ENTRAR)).ejecutar()

    assert resultado.aperturas == 0


def test_un_fallo_al_abrir_no_impide_intentar_el_siguiente(almacen: AlmacenEstado) -> None:
    corredor = CorredorFijo({"AAPL": 100.0, "MSFT": 100.0}, fallar_compra=True)

    resultado = _ciclo(almacen, corredor, estrategia=EstrategiaFija(accion_fuera=ENTRAR)).ejecutar()

    assert resultado.aperturas == 0
    # Se intentaron los dos: el fallo del primero no aborta la vuelta.
    assert len(resultado.incidencias) == 2


def test_la_misma_incidencia_no_se_repite(almacen: AlmacenEstado) -> None:
    """El detalle del latido cabe en la pantalla de un celular.

    Veinte tickers sin precio no pueden producir veinte veces la misma línea.
    """
    corredor = CorredorFijo({}, fallar_compra=True)

    ciclo = _ciclo(
        almacen,
        corredor,
        estrategia=EstrategiaFija(accion_fuera=ENTRAR),
        config=_config(instrumentos=("AAPL", "MSFT")),
    )
    ciclo._incidencia("mismo texto")
    ciclo._incidencia("mismo texto")

    assert ciclo.incidencias == ["mismo texto"]


def test_la_trm_del_dia_se_anota_en_la_apertura(almacen: AlmacenEstado) -> None:
    corredor = CorredorFijo({"AAPL": 100.0})

    _ciclo(
        almacen,
        corredor,
        estrategia=EstrategiaFija(accion_fuera=ENTRAR),
        config=_config(instrumentos=("AAPL",)),
        trm=4123.45,
    ).ejecutar()

    assert almacen.ultimas(1)[0]["trm"] == pytest.approx(4123.45)


# ---------------------------------------------------------------------------
# Freno diario
# ---------------------------------------------------------------------------


def test_el_freno_diario_impide_abrir(almacen: AlmacenEstado) -> None:
    perdedora = almacen.registrar_apertura(
        Apertura(instrumento="OLD", lado=COMPRA, cantidad=100, precio_entrada=100.0)
    )
    # 600 perdidos hoy contra un tope de 500 (5 % de 10.000).
    almacen.registrar_cierre(perdedora, precio_salida=94.0)
    corredor = CorredorFijo({"AAPL": 100.0, "MSFT": 100.0})

    resultado = _ciclo(almacen, corredor, estrategia=EstrategiaFija(accion_fuera=ENTRAR)).ejecutar()

    assert resultado.frenado is True
    assert resultado.aperturas == 0
    assert "freno diario activo" in resultado.detalle


def test_el_freno_diario_no_impide_cerrar(almacen: AlmacenEstado) -> None:
    """Un freno que impidiera salir dejaría atrapadas justo las que van mal."""
    perdedora = almacen.registrar_apertura(
        Apertura(instrumento="OLD", lado=COMPRA, cantidad=100, precio_entrada=100.0)
    )
    almacen.registrar_cierre(perdedora, precio_salida=94.0)
    almacen.registrar_apertura(
        Apertura(instrumento="AAPL", lado=COMPRA, cantidad=10, precio_entrada=100.0)
    )
    corredor = CorredorFijo({"AAPL": 90.0})

    resultado = _ciclo(almacen, corredor).ejecutar()

    assert resultado.frenado is True
    assert resultado.cierres == 1


def test_una_perdida_por_debajo_del_tope_no_frena(almacen: AlmacenEstado) -> None:
    perdedora = almacen.registrar_apertura(
        Apertura(instrumento="OLD", lado=COMPRA, cantidad=10, precio_entrada=100.0)
    )
    almacen.registrar_cierre(perdedora, precio_salida=99.0)  # -10, muy lejos de -500
    corredor = CorredorFijo({"AAPL": 100.0})

    resultado = _ciclo(
        almacen,
        corredor,
        estrategia=EstrategiaFija(accion_fuera=ENTRAR),
        config=_config(instrumentos=("AAPL",)),
    ).ejecutar()

    assert resultado.frenado is False
    assert resultado.aperturas == 1


# ---------------------------------------------------------------------------
# Detalle para el panel
# ---------------------------------------------------------------------------


def test_el_detalle_pone_los_problemas_primero(almacen: AlmacenEstado) -> None:
    """Los problemas son la razón por la que alguien abre esa pantalla."""
    corredor = CorredorFijo({"AAPL": 100.0}, fallar_compra=True)

    resultado = _ciclo(
        almacen,
        corredor,
        estrategia=EstrategiaFija(accion_fuera=ENTRAR),
        config=_config(instrumentos=("AAPL",)),
        aviso="«fija» no existe; se usa cruce_medias.",
    ).ejecutar()

    partes = resultado.detalle.split(" | ")
    assert "no existe" in partes[0]
    assert "no se pudo abrir" in partes[1]
    assert partes[-1].startswith("Estrategia fija ·")


def test_el_detalle_resume_el_movimiento(almacen: AlmacenEstado) -> None:
    corredor = CorredorFijo({"AAPL": 100.0})

    resultado = _ciclo(
        almacen,
        corredor,
        estrategia=EstrategiaFija(accion_fuera=ENTRAR),
        config=_config(instrumentos=("AAPL",)),
    ).ejecutar()

    assert resultado.detalle == "Estrategia fija · 1 posición(es) · 1 abierta(s)"


# ---------------------------------------------------------------------------
# Contra el corredor simulado
# ---------------------------------------------------------------------------


def test_un_viaje_de_ida_y_vuelta_pierde_por_el_deslizamiento(almacen: AlmacenEstado) -> None:
    """El deslizamiento siempre juega en contra, y por eso lleva signo.

    Si se aplicara como un costo aparte, un viaje de ida y vuelta en un mercado
    plano saldría a cero y la simulación mentiría a favor.
    """
    corredor = CorredorSimulado(series={"AAPL": [100.0] * 60}, costo_pct=0.5)

    compra = corredor.comprar("AAPL", 10)
    venta = corredor.vender("AAPL", 10)

    assert compra.precio > 100.0
    assert venta.precio < 100.0
    assert corredor.efectivo() < 10_000.0
