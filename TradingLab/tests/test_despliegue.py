from __future__ import annotations

import importlib.util
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "comprobar_despliegue",
    Path(__file__).resolve().parents[1] / "scripts" / "comprobar_despliegue.py",
)
assert SPEC is not None and SPEC.loader is not None
modulo = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(modulo)


@pytest.fixture
def estado(tmp_path):
    ruta = tmp_path / "estado con espacios.db"
    with sqlite3.connect(ruta) as db:
        db.execute("CREATE TABLE estado_motor (latido_en TEXT, detalle TEXT)")
    return ruta


def escribir(ruta, fecha):
    with sqlite3.connect(ruta) as db:
        db.execute("INSERT INTO estado_motor VALUES (?, ?)", (fecha, "Bloqueado; sin ordenes"))


def test_acepta_supervisor_bloqueado_sin_afirmar_que_opera(estado):
    ahora = datetime.now(timezone.utc)
    escribir(estado, (ahora - timedelta(seconds=1)).isoformat())
    assert modulo.comprobar(estado, ahora.timestamp() - 10, ahora.timestamp()).startswith(
        "Bloqueado"
    )


@pytest.mark.parametrize("edad", [121, -10])
def test_rechaza_latido_viejo_o_futuro(estado, edad):
    ahora = datetime.now(timezone.utc)
    escribir(estado, (ahora - timedelta(seconds=edad)).isoformat())
    with pytest.raises(ValueError):
        modulo.comprobar(estado, ahora.timestamp() - 300, ahora.timestamp())


def test_rechaza_latido_del_proceso_anterior(estado):
    ahora = datetime.now(timezone.utc)
    escribir(estado, (ahora - timedelta(seconds=30)).isoformat())
    with pytest.raises(ValueError):
        modulo.comprobar(estado, ahora.timestamp() - 10, ahora.timestamp())


def test_rechaza_fecha_sin_zona_y_tabla_vacia(estado):
    ahora = datetime.now(timezone.utc)
    with pytest.raises(ValueError):
        modulo.comprobar(estado, 0, ahora.timestamp())
    escribir(estado, ahora.replace(tzinfo=None).isoformat())
    with pytest.raises(ValueError):
        modulo.comprobar(estado, 0, ahora.timestamp())


def test_no_crea_base_si_no_existe(tmp_path):
    ruta = tmp_path / "ausente.db"
    with pytest.raises(sqlite3.OperationalError):
        modulo.comprobar(ruta, 0, 0)
    assert not ruta.exists()
