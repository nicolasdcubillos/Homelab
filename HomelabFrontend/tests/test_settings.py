"""Tests de la configuración de proceso (`settings.py`)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from homelab_dashboard.settings import load_settings


def test_valores_por_defecto(monkeypatch):
    for key in list(os.environ):
        if key.startswith("DASHBOARD_"):
            monkeypatch.delenv(key, raising=False)

    settings = load_settings()

    assert settings.apps_file == Path("apps.yaml")
    assert settings.data_dir == Path("data")
    assert settings.db_path == Path("data/dashboard.db")
    assert settings.logs_dir == Path("logs")
    assert settings.secure_cookies is True
    assert settings.scheduler_enabled is True
    assert settings.max_concurrent_jobs == 4
    assert settings.default_timezone == "America/Bogota"


def test_db_file_explicito_manda_sobre_data_dir(monkeypatch):
    """El systemd desplegado ya define DASHBOARD_DB_FILE; debe seguir mandando."""
    monkeypatch.setenv("DASHBOARD_DATA_DIR", "/srv/datos")
    monkeypatch.setenv("DASHBOARD_DB_FILE", "/var/lib/otro/dashboard.db")

    settings = load_settings()

    assert settings.data_dir == Path("/srv/datos")
    assert settings.db_path == Path("/var/lib/otro/dashboard.db")
    assert settings.users_dir == Path("/srv/datos/users")


def test_db_path_derivado_de_data_dir(monkeypatch):
    monkeypatch.delenv("DASHBOARD_DB_FILE", raising=False)
    monkeypatch.setenv("DASHBOARD_DATA_DIR", "/srv/datos")

    assert load_settings().db_path == Path("/srv/datos/dashboard.db")


@pytest.mark.parametrize("valor", ["true", "1", "yes", "on"])
def test_booleanos_verdaderos(monkeypatch, valor):
    monkeypatch.setenv("DASHBOARD_SECURE_COOKIES", valor)
    assert load_settings().secure_cookies is True


@pytest.mark.parametrize("valor", ["false", "0", "no", "off"])
def test_booleanos_falsos(monkeypatch, valor):
    monkeypatch.setenv("DASHBOARD_SECURE_COOKIES", valor)
    assert load_settings().secure_cookies is False


def test_booleano_invalido_falla_ruidosamente(monkeypatch):
    """Un typo en el systemd debe romper al arrancar, no degradar en silencio."""
    monkeypatch.setenv("DASHBOARD_SCHEDULER_ENABLED", "quizas")
    with pytest.raises(ValueError, match="booleano"):
        load_settings()


def test_entero_invalido_falla_ruidosamente(monkeypatch):
    monkeypatch.setenv("DASHBOARD_MAX_CONCURRENT_JOBS", "muchos")
    with pytest.raises(ValueError, match="entero"):
        load_settings()


def test_entero_fuera_de_rango_falla(monkeypatch):
    monkeypatch.setenv("DASHBOARD_MAX_CONCURRENT_JOBS", "0")
    with pytest.raises(ValueError, match=">= 1"):
        load_settings()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("ENABLED", "quizas"),
        ("DELIVERIES_ENABLED", "habilitado"),
        ("WHATSAPP_TEMPLATE_APPROVED", "aprobado"),
        ("TIMEOUT", "mucho"),
        ("TIMEOUT", "nan"),
        ("TIMEOUT", "inf"),
        ("TIMEOUT", "0"),
        ("TIMEOUT", "121"),
        ("DISK_MIN_FREE_MB", "0.5"),
        ("DISK_MIN_FREE_MB", "-1"),
        ("DISK_MIN_FREE_MB", "1000001"),
    ],
)
def test_regimen_rechaza_configuracion_invalida(monkeypatch, name, value):
    key = "DASHBOARD_REGIME_" + name
    monkeypatch.setenv(key, value)
    with pytest.raises(ValueError, match=key):
        load_settings()


def test_regimen_reutiliza_booleanos_y_normalizacion_del_dashboard(monkeypatch):
    monkeypatch.setenv("DASHBOARD_REGIME_ENABLED", "on")
    monkeypatch.setenv("DASHBOARD_REGIME_DELIVERIES_ENABLED", "off")
    monkeypatch.setenv("DASHBOARD_REGIME_DISK_MIN_FREE_MB", "")
    monkeypatch.setenv("DASHBOARD_REGIME_TIMEOUT", "")
    monkeypatch.setenv("DASHBOARD_REGIME_FRED_KEY", "   ")
    regime = load_settings().regime
    assert regime.enabled is True
    assert regime.deliveries_enabled is False
    assert regime.disk_min_free_mb == 1024
    assert regime.timeout == 20
    assert regime.fred_key == ""


def test_ensure_directories_restringe_permisos_de_usuarios(tmp_path):
    settings = load_settings(
        data_dir=tmp_path / "datos",
        db_path=tmp_path / "datos" / "d.db",
        logs_dir=tmp_path / "logs",
    )

    settings.ensure_directories()

    assert settings.data_dir.is_dir()
    assert settings.logs_dir.is_dir()
    assert settings.users_dir.is_dir()
    # Los workspaces contienen la config y el estado de cada usuario: nadie
    # más en la máquina debería poder leerlos.
    assert settings.users_dir.stat().st_mode & 0o777 == 0o700
