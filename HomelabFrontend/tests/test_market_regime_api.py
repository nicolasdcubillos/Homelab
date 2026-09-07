"""Permisos y contratos; no se usan credenciales ni se abren conexiones externas."""

import datetime as dt
from dataclasses import replace

from sqlalchemy import select

from homelab_dashboard.market_regime.models import RegimeRun

PREFIX = "/api/v1/market-regime"


def active_user(admin, nuevo_usuario, email):
    client = nuevo_usuario(email)
    identifier = client.get("/api/v1/auth/me").json()["user"]["id"]
    response = admin.patch(f"/api/v1/admin/users/{identifier}", json={"status": "active"})
    assert response.status_code == 200
    return client, identifier


def test_permiso_independiente_y_solo_lectura(admin, nuevo_usuario):
    viewer, identifier = active_user(admin, nuevo_usuario, "viewer@ejemplo.com")
    assert viewer.get(f"{PREFIX}/overview").status_code == 404
    assert admin.put(f"{PREFIX}/access/{identifier}", json={"level": "viewer"}).status_code == 200
    session = viewer.get("/api/v1/auth/me").json()["user"]
    assert session["regime_level"] == "viewer"
    assert session["trading_level"] is None
    assert viewer.get(f"{PREFIX}/overview").status_code == 200
    config = viewer.get(f"{PREFIX}/config").json()
    assert (
        viewer.patch(
            f"{PREFIX}/config",
            json={
                "version": config["version"],
                "enabled": True,
                "config": config["config"],
            },
        ).status_code
        == 403
    )
    assert viewer.get(f"{PREFIX}/access").status_code == 404
    assert admin.delete(f"{PREFIX}/access/{identifier}").status_code == 204
    assert viewer.get(f"{PREFIX}/overview").status_code == 404


def test_sin_datos_no_inventa_scores_o_historia(admin):
    overview = admin.get(f"{PREFIX}/overview")
    assert overview.status_code == 200, overview.text
    data = overview.json()
    assert data["snapshot"] is None
    assert data["first_snapshot_at"] is None
    assert data["deliveries_enabled"] is False
    assert any(item["series_id"] == "MOVE" and not item["available"] for item in data["coverage"])
    history = admin.get(f"{PREFIX}/history?range=12m").json()
    assert history["items"] == []
    assert history["unavailable_before_first"] is True
    assert admin.get(f"{PREFIX}/history?range=2m").status_code == 422


def test_config_version_csrf_y_no_secretos(admin):
    config = admin.get(f"{PREFIX}/config").json()
    update = {"version": config["version"], "enabled": True, "config": config["config"]}
    assert admin.raw.patch(f"{PREFIX}/config", json=update).status_code == 403
    changed = admin.patch(f"{PREFIX}/config", json=update)
    assert changed.status_code == 200, changed.text
    assert changed.json()["version"] == config["version"] + 1
    assert admin.patch(f"{PREFIX}/config", json=update).status_code == 409
    sources = admin.get(f"{PREFIX}/sources").json()
    assert "connection_string" not in str(sources)
    assert "api_key" not in str(sources)


def test_preferencias_solo_propias_y_sin_consentimiento(admin, nuevo_usuario):
    first, first_id = active_user(admin, nuevo_usuario, "uno@ejemplo.com")
    second, second_id = active_user(admin, nuevo_usuario, "dos@ejemplo.com")
    for identifier in (first_id, second_id):
        admin.put(f"{PREFIX}/access/{identifier}", json={"level": "viewer"})
    assert first.get(f"{PREFIX}/me/subscription").json()["enabled"] is False
    assert (
        first.put(
            f"{PREFIX}/me/subscription",
            json={
                "enabled": True,
                "email": True,
                "accept_consent": False,
            },
        ).status_code
        == 422
    )
    assert (
        first.put(
            f"{PREFIX}/me/subscription",
            json={
                "enabled": False,
                "email": False,
                "whatsapp": False,
                "user_id": second_id,
            },
        ).status_code
        == 422
    )
    assert second.get(f"{PREFIX}/me/subscription").json()["enabled"] is False
    assert first.get(f"{PREFIX}/me/deliveries").json()["items"] == []


def test_ejecucion_manual_visible_y_sin_red_en_peticion(admin, app, db):
    assert admin.post(f"{PREFIX}/runs", json={"kind": "ingest"}).status_code == 409
    # Simula solamente disponibilidad del scheduler; no arranca trabajadores.
    app.state.scheduler = object()
    assert admin.post(f"{PREFIX}/runs", json={"kind": "ingest"}).status_code == 409
    app.state.settings = replace(
        app.state.settings,
        regime=replace(app.state.settings.regime, enabled=True),
    )
    config = admin.get(f"{PREFIX}/config").json()
    admin.patch(
        f"{PREFIX}/config",
        json={
            "version": config["version"],
            "enabled": True,
            "config": config["config"],
        },
    )
    created = admin.post(f"{PREFIX}/runs", json={"kind": "ingest"})
    assert created.status_code == 202, created.text
    identifier = created.json()["id"]
    assert created.json()["status"] == "PENDIENTE"
    assert admin.post(f"{PREFIX}/runs", json={"kind": "ingest"}).status_code == 409
    assert admin.get(f"{PREFIX}/runs/{identifier}").json()["status"] == "PENDIENTE"
    assert db.scalar(select(RegimeRun).where(RegimeRun.id == identifier)).started_at is None
    app.state.scheduler = None


def test_cuenta_suspendida_pierde_acceso(admin, nuevo_usuario):
    client, identifier = active_user(admin, nuevo_usuario, "suspendido@ejemplo.com")
    admin.put(f"{PREFIX}/access/{identifier}", json={"level": "operator"})
    admin.patch(f"/api/v1/admin/users/{identifier}", json={"status": "suspended"})
    assert client.get(f"{PREFIX}/overview").status_code in (401, 403)


def test_contrato_fechas_con_zona(admin, monkeypatch):
    from homelab_dashboard.api import routes_market_regime

    monkeypatch.setattr(
        routes_market_regime,
        "utcnow",
        lambda: dt.datetime(2026, 3, 31, 12, tzinfo=dt.timezone.utc),
    )
    history = admin.get(f"{PREFIX}/history?range=1m").json()
    assert history["requested_from"].startswith("2026-02-28T12:00:00")
