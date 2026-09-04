"""La línea de comandos.

Es la superficie que se usa desde la VM: si `correr --simulado` no funciona, no
hay forma de verificar el contrato con el dashboard antes de tener credenciales
de Alpaca.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import CONFIG_BASE, escribir_config
from tradinglab.cli import main
from tradinglab.estado import COMPRA, AlmacenEstado, Apertura


@pytest.fixture(autouse=True)
def _sin_red(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ningún test del CLI sale a internet a buscar la TRM."""
    monkeypatch.setattr("tradinglab.trm.ProveedorTRM.obtener", lambda self, hoy=None: 4100.0)


def _rutas(tmp_path: Path) -> tuple[str, str]:
    return str(tmp_path / "dashboard.db"), str(tmp_path / "tradinglab.db")


def test_correr_simulado_publica_un_latido(tmp_path: Path) -> None:
    """El camino que permite arrancar antes de tener credenciales.

    Verifica el contrato entero salvo la última milla: el dashboard empieza a
    recibir latidos y operaciones reales contra precios inventados.
    """
    dashboard, propia = _rutas(tmp_path)
    escribir_config(Path(dashboard), datos={**CONFIG_BASE, "instrumentos": ["AAPL"]})

    codigo = main(
        ["--db-dashboard", dashboard, "--db", propia, "correr", "--simulado", "--una-vez"]
    )

    assert codigo == 0
    with AlmacenEstado(propia) as almacen:
        latido = almacen.ultimo_latido()
    assert latido is not None
    assert latido["version"].startswith("tradinglab ")


def test_correr_simulado_no_necesita_credenciales(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET", raising=False)
    dashboard, propia = _rutas(tmp_path)
    escribir_config(Path(dashboard))

    assert (
        main(["--db-dashboard", dashboard, "--db", propia, "correr", "--simulado", "--una-vez"])
        == 0
    )


def test_estado_sin_base_lo_dice_y_falla(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    _, propia = _rutas(tmp_path)

    codigo = main(["--db", propia, "estado"])

    assert codigo == 1
    assert "Todavía no hay base" in capsys.readouterr().out


def test_estado_muestra_el_latido_y_las_posiciones(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    _, propia = _rutas(tmp_path)
    with AlmacenEstado(propia) as almacen:
        almacen.latir(detalle="Operando", posiciones_abiertas=1, version="tradinglab 0.1.0")
        almacen.registrar_apertura(
            Apertura(instrumento="AAPL", lado=COMPRA, cantidad=3, precio_entrada=100.0)
        )

    assert main(["--db", propia, "estado"]) == 0

    salida = capsys.readouterr().out
    assert "Operando" in salida
    assert "AAPL" in salida


def test_operaciones_lista_lo_registrado(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    _, propia = _rutas(tmp_path)
    with AlmacenEstado(propia) as almacen:
        abierta = almacen.registrar_apertura(
            Apertura(instrumento="AAPL", lado=COMPRA, cantidad=3, precio_entrada=100.0)
        )
        almacen.registrar_cierre(abierta, precio_salida=110.0)
        almacen.registrar_apertura(
            Apertura(instrumento="MSFT", lado=COMPRA, cantidad=1, precio_entrada=200.0)
        )

    assert main(["--db", propia, "operaciones"]) == 0

    salida = capsys.readouterr().out
    assert "AAPL" in salida and "MSFT" in salida
    # La que sigue abierta no tiene precio de salida ni resultado.
    assert "—" in salida


def test_operaciones_sin_nada_no_es_un_error(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    _, propia = _rutas(tmp_path)
    with AlmacenEstado(propia):
        pass

    assert main(["--db", propia, "operaciones"]) == 0
    assert "Sin operaciones" in capsys.readouterr().out


def test_doctor_señala_lo_que_falta(
    tmp_path: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`doctor` es la única forma de validar el camino de Alpaca en la VM.

    Sin credenciales ni Lumibot instalado tiene que fallar, y decir exactamente
    qué falta.
    """
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET", raising=False)
    dashboard, propia = _rutas(tmp_path)
    escribir_config(Path(dashboard))

    codigo = main(["--db-dashboard", dashboard, "--db", propia, "doctor"])

    salida = capsys.readouterr().out
    assert "configuración v1" in salida
    assert "cruce_medias" in salida  # las estrategias disponibles
    assert codigo == 1  # falta Lumibot, credenciales o ambos


def test_doctor_avisa_de_una_configuracion_a_medias(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    dashboard, propia = _rutas(tmp_path)
    escribir_config(Path(dashboard), datos={**CONFIG_BASE, "instrumentos": []})

    main(["--db-dashboard", dashboard, "--db", propia, "doctor"])

    assert "encendido sin tickers" in capsys.readouterr().out


def test_las_rutas_salen_del_entorno(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """En systemd las rutas van en `Environment=`, no en la línea de comandos."""
    dashboard, propia = _rutas(tmp_path)
    escribir_config(Path(dashboard), habilitado=False)
    monkeypatch.setenv("TRADINGLAB_DASHBOARD_DB", dashboard)
    monkeypatch.setenv("TRADINGLAB_DB", propia)

    assert main(["correr", "--simulado", "--una-vez"]) == 0
    assert Path(propia).exists()
