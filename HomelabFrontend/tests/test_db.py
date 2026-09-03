"""Tests del motor SQLAlchemy y de la disciplina de fechas en UTC."""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, StatementError

from homelab_dashboard.db import Base, create_db_engine, make_session_factory, utcnow
from homelab_dashboard.models import JobRun, User


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_db_engine(tmp_path / "d.db")
    Base.metadata.create_all(engine)
    return make_session_factory(engine)


def test_utcnow_siempre_trae_zona_horaria():
    assert utcnow().tzinfo is not None


def test_guardar_datetime_sin_zona_es_un_error(session_factory):
    """Un datetime ingenuo es un bug silencioso: debe fallar al escribir."""
    with session_factory() as s:
        s.add(
            JobRun(
                app_name="x",
                command_label="y",
                started_at=dt.datetime(2026, 1, 1, 12, 0, 0),  # sin tzinfo
                status="running",
            )
        )
        # SQLAlchemy envuelve el ValueError del TypeDecorator en StatementError.
        with pytest.raises(StatementError, match="sin zona horaria"):
            s.commit()


def test_datetime_se_relee_en_utc_aunque_se_guarde_en_otra_zona(session_factory):
    bogota = dt.timezone(dt.timedelta(hours=-5))
    momento = dt.datetime(2026, 9, 2, 18, 30, 0, tzinfo=bogota)

    with session_factory() as s:
        s.add(JobRun(app_name="x", command_label="y", started_at=momento, status="running"))
        s.commit()

    with session_factory() as s:
        leido = s.scalars(select(JobRun)).one()

    assert leido.started_at.tzinfo is not None
    assert leido.started_at == momento
    assert leido.started_at.utcoffset() == dt.timedelta(0)


def test_foreign_keys_activas_impiden_referencias_huerfanas(session_factory):
    """SQLite ignora las claves foráneas salvo que se activen explícitamente;
    sin el PRAGMA, el borrado en cascada de usuarios no funcionaría."""
    with session_factory() as s:
        s.add(JobRun(app_name="x", command_label="y", status="running", user_id="noexiste"))
        with pytest.raises(IntegrityError):
            s.commit()


def test_borrar_usuario_arrastra_sus_datos(session_factory):
    with session_factory() as s:
        u = User(email="a@b.c", password_hash="x", status="active")
        s.add(u)
        s.flush()
        s.add(JobRun(app_name="x", command_label="y", status="success", user_id=u.id))
        s.commit()
        user_id = u.id

    with session_factory() as s:
        s.delete(s.get(User, user_id))
        s.commit()

    with session_factory() as s:
        assert s.scalars(select(JobRun)).all() == []
