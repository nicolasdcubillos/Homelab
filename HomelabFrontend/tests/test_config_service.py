"""Tests de la orquestación entre la base y los archivos generados."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from homelab_dashboard import config_service, watchers
from homelab_dashboard.models import (
    CHANNEL_EMAIL,
    CHANNEL_WHATSAPP,
    AppChannelPref,
    NotificationChannel,
    PortfolioHolding,
    StockWatch,
    User,
)
from homelab_dashboard.security import hash_password


def _usuario(db, email: str = "ana@example.com") -> User:
    usuario = User(
        email=email,
        password_hash=hash_password("Contrasena123"),
        role="user",
        status="active",
    )
    db.add(usuario)
    db.flush()
    return usuario


def _con_watch(db, usuario, destino="+573001112233") -> None:
    db.add(
        StockWatch(
            user_id=usuario.id,
            name="Zapatillas",
            match_terms=["air max"],
            countries=["CO"],
            notify_channels=[CHANNEL_WHATSAPP],
        )
    )
    db.add(
        NotificationChannel(
            user_id=usuario.id, channel=CHANNEL_WHATSAPP, destination=destino
        )
    )
    db.add(
        AppChannelPref(
            user_id=usuario.id,
            app_name=watchers.APP_STOCKWATCHER,
            channel=CHANNEL_WHATSAPP,
            enabled=True,
        )
    )
    db.flush()


def test_preparar_escribe_la_config_del_usuario(db, settings):
    usuario = _usuario(db)
    _con_watch(db, usuario)

    plan = config_service.preparar(
        db, settings, usuario, watchers.APP_STOCKWATCHER
    )

    contenido = Path(plan.config_path).read_text(encoding="utf-8")
    assert "Zapatillas" in contenido
    assert yaml.safe_load(contenido)["watches"][0]["name"] == "Zapatillas"


def test_la_config_vive_dentro_del_workspace_del_usuario(db, settings):
    usuario = _usuario(db)
    _con_watch(db, usuario)

    plan = config_service.preparar(db, settings, usuario, watchers.APP_STOCKWATCHER)

    esperado = settings.users_dir.resolve() / usuario.id
    assert Path(plan.config_path).is_relative_to(esperado)
    assert Path(plan.state_path).is_relative_to(esperado)


def test_dos_usuarios_generan_archivos_distintos(db, settings):
    ana = _usuario(db, "ana@example.com")
    bruno = _usuario(db, "bruno@example.com")
    _con_watch(db, ana, destino="+573001112233")
    _con_watch(db, bruno, destino="+573009998877")

    plan_ana = config_service.preparar(db, settings, ana, watchers.APP_STOCKWATCHER)
    plan_bruno = config_service.preparar(db, settings, bruno, watchers.APP_STOCKWATCHER)

    assert plan_ana.config_path != plan_bruno.config_path
    assert plan_ana.state_path != plan_bruno.state_path, (
        "compartir estado haría que el segundo usuario nunca reciba su alerta"
    )
    assert plan_ana.entorno["WHATSAPP_TO"] == "+573001112233"
    assert plan_bruno.entorno["WHATSAPP_TO"] == "+573009998877"


def test_el_entorno_generado_no_hereda_destinos_del_proceso(db, settings, monkeypatch):
    """Aunque el proceso tenga `WHATSAPP_TO`, el del usuario manda.

    Es la defensa contra que el `.env` del repo administrado mande la alerta al
    número del dueño de la máquina.
    """
    monkeypatch.setenv("WHATSAPP_TO", "+570000000000")
    monkeypatch.setenv("EMAIL_TO", "dueño@example.com")

    usuario = _usuario(db)
    _con_watch(db, usuario)
    plan = config_service.preparar(db, settings, usuario, watchers.APP_STOCKWATCHER)

    assert plan.entorno["WHATSAPP_TO"] == "+573001112233"
    assert plan.entorno["EMAIL_TO"] == ""


def test_un_canal_sin_destino_no_se_activa(db, settings):
    usuario = _usuario(db)
    _con_watch(db, usuario)
    db.add(
        AppChannelPref(
            user_id=usuario.id,
            app_name=watchers.APP_STOCKWATCHER,
            channel=CHANNEL_EMAIL,
            enabled=True,
        )
    )
    db.flush()

    plan = config_service.preparar(db, settings, usuario, watchers.APP_STOCKWATCHER)
    assert plan.entorno["EMAIL_TO"] == ""


def test_readiness_bloquea_a_un_usuario_vacio(db, settings):
    usuario = _usuario(db)
    estado = config_service.evaluar_readiness(
        db, usuario, watchers.APP_STOCKWATCHER
    )
    assert estado.listo is False
    assert {m.code for m in estado.motivos} == {"sin_destino", "sin_watches"}


def test_readiness_deja_pasar_a_un_usuario_completo(db, settings):
    usuario = _usuario(db)
    _con_watch(db, usuario)
    estado = config_service.evaluar_readiness(db, usuario, watchers.APP_STOCKWATCHER)
    assert estado.listo is True
    assert estado.motivo == ""


def test_readiness_exige_holdings_en_portfoliowatcher(db, settings):
    usuario = _usuario(db)
    estado = config_service.evaluar_readiness(
        db, usuario, watchers.APP_PORTFOLIOWATCHER
    )
    assert "sin_holdings" in {m.code for m in estado.motivos}

    db.add(
        PortfolioHolding(
            user_id=usuario.id, ticker="AAPL", quantity=1.0, avg_cost=100.0
        )
    )
    db.add(
        NotificationChannel(
            user_id=usuario.id, channel=CHANNEL_WHATSAPP, destination="+573001112233"
        )
    )
    db.add(
        AppChannelPref(
            user_id=usuario.id,
            app_name=watchers.APP_PORTFOLIOWATCHER,
            channel=CHANNEL_WHATSAPP,
            enabled=True,
        )
    )
    db.flush()
    estado = config_service.evaluar_readiness(
        db, usuario, watchers.APP_PORTFOLIOWATCHER
    )
    assert estado.listo is True


def test_una_app_desconocida_no_es_ejecutable(db, settings):
    usuario = _usuario(db)
    estado = config_service.evaluar_readiness(db, usuario, "inventada")
    assert estado.listo is False
    assert estado.motivos[0].code == "app_desconocida"


def test_previsualizar_no_escribe_nada(db, settings):
    usuario = _usuario(db)
    _con_watch(db, usuario)
    config_service.previsualizar(db, settings, usuario, watchers.APP_STOCKWATCHER)
    assert list(settings.users_dir.rglob("*.yaml")) == []


def test_preparar_es_repetible(db, settings):
    usuario = _usuario(db)
    _con_watch(db, usuario)
    uno = config_service.preparar(db, settings, usuario, watchers.APP_STOCKWATCHER)
    dos = config_service.preparar(db, settings, usuario, watchers.APP_STOCKWATCHER)
    assert uno.config_path == dos.config_path
    assert Path(uno.config_path).read_text(encoding="utf-8") == Path(
        dos.config_path
    ).read_text(encoding="utf-8")


def test_una_app_desconocida_levanta_al_preparar(db, settings):
    usuario = _usuario(db)
    with pytest.raises(ValueError):
        config_service.preparar(db, settings, usuario, "inventada")
