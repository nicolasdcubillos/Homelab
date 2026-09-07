"""La lectura de la configuración compartida.

Lo que se prueba aquí no es «que lee un JSON», sino las decisiones que hacen que
el bot siga siendo seguro cuando la fila que le llega no es la que esperaba.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import CONFIG_BASE, escribir_config
from tradinglab.config import (
    MAX_INSTRUMENTOS,
    ConfigCompartida,
    ErrorDeConfig,
    LectorDashboard,
)


def test_lee_la_configuracion_publicada(lector: LectorDashboard) -> None:
    config = lector.leer()

    assert config.habilitado is True
    assert config.version == 1
    assert config.instrumentos == ("AAPL", "MSFT")
    assert config.estrategia == "cruce_medias"
    assert config.capital_simulado == 10_000.0
    assert config.actualizada_por == "nico@example.com"


def test_sin_base_no_se_inventa_nada(tmp_path: Path) -> None:
    with pytest.raises(ErrorDeConfig, match="No existe la base"):
        LectorDashboard(tmp_path / "no-existe.db").leer()


def test_sin_fila_se_queda_en_pausa(db_dashboard: Path) -> None:
    """El dashboard crea la fila al abrir la pantalla, no en la migración.

    Antes de eso el proceso puede llevar días instalado y correcto. Fallar sería
    reportar como avería lo que es simplemente «nadie ha entrado todavía».
    """
    escribir_config(db_dashboard, bot="freqtrade")

    config = LectorDashboard(db_dashboard).leer()

    assert config == ConfigCompartida.ausente()
    assert config.habilitado is False
    assert config.version == 0


def test_un_modo_distinto_de_paper_es_un_error(db_dashboard: Path) -> None:
    """La invariante de «solo simulación», comprobada desde este lado.

    El dashboard ya lo garantiza con un CHECK. Que aquí se vuelva a comprobar no
    es redundancia ociosa: son dos procesos, y si la base dijera otra cosa este
    se niega a operar en vez de confiar.
    """
    escribir_config(db_dashboard, modo="real", con_checks=False)

    with pytest.raises(ErrorDeConfig, match="no opera fuera de simulación"):
        LectorDashboard(db_dashboard).leer()


def test_json_invalido_es_un_error_y_no_una_pausa(db_dashboard: Path) -> None:
    escribir_config(db_dashboard, crudo="{esto no es json", con_checks=False)

    with pytest.raises(ErrorDeConfig, match="no es JSON válido"):
        LectorDashboard(db_dashboard).leer()


def test_los_tickers_se_normalizan(db_dashboard: Path) -> None:
    escribir_config(
        db_dashboard,
        datos={**CONFIG_BASE, "instrumentos": [" aapl ", "AAPL", "msft", ""]},
    )

    config = LectorDashboard(db_dashboard).leer()

    # Mayúsculas, sin espacios, sin duplicados y sin vacíos: el corredor recibe
    # exactamente lo que puede pedir.
    assert config.instrumentos == ("AAPL", "MSFT")


def test_se_rechaza_el_exceso_de_tickers(db_dashboard: Path) -> None:
    demasiados = [f"TCK{indice}" for indice in range(MAX_INSTRUMENTOS + 10)]
    escribir_config(db_dashboard, datos={**CONFIG_BASE, "instrumentos": demasiados})

    with pytest.raises(ErrorDeConfig, match="no se recorta"):
        LectorDashboard(db_dashboard).leer()


def test_un_numero_corrupto_no_se_sustituye(db_dashboard: Path) -> None:
    escribir_config(db_dashboard, datos={**CONFIG_BASE, "stop_loss_pct": "muchísimo"})

    with pytest.raises(ErrorDeConfig, match="stop_loss_pct"):
        LectorDashboard(db_dashboard).leer()


def test_la_lectura_no_cachea_la_conexion(db_dashboard: Path) -> None:
    """Apagar el bot desde el celular tiene que surtir efecto en la vuelta siguiente.

    SQLite entrega una instantánea al abrir la conexión; si el lector la
    guardara, seguiría viendo `enabled = 1` después de que alguien pulse el
    interruptor. Este es exactamente el fallo que se está previniendo.
    """
    lector = LectorDashboard(db_dashboard)
    escribir_config(db_dashboard, habilitado=True, version=1)
    assert lector.leer().habilitado is True

    escribir_config(db_dashboard, habilitado=False, version=2)
    segunda = lector.leer()

    assert segunda.habilitado is False
    assert segunda.version == 2


def test_encendido_sin_tickers_no_es_operable(db_dashboard: Path) -> None:
    escribir_config(db_dashboard, datos={**CONFIG_BASE, "instrumentos": []})

    config = LectorDashboard(db_dashboard).leer()

    assert config.habilitado is True
    assert config.operable is False


@pytest.mark.parametrize(
    ("timeframe", "segundos"),
    [("5m", 300), ("1h", 3_600), ("1d", 86_400)],
)
def test_cadencia_por_marco_temporal(db_dashboard: Path, timeframe: str, segundos: int) -> None:
    escribir_config(db_dashboard, datos={**CONFIG_BASE, "timeframe": timeframe})

    config = LectorDashboard(db_dashboard).leer()

    assert config.segundos_entre_evaluaciones == segundos


def test_config_json_como_objeto_nativo(db_dashboard: Path) -> None:
    """SQLAlchemy declara la columna como JSON; sqlite3 la devuelve como texto.

    Se comprueba que el camino de texto —el real— funciona con un JSON que
    contiene tipos mezclados, que es lo que produce el formulario del panel.
    """
    escribir_config(
        db_dashboard,
        crudo=json.dumps({**CONFIG_BASE, "max_posiciones_abiertas": 2, "capital_simulado": 5000}),
    )

    config = LectorDashboard(db_dashboard).leer()

    assert config.max_posiciones_abiertas == 2
    assert config.capital_simulado == 5000.0


@pytest.mark.parametrize(
    ("campo", "valor"),
    [
        ("stop_loss_pct", float("nan")),
        ("take_profit_pct", float("inf")),
        ("capital_simulado", -1),
        ("max_posiciones_abiertas", 2.7),
        ("capital_simulado", True),
        ("instrumentos", "AAPL"),
        ("instrumentos", [None]),
        ("instrumentos", ["AAPL/USDT"]),
        ("timeframe", "marciano"),
        ("estrategia", "desconocida"),
        ("dry_run", False),
    ],
)
def test_configuracion_invalida_se_rechaza(db_dashboard, campo, valor):
    escribir_config(db_dashboard, datos={**CONFIG_BASE, campo: valor})
    with pytest.raises(ErrorDeConfig):
        LectorDashboard(db_dashboard).leer()


def test_ruta_sqlite_con_caracteres_uri(tmp_path):
    ruta = tmp_path / "dashboard # demo.db"
    escribir_config(ruta)
    assert LectorDashboard(ruta).leer().version == 1
