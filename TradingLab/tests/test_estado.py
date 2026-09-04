"""La base que TradingLab publica: el lado visible del contrato.

Cada columna que se comprueba aquí acaba en una pantalla, así que un fallo en
este archivo es un fallo que el usuario ve.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from tradinglab.estado import (
    COMPRA,
    VENTA,
    AlmacenEstado,
    Apertura,
    PosicionAbierta,
    ahora_iso,
)


def test_el_latido_no_acumula_historial(almacen: AlmacenEstado) -> None:
    """Una sola fila, siempre.

    El dashboard lee con `ORDER BY latido_en DESC LIMIT 1`, así que toleraría un
    historial; pero ese historial crecería sin límite en una VM pequeña y no le
    serviría a nadie.
    """
    almacen.latir(detalle="primera", posiciones_abiertas=1, version="tradinglab 0.1.0")
    almacen.latir(detalle="segunda", posiciones_abiertas=2, version="tradinglab 0.1.0")

    filas = almacen.conexion.execute("SELECT COUNT(*) AS n FROM estado_motor").fetchone()
    assert filas["n"] == 1

    ultimo = almacen.ultimo_latido()
    assert ultimo is not None
    assert ultimo["detalle"] == "segunda"
    assert ultimo["posiciones_abiertas"] == 2


def test_las_columnas_son_las_que_el_dashboard_consulta(almacen: AlmacenEstado) -> None:
    """Réplica literal de la consulta de `AdaptadorTradingLab`.

    Si alguien renombra una columna, este test se cae antes que la pantalla.
    """
    almacen.latir(detalle="ok", posiciones_abiertas=0, version="tradinglab 0.1.0")
    almacen.registrar_apertura(
        Apertura(instrumento="AAPL", lado=COMPRA, cantidad=3, precio_entrada=100.0)
    )

    almacen.conexion.execute(
        "SELECT latido_en, detalle, posiciones_abiertas, version "
        "FROM estado_motor ORDER BY latido_en DESC LIMIT 1"
    ).fetchone()
    almacen.conexion.execute(
        "SELECT instrumento, lado, cantidad, precio_entrada, precio_salida, "
        "pnl_absoluto, pnl_pct, abierta_en, cerrada_en "
        "FROM operaciones ORDER BY abierta_en DESC LIMIT ?",
        (20,),
    ).fetchall()
    almacen.conexion.execute(
        "SELECT COUNT(*) AS n, SUM(pnl_absoluto) AS pnl, SUM(costos) AS costos, "
        "MAX(pnl_pct) AS mejor, MIN(pnl_pct) AS peor "
        "FROM operaciones WHERE cerrada_en IS NOT NULL"
    ).fetchone()


def test_el_esquema_rechaza_un_lado_que_la_interfaz_no_sabe_etiquetar(
    almacen: AlmacenEstado,
) -> None:
    """El `CHECK` de `lado`, que es la razón de que exista.

    La interfaz mapea `compra`/`venta` a etiquetas. Un `long` escrito por error
    aparecería como una fila con un guion en lugar de la operación. Es mejor que
    la escritura falle aquí.
    """
    with pytest.raises(sqlite3.IntegrityError):
        almacen.conexion.execute(
            "INSERT INTO operaciones (instrumento, lado, cantidad, precio_entrada, abierta_en) "
            "VALUES ('AAPL', 'long', 1, 100.0, ?)",
            (ahora_iso(),),
        )


def test_registrar_apertura_valida_el_lado(almacen: AlmacenEstado) -> None:
    with pytest.raises(ValueError, match="lado inválido"):
        almacen.registrar_apertura(
            Apertura(instrumento="AAPL", lado="long", cantidad=1, precio_entrada=100.0)
        )


def test_el_resultado_descuenta_los_costos_de_ida_y_vuelta(almacen: AlmacenEstado) -> None:
    """La pantalla afirma «ya están descontados del resultado».

    Es parte del contrato, no una comodidad: si el PnL fuera bruto, el panel
    estaría mintiendo con letra pequeña propia.
    """
    identificador = almacen.registrar_apertura(
        Apertura(instrumento="AAPL", lado=COMPRA, cantidad=10, precio_entrada=100.0, costos=1.5)
    )

    almacen.registrar_cierre(identificador, precio_salida=110.0, costos_salida=2.5, motivo="prueba")

    fila = almacen.conexion.execute(
        "SELECT pnl_absoluto, pnl_pct, costos, motivo_salida FROM operaciones WHERE id = ?",
        (identificador,),
    ).fetchone()
    # Bruto 100, menos 4 de costos.
    assert fila["pnl_absoluto"] == pytest.approx(96.0)
    assert fila["costos"] == pytest.approx(4.0)
    # El porcentaje se mide contra el capital que la operación inmovilizó (1000).
    assert fila["pnl_pct"] == pytest.approx(9.6)
    assert fila["motivo_salida"] == "prueba"


def test_una_venta_gana_cuando_el_precio_baja(almacen: AlmacenEstado) -> None:
    """El lado corto existe en el esquema porque el contrato es común con Freqtrade.

    TradingLab no lo usa —vender acciones en corto exige localización de
    títulos—, pero la contabilidad tiene que ser correcta si algún día se usa.
    """
    identificador = almacen.registrar_apertura(
        Apertura(instrumento="AAPL", lado=VENTA, cantidad=10, precio_entrada=100.0)
    )

    almacen.registrar_cierre(identificador, precio_salida=90.0)

    fila = almacen.conexion.execute(
        "SELECT pnl_absoluto FROM operaciones WHERE id = ?", (identificador,)
    ).fetchone()
    assert fila["pnl_absoluto"] == pytest.approx(100.0)


def test_cerrar_una_operacion_inexistente_falla(almacen: AlmacenEstado) -> None:
    with pytest.raises(ValueError, match="no existe la operación"):
        almacen.registrar_cierre(999, precio_salida=1.0)


def test_abiertas_solo_devuelve_las_vivas(almacen: AlmacenEstado) -> None:
    viva = almacen.registrar_apertura(
        Apertura(instrumento="AAPL", lado=COMPRA, cantidad=1, precio_entrada=100.0)
    )
    muerta = almacen.registrar_apertura(
        Apertura(instrumento="MSFT", lado=COMPRA, cantidad=1, precio_entrada=200.0)
    )
    almacen.registrar_cierre(muerta, precio_salida=210.0)

    abiertas = almacen.abiertas()

    assert [posicion.id for posicion in abiertas] == [viva]
    assert almacen.instrumentos_abiertos() == {"AAPL"}


def test_el_pnl_del_dia_solo_cuenta_lo_cerrado(almacen: AlmacenEstado) -> None:
    """Frenar por pérdidas no realizadas convertiría cualquier vaivén en una parada.

    Una posición abierta que va perdiendo todavía puede darse la vuelta; una
    cerrada, no. El freno diario se calcula sobre lo segundo.
    """
    almacen.registrar_apertura(
        Apertura(instrumento="AAPL", lado=COMPRA, cantidad=100, precio_entrada=100.0)
    )
    cerrada = almacen.registrar_apertura(
        Apertura(instrumento="MSFT", lado=COMPRA, cantidad=10, precio_entrada=100.0)
    )
    momento = ahora_iso()
    almacen.registrar_cierre(cerrada, precio_salida=90.0, momento=momento)

    assert almacen.pnl_del_dia(momento[:10]) == pytest.approx(-100.0)


def test_el_pnl_del_dia_ignora_los_otros_dias(almacen: AlmacenEstado) -> None:
    identificador = almacen.registrar_apertura(
        Apertura(instrumento="AAPL", lado=COMPRA, cantidad=10, precio_entrada=100.0)
    )
    almacen.registrar_cierre(identificador, precio_salida=80.0, momento="2020-01-01T10:00:00+00:00")

    assert almacen.pnl_del_dia("2026-09-04") == pytest.approx(0.0)
    assert almacen.pnl_del_dia("2020-01-01") == pytest.approx(-200.0)


def test_las_marcas_de_tiempo_ordenan_alfabeticamente(almacen: AlmacenEstado) -> None:
    """El formato importa: el dashboard ordena por texto, no por fecha.

    ISO-8601 con desfase explícito hace que el orden alfabético coincida con el
    cronológico. Un formato local, o mezclar `Z` con `+00:00`, rompería
    `ORDER BY abierta_en DESC` de forma silenciosa.
    """
    for indice, momento in enumerate(
        ["2026-01-01T08:00:00+00:00", "2026-01-01T09:00:00+00:00", "2026-01-02T07:00:00+00:00"]
    ):
        almacen.registrar_apertura(
            Apertura(instrumento=f"T{indice}", lado=COMPRA, cantidad=1, precio_entrada=1.0),
            momento=momento,
        )

    filas = almacen.ultimas(10)

    assert [fila["instrumento"] for fila in filas] == ["T2", "T1", "T0"]
    assert ahora_iso().endswith("+00:00")


def test_la_base_se_crea_con_su_carpeta(tmp_path: Path) -> None:
    ruta = tmp_path / "datos" / "anidados" / "tradinglab.db"

    with AlmacenEstado(ruta) as almacen:
        almacen.latir(detalle="hola")

    assert ruta.exists()


def test_usar_el_almacen_sin_abrir_es_un_error(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="sin abrir"):
        AlmacenEstado(tmp_path / "x.db").conexion  # noqa: B018


@pytest.mark.parametrize(
    ("lado", "precio", "esperado_pnl", "esperado_pct"),
    [
        (COMPRA, 110.0, 100.0, 10.0),
        (COMPRA, 90.0, -100.0, -10.0),
        (VENTA, 90.0, 100.0, 10.0),
        (VENTA, 110.0, -100.0, -10.0),
    ],
)
def test_variacion_de_una_posicion_viva(
    lado: str, precio: float, esperado_pnl: float, esperado_pct: float
) -> None:
    posicion = PosicionAbierta(
        id=1,
        instrumento="AAPL",
        lado=lado,
        cantidad=10,
        precio_entrada=100.0,
        costos=0.0,
        abierta_en=ahora_iso(),
    )

    assert posicion.pnl_bruto(precio) == pytest.approx(esperado_pnl)
    assert posicion.variacion_pct(precio) == pytest.approx(esperado_pct)
