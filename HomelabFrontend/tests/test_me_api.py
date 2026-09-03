"""Tests de la API de configuración del usuario.

El bloque más importante es el de aislamiento: dos usuarios registrados de
verdad, cada uno intentando alcanzar los datos del otro por su id real.
"""

from __future__ import annotations

import pytest
from conftest import PASSWORD_DE_PRUEBA

from homelab_dashboard.api.routes_me import LIMITE_WATCHES

WATCH = {
    "name": "Zapatillas",
    "match_terms": ["air max"],
    "countries": ["CO"],
    "notify_channels": ["whatsapp"],
}
HOLDING = {"ticker": "AAPL", "quantity": 10, "avg_cost": 150.5}


@pytest.fixture
def ana(nuevo_usuario):
    return nuevo_usuario("ana@example.com")


@pytest.fixture
def bruno(nuevo_usuario):
    return nuevo_usuario("bruno@example.com")


# ---------------------------------------------------------------------------
# Notificaciones
# ---------------------------------------------------------------------------


def test_notificaciones_empiezan_vacias(ana):
    datos = ana.get("/api/v1/me/notifications").json()
    assert datos["whatsapp"] is None
    assert datos["email"] is None


def test_guardar_y_leer_notificaciones(ana):
    r = ana.put(
        "/api/v1/me/notifications",
        json={"whatsapp": "+573001112233", "email": "ana@example.com"},
    )
    assert r.status_code == 200
    datos = ana.get("/api/v1/me/notifications").json()
    assert datos["whatsapp"] == "+573001112233"
    assert datos["email"] == "ana@example.com"


@pytest.mark.parametrize(
    "malo",
    ["3001112233", "+5730", "whatsapp", "+", "+0573001112233", "+" + "9" * 20],
)
def test_whatsapp_invalido_se_rechaza(ana, malo):
    r = ana.put("/api/v1/me/notifications", json={"whatsapp": malo})
    assert r.status_code == 422
    assert "whatsapp" in r.json()["error"]["fields"]


def test_email_invalido_se_rechaza(ana):
    r = ana.put("/api/v1/me/notifications", json={"email": "no-es-un-correo"})
    assert r.status_code == 422


def test_se_puede_borrar_un_destino(ana):
    ana.put("/api/v1/me/notifications", json={"whatsapp": "+573001112233"})
    ana.put("/api/v1/me/notifications", json={"whatsapp": None})
    assert ana.get("/api/v1/me/notifications").json()["whatsapp"] is None


def test_las_preferencias_por_app_se_persisten(ana):
    r = ana.put(
        "/api/v1/me/notifications/preferences",
        json={"app_name": "stockwatcher", "channels": ["email"]},
    )
    assert r.status_code == 200
    prefs = ana.get("/api/v1/me/notifications").json()["preferences"]
    assert prefs["stockwatcher"] == ["email"]


def test_portfoliowatcher_acepta_email(ana):
    """Hallazgo 1 resuelto (commit 8bfa9fd de PortfolioWatcher): ya hay
    notificador de correo, así que la app acepta ese canal."""
    r = ana.put(
        "/api/v1/me/notifications/preferences",
        json={"app_name": "portfoliowatcher", "channels": ["email"]},
    )
    assert r.status_code == 200
    prefs = ana.get("/api/v1/me/notifications").json()
    assert prefs["preferences"]["portfoliowatcher"] == ["email"]
    assert sorted(prefs["supported"]["portfoliowatcher"]) == ["email", "whatsapp"]


def test_portfoliowatcher_rechaza_canal_desconocido(ana):
    r = ana.put(
        "/api/v1/me/notifications/preferences",
        json={"app_name": "portfoliowatcher", "channels": ["telegram"]},
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Watches
# ---------------------------------------------------------------------------


def test_crear_y_listar_watches(ana):
    r = ana.post("/api/v1/me/stockwatcher/watches", json=WATCH)
    assert r.status_code == 201
    creada = r.json()
    assert creada["name"] == "Zapatillas"
    assert creada["enabled"] is True

    listado = ana.get("/api/v1/me/stockwatcher/watches").json()
    assert [w["id"] for w in listado["items"]] == [creada["id"]]


def test_la_lista_arranca_vacia(ana):
    assert ana.get("/api/v1/me/stockwatcher/watches").json()["items"] == []


def test_editar_un_watch(ana):
    wid = ana.post("/api/v1/me/stockwatcher/watches", json=WATCH).json()["id"]
    r = ana.put(
        f"/api/v1/me/stockwatcher/watches/{wid}",
        json={**WATCH, "name": "Otra cosa", "enabled": False},
    )
    assert r.status_code == 200
    assert r.json()["name"] == "Otra cosa"
    assert r.json()["enabled"] is False


def test_borrar_un_watch(ana):
    wid = ana.post("/api/v1/me/stockwatcher/watches", json=WATCH).json()["id"]
    assert ana.delete(f"/api/v1/me/stockwatcher/watches/{wid}").status_code == 204
    assert ana.get("/api/v1/me/stockwatcher/watches").json()["items"] == []


def test_borrar_un_watch_inexistente_da_404(ana):
    assert ana.delete("/api/v1/me/stockwatcher/watches/" + "f" * 32).status_code == 404


@pytest.mark.parametrize(
    "parche",
    [
        {"name": ""},
        {"name": "x" * 200},
        {"match_terms": []},
        {"match_terms": [""]},
        {"gender": "otro"},
        {"max_price": "-5"},
        {"max_price": "no-es-numero"},
        {"countries": ["COLOMBIA"]},
        {"notify_channels": ["telegrama"]},
    ],
)
def test_watch_invalido_se_rechaza(ana, parche):
    r = ana.post("/api/v1/me/stockwatcher/watches", json={**WATCH, **parche})
    assert r.status_code == 422


def test_no_se_aceptan_campos_desconocidos(ana):
    r = ana.post(
        "/api/v1/me/stockwatcher/watches", json={**WATCH, "user_id": "x" * 32}
    )
    assert r.status_code == 422


def test_los_paises_se_normalizan_a_mayusculas(ana):
    r = ana.post("/api/v1/me/stockwatcher/watches", json={**WATCH, "countries": ["co"]})
    assert r.json()["countries"] == ["CO"]


def test_no_se_permiten_dos_watches_con_el_mismo_nombre(ana):
    ana.post("/api/v1/me/stockwatcher/watches", json=WATCH)
    r = ana.post("/api/v1/me/stockwatcher/watches", json=WATCH)
    assert r.status_code == 409


def test_dos_usuarios_si_pueden_usar_el_mismo_nombre(ana, bruno):
    assert ana.post("/api/v1/me/stockwatcher/watches", json=WATCH).status_code == 201
    assert bruno.post("/api/v1/me/stockwatcher/watches", json=WATCH).status_code == 201


def test_hay_un_limite_de_watches(ana):
    for i in range(LIMITE_WATCHES):
        r = ana.post(
            "/api/v1/me/stockwatcher/watches", json={**WATCH, "name": f"Watch {i}"}
        )
        assert r.status_code == 201, r.text
    r = ana.post("/api/v1/me/stockwatcher/watches", json={**WATCH, "name": "Uno más"})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "limite_alcanzado"


# ---------------------------------------------------------------------------
# Portafolio
# ---------------------------------------------------------------------------


def test_el_portafolio_arranca_vacio(ana):
    datos = ana.get("/api/v1/me/portfolio").json()
    assert datos["holdings"] == []
    assert datos["closed_positions"] == []
    assert datos["profile"]["tolerance"] == "moderate"


def test_crear_holding(ana):
    r = ana.post("/api/v1/me/portfolio/holdings", json=HOLDING)
    assert r.status_code == 201
    assert r.json()["ticker"] == "AAPL"


def test_el_ticker_se_normaliza(ana):
    r = ana.post("/api/v1/me/portfolio/holdings", json={**HOLDING, "ticker": " aapl "})
    assert r.json()["ticker"] == "AAPL"


def test_no_se_repite_un_ticker(ana):
    ana.post("/api/v1/me/portfolio/holdings", json=HOLDING)
    assert ana.post("/api/v1/me/portfolio/holdings", json=HOLDING).status_code == 409


@pytest.mark.parametrize(
    "parche",
    [
        {"ticker": ""},
        {"ticker": "TICKER DEMASIADO LARGO"},
        {"ticker": "AA PL"},
        {"quantity": 0},
        {"quantity": -1},
        {"avg_cost": -1},
    ],
)
def test_holding_invalido_se_rechaza(ana, parche):
    assert (
        ana.post("/api/v1/me/portfolio/holdings", json={**HOLDING, **parche}).status_code
        == 422
    )


def test_editar_y_borrar_holding(ana):
    hid = ana.post("/api/v1/me/portfolio/holdings", json=HOLDING).json()["id"]
    r = ana.put(
        f"/api/v1/me/portfolio/holdings/{hid}", json={**HOLDING, "quantity": 20}
    )
    assert r.json()["quantity"] == 20
    assert ana.delete(f"/api/v1/me/portfolio/holdings/{hid}").status_code == 204
    assert ana.get("/api/v1/me/portfolio").json()["holdings"] == []


def test_guardar_perfil_de_riesgo(ana):
    r = ana.put(
        "/api/v1/me/portfolio/profile",
        json={
            "horizon": "long_term",
            "tolerance": "aggressive",
            "notes": "Sin bancos",
            "analysis_interval_days": 3,
        },
    )
    assert r.status_code == 200
    assert ana.get("/api/v1/me/portfolio").json()["profile"]["tolerance"] == "aggressive"


@pytest.mark.parametrize(
    "parche",
    [
        {"tolerance": "temeraria"},
        {"horizon": "algun_dia"},
        {"analysis_interval_days": 0},
        {"analysis_interval_days": 4000},
    ],
)
def test_perfil_invalido_se_rechaza(ana, parche):
    base = {"horizon": "long_term", "tolerance": "moderate", "analysis_interval_days": 7}
    assert ana.put("/api/v1/me/portfolio/profile", json={**base, **parche}).status_code == 422


def test_posiciones_cerradas(ana):
    r = ana.post("/api/v1/me/portfolio/closed-positions", json={"ticker": "TSLA"})
    assert r.status_code == 201
    cid = r.json()["id"]
    assert ana.get("/api/v1/me/portfolio").json()["closed_positions"][0]["ticker"] == "TSLA"
    assert ana.delete(f"/api/v1/me/portfolio/closed-positions/{cid}").status_code == 204


# ---------------------------------------------------------------------------
# Aislamiento entre usuarios
# ---------------------------------------------------------------------------


def test_cada_usuario_solo_ve_lo_suyo(ana, bruno):
    ana.post("/api/v1/me/stockwatcher/watches", json={**WATCH, "name": "De Ana"})
    bruno.post("/api/v1/me/stockwatcher/watches", json={**WATCH, "name": "De Bruno"})

    assert [w["name"] for w in ana.get("/api/v1/me/stockwatcher/watches").json()["items"]] == [
        "De Ana"
    ]
    assert [
        w["name"] for w in bruno.get("/api/v1/me/stockwatcher/watches").json()["items"]
    ] == ["De Bruno"]


def test_bruno_no_puede_leer_el_watch_de_ana(ana, bruno):
    wid = ana.post("/api/v1/me/stockwatcher/watches", json=WATCH).json()["id"]
    r = bruno.get(f"/api/v1/me/stockwatcher/watches/{wid}")
    assert r.status_code == 404, "un 403 filtraría que el recurso existe"


def test_bruno_no_puede_editar_el_watch_de_ana(ana, bruno):
    wid = ana.post("/api/v1/me/stockwatcher/watches", json=WATCH).json()["id"]
    assert (
        bruno.put(
            f"/api/v1/me/stockwatcher/watches/{wid}", json={**WATCH, "name": "Secuestrado"}
        ).status_code
        == 404
    )
    assert ana.get(f"/api/v1/me/stockwatcher/watches/{wid}").json()["name"] == "Zapatillas"


def test_bruno_no_puede_borrar_el_watch_de_ana(ana, bruno):
    wid = ana.post("/api/v1/me/stockwatcher/watches", json=WATCH).json()["id"]
    assert bruno.delete(f"/api/v1/me/stockwatcher/watches/{wid}").status_code == 404
    assert ana.get(f"/api/v1/me/stockwatcher/watches/{wid}").status_code == 200


def test_bruno_no_puede_tocar_los_holdings_de_ana(ana, bruno):
    hid = ana.post("/api/v1/me/portfolio/holdings", json=HOLDING).json()["id"]
    assert bruno.put(f"/api/v1/me/portfolio/holdings/{hid}", json=HOLDING).status_code == 404
    assert bruno.delete(f"/api/v1/me/portfolio/holdings/{hid}").status_code == 404


def test_bruno_no_puede_tocar_las_cerradas_de_ana(ana, bruno):
    cid = ana.post("/api/v1/me/portfolio/closed-positions", json={"ticker": "TSLA"}).json()[
        "id"
    ]
    assert bruno.delete(f"/api/v1/me/portfolio/closed-positions/{cid}").status_code == 404


def test_los_destinos_no_se_cruzan(ana, bruno):
    ana.put("/api/v1/me/notifications", json={"whatsapp": "+573001112233"})
    bruno.put("/api/v1/me/notifications", json={"whatsapp": "+573009998877"})
    assert ana.get("/api/v1/me/notifications").json()["whatsapp"] == "+573001112233"
    assert bruno.get("/api/v1/me/notifications").json()["whatsapp"] == "+573009998877"


def test_la_vista_previa_no_filtra_datos_ajenos(ana, bruno):
    ana.post("/api/v1/me/stockwatcher/watches", json={**WATCH, "name": "De Ana"})
    ana.put("/api/v1/me/notifications", json={"whatsapp": "+573001112233"})
    bruno.post("/api/v1/me/stockwatcher/watches", json={**WATCH, "name": "De Bruno"})

    yaml_de_bruno = bruno.get("/api/v1/me/apps/stockwatcher/config-preview").json()["yaml"]
    assert "De Bruno" in yaml_de_bruno
    assert "De Ana" not in yaml_de_bruno
    assert "+573001112233" not in yaml_de_bruno


def test_borrar_mis_datos_no_toca_los_del_otro(ana, bruno):
    ana.post("/api/v1/me/stockwatcher/watches", json=WATCH)
    bruno.post("/api/v1/me/stockwatcher/watches", json=WATCH)

    r = ana.request(
        "DELETE", "/api/v1/me/data", json={"password": PASSWORD_DE_PRUEBA}
    )
    assert r.status_code == 204
    assert ana.get("/api/v1/me/stockwatcher/watches").json()["items"] == []
    assert len(bruno.get("/api/v1/me/stockwatcher/watches").json()["items"]) == 1


def test_borrar_mis_datos_exige_la_password(ana):
    ana.post("/api/v1/me/stockwatcher/watches", json=WATCH)
    r = ana.request("DELETE", "/api/v1/me/data", json={"password": "otra-cosa-123"})
    assert r.status_code == 403
    assert len(ana.get("/api/v1/me/stockwatcher/watches").json()["items"]) == 1


# ---------------------------------------------------------------------------
# Vista previa y readiness
# ---------------------------------------------------------------------------


def test_la_vista_previa_refleja_lo_configurado(ana):
    ana.post("/api/v1/me/stockwatcher/watches", json=WATCH)
    datos = ana.get("/api/v1/me/apps/stockwatcher/config-preview").json()
    assert "Zapatillas" in datos["yaml"]
    assert datos["path"].endswith("watches.yaml")


def test_la_vista_previa_no_escribe_en_disco(ana, settings):
    ana.post("/api/v1/me/stockwatcher/watches", json=WATCH)
    ana.get("/api/v1/me/apps/stockwatcher/config-preview")
    generados = list(settings.users_dir.rglob("watches.yaml"))
    assert generados == []


def test_una_app_desconocida_da_404(ana):
    assert ana.get("/api/v1/me/apps/inventada/config-preview").status_code == 404


def test_readiness_explica_que_falta(ana):
    datos = ana.get("/api/v1/me/readiness").json()
    stock = datos["apps"]["stockwatcher"]
    assert stock["ready"] is False
    assert stock["reasons"], "debe decir por qué no puede correr"
    assert any("vigil" in r["message"].lower() for r in stock["reasons"])


def test_readiness_se_pone_verde_al_completar(ana):
    ana.put("/api/v1/me/notifications", json={"whatsapp": "+573001112233"})
    ana.post("/api/v1/me/stockwatcher/watches", json=WATCH)
    stock = ana.get("/api/v1/me/readiness").json()["apps"]["stockwatcher"]
    assert stock["ready"] is True
    assert stock["reasons"] == []


def test_readiness_avisa_si_no_hay_destino(ana):
    ana.post("/api/v1/me/stockwatcher/watches", json=WATCH)
    stock = ana.get("/api/v1/me/readiness").json()["apps"]["stockwatcher"]
    assert stock["ready"] is False
    assert any(r["code"] == "sin_destino" for r in stock["reasons"])


# ---------------------------------------------------------------------------
# Autenticación y estado de cuenta
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("metodo", "ruta"),
    [
        ("get", "/api/v1/me/notifications"),
        ("get", "/api/v1/me/stockwatcher/watches"),
        ("get", "/api/v1/me/portfolio"),
        ("get", "/api/v1/me/readiness"),
        ("post", "/api/v1/me/stockwatcher/watches"),
        ("get", "/api/v1/me/apps/stockwatcher/config-preview"),
    ],
)
def test_sin_sesion_todo_pide_login(client, metodo, ruta):
    r = client.request(metodo, ruta)
    assert r.status_code == 401


def test_suspender_corta_la_sesion_en_curso(client, admin, ana):
    """Suspender revoca las sesiones abiertas, así que la siguiente petición
    ya no está autenticada: sale 401 antes incluso de mirar el estado."""
    yo = ana.get("/api/v1/auth/me").json()["user"]["id"]
    assert admin.patch(f"/api/v1/admin/users/{yo}", json={"status": "suspended"}).status_code == 200
    assert ana.get("/api/v1/me/stockwatcher/watches").status_code == 401


def test_un_usuario_suspendido_no_puede_configurar(app, ana):
    """La otra mitad de la baranda: con una sesión todavía válida (suspensión
    aplicada directamente en base), la autorización devuelve 403."""
    from homelab_dashboard.models import USER_SUSPENDED, User

    yo = ana.get("/api/v1/auth/me").json()["user"]["id"]
    with app.state.session_factory() as db:
        db.get(User, yo).status = USER_SUSPENDED
        db.commit()

    r = ana.get("/api/v1/me/stockwatcher/watches")
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "cuenta_suspendida"


def test_las_mutaciones_exigen_csrf(ana):
    r = ana.raw.post("/api/v1/me/stockwatcher/watches", json=WATCH)
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "csrf_invalido"
