"""Tests de la API de administración.

Dos bloques importan por encima del resto: que un usuario normal no vea nunca
`/admin/*` (y reciba 404, no 403), y que las barandas impidan dejar la
instalación sin ningún administrador con acceso.
"""

from __future__ import annotations

import pytest
from conftest import PASSWORD_DE_PRUEBA, entrar
from sqlalchemy import select

from homelab_dashboard.models import (
    JOB_ERROR,
    ROLE_ADMIN,
    USER_ACTIVE,
    USER_SUSPENDED,
    AuditLog,
    JobRun,
    User,
)

OTRA_PASSWORD = "Otra-Password-Larga-9"


@pytest.fixture()
def app(app_watchers):
    """Registro con los watchers reales, para poder lanzar y cancelar."""
    return app_watchers


@pytest.fixture()
def sesion(app):
    with app.state.session_factory() as db:
        yield db


@pytest.fixture()
def ana(admin, nuevo_usuario):
    """Usuaria normal. `admin` va primero: el primer registro nace admin."""
    return nuevo_usuario("ana@example.com")


def _id_de(admin, email: str) -> str:
    usuarios = admin.get("/api/v1/admin/users").json()["items"]
    return next(u["id"] for u in usuarios if u["email"] == email)


# ---------------------------------------------------------------------------
# Autorización
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "metodo,ruta",
    [
        ("GET", "/api/v1/admin/users"),
        ("GET", "/api/v1/admin/metrics"),
        ("GET", "/api/v1/admin/runs"),
        ("GET", "/api/v1/admin/audit"),
        ("GET", "/api/v1/admin/users/loquesea"),
    ],
)
def test_usuario_normal_recibe_404(ana, metodo, ruta):
    """404 y no 403: para quien no es admin, el panel no existe."""
    assert ana.request(metodo, ruta).status_code == 404


def test_anonimo_recibe_401(client):
    assert client.get("/api/v1/admin/users").status_code == 401


def test_admin_entra(admin):
    assert admin.get("/api/v1/admin/users").status_code == 200


# ---------------------------------------------------------------------------
# Listado
# ---------------------------------------------------------------------------


def test_listado_incluye_a_todos(admin, nuevo_usuario):
    nuevo_usuario("uno@example.com")
    nuevo_usuario("dos@example.com")
    cuerpo = admin.get("/api/v1/admin/users").json()
    assert cuerpo["total"] == 3
    correos = {u["email"] for u in cuerpo["items"]}
    assert {"uno@example.com", "dos@example.com"} <= correos


def test_no_expone_el_hash_de_la_password(admin, ana):
    cuerpo = admin.get("/api/v1/admin/users").text
    assert "password_hash" not in cuerpo
    assert "$argon2" not in cuerpo


def test_busqueda_por_correo(admin, nuevo_usuario):
    nuevo_usuario("carolina@example.com")
    nuevo_usuario("pedro@example.com")
    items = admin.get("/api/v1/admin/users?q=carol").json()["items"]
    assert [u["email"] for u in items] == ["carolina@example.com"]


def test_busqueda_ignora_mayusculas(admin, nuevo_usuario):
    nuevo_usuario("carolina@example.com")
    assert admin.get("/api/v1/admin/users?q=CAROL").json()["total"] == 1


def test_filtro_por_estado(admin, ana):
    items = admin.get("/api/v1/admin/users?status=pending").json()["items"]
    assert [u["email"] for u in items] == ["ana@example.com"]


def test_filtro_por_rol(admin, ana):
    items = admin.get("/api/v1/admin/users?role=admin").json()["items"]
    assert all(u["role"] == "admin" for u in items)
    assert len(items) == 1


def test_orden_por_correo(admin, nuevo_usuario):
    nuevo_usuario("zeta@example.com")
    nuevo_usuario("alfa@example.com")
    items = admin.get("/api/v1/admin/users?sort=email&order=asc").json()["items"]
    correos = [u["email"] for u in items]
    assert correos == sorted(correos)


def test_orden_invalido_da_422(admin):
    assert admin.get("/api/v1/admin/users?order=cualquiera").status_code == 422


def test_campo_de_orden_desconocido_no_revienta(admin):
    """Un `sort` inventado cae al orden por defecto en vez de dar un 500."""
    assert admin.get("/api/v1/admin/users?sort=; DROP TABLE users").status_code == 200


def test_paginacion(admin, nuevo_usuario):
    for i in range(4):
        nuevo_usuario(f"u{i}@example.com")
    cuerpo = admin.get("/api/v1/admin/users?limit=2&offset=1").json()
    assert cuerpo["total"] == 5
    assert len(cuerpo["items"]) == 2
    assert cuerpo["offset"] == 1


# ---------------------------------------------------------------------------
# Ficha del usuario
# ---------------------------------------------------------------------------


def test_ficha_resume_la_configuracion(admin, ana):
    ana.post(
        "/api/v1/me/stockwatcher/watches",
        json={"name": "Zapatos", "match_terms": ["zapato"]},
    )
    ana.post(
        "/api/v1/me/portfolio/holdings",
        json={"ticker": "AAPL", "quantity": 3, "avg_cost": 100},
    )
    ana.put("/api/v1/me/notifications", json={"whatsapp": "+573001112233"})

    ficha = admin.get(f"/api/v1/admin/users/{_id_de(admin, 'ana@example.com')}").json()
    assert ficha["watches"] == 1
    assert ficha["holdings"] == 1
    assert ficha["user"]["email"] == "ana@example.com"
    assert [c["channel"] for c in ficha["channels"]] == ["whatsapp"]


def test_ficha_incluye_la_programacion(admin, ana):
    ana.put(
        "/api/v1/me/schedules/stockwatcher/cmd-run",
        json={"enabled": True, "kind": "interval", "interval_minutes": 60},
    )
    ficha = admin.get(f"/api/v1/admin/users/{_id_de(admin, 'ana@example.com')}").json()
    assert len(ficha["schedules"]) == 1
    assert ficha["schedules"][0]["next_run_at"] is not None


def test_ficha_de_usuario_inexistente_da_404(admin):
    assert admin.get("/api/v1/admin/users/noexiste").status_code == 404


# ---------------------------------------------------------------------------
# Estado y rol
# ---------------------------------------------------------------------------


def test_activar_usuario(admin, ana):
    uid = _id_de(admin, "ana@example.com")
    r = admin.patch(f"/api/v1/admin/users/{uid}", json={"status": "active"})
    assert r.status_code == 200
    assert r.json()["status"] == "active"


def test_activar_permite_ejecutar(admin, ana):
    """Antes de activar, el usuario no puede lanzar nada."""
    ana.put("/api/v1/me/notifications", json={"whatsapp": "+573001112233"})
    ana.post(
        "/api/v1/me/stockwatcher/watches",
        json={"name": "Zapatos", "match_terms": ["zapato"], "notify_channels": ["whatsapp"]},
    )
    antes = ana.post(
        "/api/v1/me/apps/stockwatcher/runs", json={"command_key": "cmd-run"}
    )
    assert antes.status_code == 403

    admin.patch(
        f"/api/v1/admin/users/{_id_de(admin, 'ana@example.com')}",
        json={"status": "active"},
    )
    despues = ana.post(
        "/api/v1/me/apps/stockwatcher/runs", json={"command_key": "cmd-run"}
    )
    assert despues.status_code == 201, despues.text


def test_suspender_cierra_la_sesion_abierta(admin, ana):
    """Suspender sin revocar la cookie no suspendería nada."""
    assert ana.get("/api/v1/auth/me").status_code == 200
    admin.patch(
        f"/api/v1/admin/users/{_id_de(admin, 'ana@example.com')}",
        json={"status": "suspended"},
    )
    assert ana.get("/api/v1/auth/me").status_code == 401


def test_promover_a_admin(admin, ana):
    uid = _id_de(admin, "ana@example.com")
    admin.patch(f"/api/v1/admin/users/{uid}", json={"status": "active"})
    r = admin.patch(f"/api/v1/admin/users/{uid}", json={"role": "admin"})
    assert r.json()["role"] == "admin"
    assert ana.get("/api/v1/admin/users").status_code == 200


def test_degradar_admin(admin, nuevo_usuario, sesion):
    otro = nuevo_usuario("otro@example.com")
    uid = _id_de(admin, "otro@example.com")
    admin.patch(f"/api/v1/admin/users/{uid}", json={"status": "active", "role": "admin"})
    r = admin.patch(f"/api/v1/admin/users/{uid}", json={"role": "user"})
    assert r.json()["role"] == "user"
    assert otro.get("/api/v1/admin/users").status_code == 404


def test_estado_invalido_da_422(admin, ana):
    uid = _id_de(admin, "ana@example.com")
    assert (
        admin.patch(f"/api/v1/admin/users/{uid}", json={"status": "zombi"}).status_code
        == 422
    )


def test_patch_vacio_no_cambia_nada(admin, ana):
    uid = _id_de(admin, "ana@example.com")
    r = admin.patch(f"/api/v1/admin/users/{uid}", json={})
    assert r.status_code == 200
    assert r.json()["status"] == "pending"


# -- barandas del último admin ---------------------------------------------


def test_no_puedo_degradarme_siendo_el_unico_admin(admin):
    uid = _id_de(admin, "admin@ejemplo.com")
    r = admin.patch(f"/api/v1/admin/users/{uid}", json={"role": "user"})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "ultimo_admin"


def test_no_puedo_suspenderme_siendo_el_unico_admin(admin):
    uid = _id_de(admin, "admin@ejemplo.com")
    r = admin.patch(f"/api/v1/admin/users/{uid}", json={"status": "suspended"})
    assert r.status_code == 409


def test_puedo_degradarme_si_hay_otro_admin(admin, nuevo_usuario):
    otro_id = None
    nuevo_usuario("segundo@example.com")
    otro_id = _id_de(admin, "segundo@example.com")
    admin.patch(
        f"/api/v1/admin/users/{otro_id}", json={"status": "active", "role": "admin"}
    )
    yo = _id_de(admin, "admin@ejemplo.com")
    assert admin.patch(f"/api/v1/admin/users/{yo}", json={"role": "user"}).status_code == 200


def test_un_admin_suspendido_no_cuenta_como_activo(admin, nuevo_usuario):
    """Dejar un admin suspendido no basta: no podría entrar a arreglarlo."""
    nuevo_usuario("dormido@example.com")
    otro = _id_de(admin, "dormido@example.com")
    admin.patch(f"/api/v1/admin/users/{otro}", json={"role": "admin"})  # sigue pending
    yo = _id_de(admin, "admin@ejemplo.com")
    assert admin.patch(f"/api/v1/admin/users/{yo}", json={"role": "user"}).status_code == 409


# ---------------------------------------------------------------------------
# Contraseñas
# ---------------------------------------------------------------------------


def test_asignar_password_obliga_a_cambiarla(admin, ana, client):
    uid = _id_de(admin, "ana@example.com")
    r = admin.post(
        f"/api/v1/admin/users/{uid}/password", json={"new_password": OTRA_PASSWORD}
    )
    assert r.status_code == 204

    # La sesión anterior de Ana ya no vale.
    assert ana.get("/api/v1/auth/me").status_code == 401

    acceso = entrar(ana.raw, "ana@example.com", OTRA_PASSWORD)
    assert acceso.status_code == 200
    assert acceso.json()["user"]["must_change_password"] is True


def test_password_debil_rechazada(admin, ana):
    uid = _id_de(admin, "ana@example.com")
    assert (
        admin.post(
            f"/api/v1/admin/users/{uid}/password", json={"new_password": "corta"}
        ).status_code
        == 422
    )


def test_forzar_reset_deja_la_cuenta_sin_acceso(admin, ana):
    uid = _id_de(admin, "ana@example.com")
    assert (
        admin.post(f"/api/v1/admin/users/{uid}/password", json={"force_reset": True}).status_code
        == 204
    )
    assert entrar(ana.raw, "ana@example.com", PASSWORD_DE_PRUEBA).status_code == 401


def test_no_se_puede_pedir_las_dos_cosas(admin, ana):
    uid = _id_de(admin, "ana@example.com")
    r = admin.post(
        f"/api/v1/admin/users/{uid}/password",
        json={"new_password": OTRA_PASSWORD, "force_reset": True},
    )
    assert r.status_code == 422


def test_hay_que_pedir_alguna(admin, ana):
    uid = _id_de(admin, "ana@example.com")
    assert admin.post(f"/api/v1/admin/users/{uid}/password", json={}).status_code == 422


def test_reset_desbloquea_la_cuenta(admin, ana, sesion):
    usuario = sesion.scalars(select(User).where(User.email == "ana@example.com")).one()
    usuario.failed_login_count = 5
    sesion.commit()

    admin.post(
        f"/api/v1/admin/users/{usuario.id}/password", json={"new_password": OTRA_PASSWORD}
    )
    sesion.expire_all()
    assert sesion.get(User, usuario.id).failed_login_count == 0


# ---------------------------------------------------------------------------
# Eliminación
# ---------------------------------------------------------------------------


def test_eliminar_borra_al_usuario_y_sus_datos(admin, ana, sesion):
    ana.post(
        "/api/v1/me/stockwatcher/watches",
        json={"name": "Zapatos", "match_terms": ["zapato"]},
    )
    uid = _id_de(admin, "ana@example.com")
    assert admin.delete(f"/api/v1/admin/users/{uid}").status_code == 204

    assert admin.get(f"/api/v1/admin/users/{uid}").status_code == 404
    from homelab_dashboard.models import StockWatch

    assert (
        sesion.scalars(select(StockWatch).where(StockWatch.user_id == uid)).all() == []
    )


def test_eliminar_borra_el_workspace(admin, ana, settings, sesion):
    from homelab_dashboard.workspace import UserWorkspace

    uid = _id_de(admin, "ana@example.com")
    ws = UserWorkspace.para(settings, uid)
    ws.preparar("stockwatcher")
    assert ws.raiz.is_dir()

    admin.delete(f"/api/v1/admin/users/{uid}")
    assert not ws.raiz.exists()


def test_eliminar_borra_sus_logs(admin, ana, settings):
    uid = _id_de(admin, "ana@example.com")
    carpeta = settings.logs_dir / uid / "stockwatcher"
    carpeta.mkdir(parents=True)
    (carpeta / "x.log").write_text("hola")

    admin.delete(f"/api/v1/admin/users/{uid}")
    assert not (settings.logs_dir / uid).exists()


def test_eliminar_no_toca_los_logs_de_otro(admin, nuevo_usuario, settings):
    nuevo_usuario("uno@example.com")
    nuevo_usuario("dos@example.com")
    uno, dos = _id_de(admin, "uno@example.com"), _id_de(admin, "dos@example.com")
    for uid in (uno, dos):
        (settings.logs_dir / uid).mkdir(parents=True)

    admin.delete(f"/api/v1/admin/users/{uno}")
    assert not (settings.logs_dir / uno).exists()
    assert (settings.logs_dir / dos).is_dir()


def test_no_puedo_eliminarme_a_mi_mismo(admin):
    uid = _id_de(admin, "admin@ejemplo.com")
    r = admin.delete(f"/api/v1/admin/users/{uid}")
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "autoborrado"


def test_eliminar_inexistente_da_404(admin):
    assert admin.delete("/api/v1/admin/users/fantasma").status_code == 404


# ---------------------------------------------------------------------------
# Ejecuciones
# ---------------------------------------------------------------------------


def _preparar_para_correr(admin, cliente, email):
    cliente.put("/api/v1/me/notifications", json={"whatsapp": "+573001112233"})
    cliente.post(
        "/api/v1/me/stockwatcher/watches",
        json={
            "name": "Zapatos",
            "match_terms": ["zapato"],
            "notify_channels": ["whatsapp"],
        },
    )
    admin.patch(f"/api/v1/admin/users/{_id_de(admin, email)}", json={"status": "active"})
    return _id_de(admin, email)


def test_admin_dispara_el_job_de_otro(admin, ana):
    uid = _preparar_para_correr(admin, ana, "ana@example.com")
    r = admin.post(
        f"/api/v1/admin/users/{uid}/apps/stockwatcher/runs",
        json={"command_key": "cmd-run"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["app_name"] == "stockwatcher"


def test_la_corrida_lanzada_por_admin_es_del_usuario(admin, ana):
    """El job corre con la configuración del usuario, no con la del admin."""
    uid = _preparar_para_correr(admin, ana, "ana@example.com")
    admin.post(
        f"/api/v1/admin/users/{uid}/apps/stockwatcher/runs",
        json={"command_key": "cmd-run"},
    )
    mias = admin.get("/api/v1/me/runs").json()["items"]
    assert mias == []
    suyas = ana.get("/api/v1/me/runs").json()["items"]
    assert len(suyas) == 1


def test_cancelar_sin_job_da_404(admin, ana):
    uid = _id_de(admin, "ana@example.com")
    r = admin.delete(f"/api/v1/admin/users/{uid}/apps/stockwatcher/runs/current")
    assert r.status_code == 404


def test_listado_de_ejecuciones_incluye_el_correo(admin, ana):
    uid = _preparar_para_correr(admin, ana, "ana@example.com")
    admin.post(
        f"/api/v1/admin/users/{uid}/apps/stockwatcher/runs",
        json={"command_key": "cmd-run"},
    )
    items = admin.get("/api/v1/admin/runs").json()["items"]
    assert items[0]["user_email"] == "ana@example.com"


def test_filtro_de_ejecuciones_por_estado(admin, ana, sesion):
    sesion.add(
        JobRun(
            user_id=_id_de(admin, "ana@example.com"),
            app_name="stockwatcher",
            command_key="cmd-run",
            command_label="Ejecutar",
            status=JOB_ERROR,
        )
    )
    sesion.commit()
    assert len(admin.get("/api/v1/admin/runs?status=error").json()["items"]) == 1
    assert admin.get("/api/v1/admin/runs?status=success").json()["items"] == []


# ---------------------------------------------------------------------------
# Métricas y bitácora
# ---------------------------------------------------------------------------


def test_metricas(admin, nuevo_usuario):
    nuevo_usuario("uno@example.com")
    m = admin.get("/api/v1/admin/metrics").json()
    assert m["users_total"] == 2
    assert m["users_by_status"]["pending"] == 1
    assert m["admins"] == 1
    assert m["jobs_running"] == 0


def test_metricas_cuentan_los_fallos_recientes(admin, ana, sesion):
    sesion.add(
        JobRun(
            user_id=_id_de(admin, "ana@example.com"),
            app_name="stockwatcher",
            command_key="cmd-run",
            command_label="Ejecutar",
            status=JOB_ERROR,
        )
    )
    sesion.commit()
    assert admin.get("/api/v1/admin/metrics").json()["recent_failures"] == 1


def test_la_bitacora_registra_los_cambios(admin, ana):
    uid = _id_de(admin, "ana@example.com")
    admin.patch(f"/api/v1/admin/users/{uid}", json={"status": "active"})
    items = admin.get("/api/v1/admin/audit").json()["items"]
    assert items[0]["action"] == "usuario.estado"
    assert items[0]["actor_email"] == "admin@ejemplo.com"
    assert items[0]["target_email"] == "ana@example.com"
    assert items[0]["detail_json"]["despues"] == "active"


def test_la_bitacora_sobrevive_al_borrado(admin, ana, sesion):
    """Una bitácora que olvida a quién se borró no sirve para auditar."""
    uid = _id_de(admin, "ana@example.com")
    admin.delete(f"/api/v1/admin/users/{uid}")

    entrada = sesion.scalars(
        select(AuditLog).where(AuditLog.action == "usuario.eliminado")
    ).one()
    assert entrada.target_email == "ana@example.com"
    assert entrada.target_user_id is None


def test_la_bitacora_no_registra_lecturas(admin, ana):
    admin.get("/api/v1/admin/users")
    admin.get(f"/api/v1/admin/users/{_id_de(admin, 'ana@example.com')}")
    assert admin.get("/api/v1/admin/audit").json()["items"] == []


# ---------------------------------------------------------------------------
# Servicio, sin pasar por HTTP
# ---------------------------------------------------------------------------


def test_contar_admins_activos(db):
    from conftest import crear_usuario

    from homelab_dashboard import admin as servicio

    assert servicio.contar_admins_activos(db) == 0
    crear_usuario(db, "a@example.com", role=ROLE_ADMIN, status=USER_ACTIVE)
    crear_usuario(db, "b@example.com", role=ROLE_ADMIN, status=USER_SUSPENDED)
    assert servicio.contar_admins_activos(db) == 1


def test_borrar_logs_no_escapa_del_arbol(settings, tmp_path):
    from homelab_dashboard.admin import _borrar_logs

    victima = tmp_path / "victima"
    victima.mkdir()
    _borrar_logs(settings, "../../victima")
    assert victima.is_dir()
