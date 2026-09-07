"""Tests de las migraciones de Alembic.

El caso que importa de verdad es el segundo: una base creada por la versión
single-user del dashboard debe migrarse sin perder el historial de ejecuciones
y con las fechas convertidas al formato que entiende SQLAlchemy.
"""

from __future__ import annotations

import datetime as dt
import sqlite3

import pytest
from alembic import command
from sqlalchemy import inspect, select

from homelab_dashboard.db import create_db_engine, make_session_factory
from homelab_dashboard.jobs import _SCHEMA as ESQUEMA_LEGADO
from homelab_dashboard.migrate import (
    alembic_config,
    current_revision,
    head_revision,
    is_up_to_date,
    upgrade_to_head,
)
from homelab_dashboard.models import JobRun
from homelab_dashboard.settings import load_settings

TABLAS_ESPERADAS = {
    "app_channel_prefs",
    "audit_log",
    "auth_sessions",
    "job_runs",
    "login_attempts",
    "notification_channels",
    "portfolio_closed_positions",
    "portfolio_holdings",
    "portfolio_profiles",
    "schedules",
    "stock_watches",
    "trading_access",
    "trading_bot_config",
    "users",
}


def _settings_para(tmp_path):
    return load_settings(
        data_dir=tmp_path,
        db_path=tmp_path / "dashboard.db",
        logs_dir=tmp_path / "logs",
    )


def test_migracion_desde_cero_crea_todo_el_esquema(tmp_path):
    settings = _settings_para(tmp_path)

    upgrade_to_head(settings)

    engine = create_db_engine(settings.db_path)
    tablas = set(inspect(engine).get_table_names())
    engine.dispose()

    assert TABLAS_ESPERADAS <= tablas
    assert current_revision(settings) == head_revision()
    assert is_up_to_date(settings)


def test_migracion_es_idempotente(tmp_path):
    settings = _settings_para(tmp_path)
    upgrade_to_head(settings)
    upgrade_to_head(settings)
    assert is_up_to_date(settings)


@pytest.mark.parametrize("revision", ["ddf944225582", "de02a901e6ae"])
def test_unifica_ambas_ramas_sin_perder_ejecuciones(tmp_path, revision):
    settings = _settings_para(tmp_path)
    _crear_base_legada(settings.db_path)
    engine = create_db_engine(settings.db_path)
    try:
        config = alembic_config()
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, revision)
        if revision == "ddf944225582":
            with sqlite3.connect(settings.db_path) as db:
                db.execute("UPDATE job_runs SET result_json = ?", ('{"hallazgos": []}',))
    finally:
        engine.dispose()

    upgrade_to_head(settings)
    upgrade_to_head(settings)
    assert current_revision(settings) == head_revision()
    engine = create_db_engine(settings.db_path)
    try:
        assert TABLAS_ESPERADAS <= set(inspect(engine).get_table_names())
        with make_session_factory(engine)() as session:
            runs = session.scalars(select(JobRun).order_by(JobRun.id)).all()
            assert len(runs) == 2
            assert runs[0].status == "success"
            if revision == "ddf944225582":
                assert runs[0].result == {"hallazgos": []}
            else:
                assert runs[0].result is None
    finally:
        engine.dispose()


def _crear_base_legada(db_path) -> None:
    """Reproduce la base tal como la dejaba la versión single-user."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(ESQUEMA_LEGADO)
    inicio = dt.datetime(2026, 9, 2, 23, 0, 0, tzinfo=dt.timezone.utc)
    fin = inicio + dt.timedelta(seconds=42)
    conn.execute(
        "INSERT INTO job_runs (app_name, command_label, args_json, log_path, started_at, "
        "finished_at, duration_seconds, status, return_code) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            "stockwatcher",
            "Run (sin discovery)",
            '["run"]',
            "logs/stockwatcher/x.log",
            inicio.isoformat(),
            fin.isoformat(),
            42.0,
            "success",
            0,
        ),
    )
    conn.execute(
        "INSERT INTO job_runs (app_name, command_label, args_json, log_path, started_at, status) "
        "VALUES (?,?,?,?,?,?)",
        (
            "portfoliowatcher",
            "Diario (real)",
            '["daily"]',
            "logs/portfoliowatcher/y.log",
            inicio.isoformat(),
            "running",
        ),
    )
    conn.commit()
    conn.close()


def test_migracion_preserva_el_historial_single_user(tmp_path):
    settings = _settings_para(tmp_path)
    _crear_base_legada(settings.db_path)

    upgrade_to_head(settings)

    factory = make_session_factory(create_db_engine(settings.db_path))
    with factory() as s:
        runs = s.scalars(select(JobRun).order_by(JobRun.id)).all()

    assert len(runs) == 2
    primero, segundo = runs

    # El historial no se pierde ni se reescribe.
    assert primero.app_name == "stockwatcher"
    assert primero.command_label == "Run (sin discovery)"
    assert primero.status == "success"
    assert primero.return_code == 0
    assert primero.duration_seconds == 42.0
    assert segundo.status == "running"

    # Las columnas nuevas reciben valores coherentes.
    assert primero.user_id is None, "las ejecuciones heredadas no son de nadie"
    assert primero.trigger == "manual"
    assert primero.command_key == ""
    assert primero.schedule_id is None


def test_migracion_convierte_las_fechas_iso_a_datetimes_utc(tmp_path):
    """Las fechas legadas eran texto ISO con 'T' y sufijo '+00:00'."""
    settings = _settings_para(tmp_path)
    _crear_base_legada(settings.db_path)

    upgrade_to_head(settings)

    factory = make_session_factory(create_db_engine(settings.db_path))
    with factory() as s:
        run = s.scalars(select(JobRun).order_by(JobRun.id)).first()

    assert run.started_at == dt.datetime(2026, 9, 2, 23, 0, 0, tzinfo=dt.timezone.utc)
    assert run.finished_at == dt.datetime(2026, 9, 2, 23, 0, 42, tzinfo=dt.timezone.utc)
    assert run.started_at.tzinfo is not None


def test_migracion_legada_no_deja_tabla_temporal(tmp_path):
    settings = _settings_para(tmp_path)
    _crear_base_legada(settings.db_path)

    upgrade_to_head(settings)

    engine = create_db_engine(settings.db_path)
    tablas = set(inspect(engine).get_table_names())
    engine.dispose()

    assert "job_runs_legacy" not in tablas
    assert TABLAS_ESPERADAS <= tablas
