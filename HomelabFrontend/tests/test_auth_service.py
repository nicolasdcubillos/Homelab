"""Tests del servicio de autenticación y del comando `create-admin`.

Cubren los caminos que son incómodos de alcanzar por HTTP: expiración de
sesiones, suspensión, reset forzado y purgas.
"""

from __future__ import annotations

import datetime as dt

import pytest
from conftest import PASSWORD_DE_PRUEBA, entrar, registrar

from homelab_dashboard import auth
from homelab_dashboard.cli import main as cli_main
from homelab_dashboard.db import utcnow
from homelab_dashboard.models import (
    ROLE_ADMIN,
    ROLE_USER,
    USER_ACTIVE,
    USER_PENDING,
    USER_SUSPENDED,
    AuthSession,
    LoginAttempt,
)


def _crear(db, email="ana@ejemplo.com", **kw):
    kw.setdefault("status", USER_ACTIVE)
    usuario = auth.crear_usuario(db, email=email, password=PASSWORD_DE_PRUEBA, **kw)
    db.commit()
    return usuario


# ---------------------------------------------------------------------------
# Creación
# ---------------------------------------------------------------------------


def test_crear_usuario_normaliza_el_email(db):
    usuario = _crear(db, "  Ana@Ejemplo.COM ")
    assert usuario.email == "ana@ejemplo.com"


def test_crear_usuario_guarda_hash_y_no_la_password(db):
    usuario = _crear(db)
    assert usuario.password_hash.startswith("$argon2id$")
    assert PASSWORD_DE_PRUEBA not in usuario.password_hash


def test_crear_usuario_rechaza_rol_desconocido(db):
    with pytest.raises(auth.ErrorDeAuth):
        auth.crear_usuario(
            db, email="x@y.com", password=PASSWORD_DE_PRUEBA, role="superadmin"
        )


def test_crear_usuario_rechaza_estado_desconocido(db):
    with pytest.raises(auth.ErrorDeAuth):
        auth.crear_usuario(
            db, email="x@y.com", password=PASSWORD_DE_PRUEBA, status="zombie"
        )


def test_hay_algun_usuario(db):
    assert not auth.hay_algun_usuario(db)
    _crear(db)
    assert auth.hay_algun_usuario(db)


def test_contar_admins_activos_ignora_pendientes_y_suspendidos(db):
    _crear(db, "a@x.com", role=ROLE_ADMIN, status=USER_ACTIVE)
    _crear(db, "b@x.com", role=ROLE_ADMIN, status=USER_SUSPENDED)
    _crear(db, "c@x.com", role=ROLE_ADMIN, status=USER_PENDING)
    _crear(db, "d@x.com", role=ROLE_USER, status=USER_ACTIVE)
    assert auth.contar_admins_activos(db) == 1


def test_contar_admins_activos_puede_excluir_a_uno(db):
    a = _crear(db, "a@x.com", role=ROLE_ADMIN)
    _crear(db, "b@x.com", role=ROLE_ADMIN)
    assert auth.contar_admins_activos(db, excluyendo=a.id) == 1


# ---------------------------------------------------------------------------
# Sesiones
# ---------------------------------------------------------------------------


def test_resolver_sesion_devuelve_al_usuario(db, settings):
    usuario = _crear(db)
    sesion = auth.abrir_sesion(db, settings, usuario=usuario)
    db.commit()
    resultado = auth.resolver_sesion(db, sesion.token)
    assert resultado is not None
    assert resultado[1].id == usuario.id


def test_resolver_sesion_con_token_vacio_o_falso(db):
    assert auth.resolver_sesion(db, None) is None
    assert auth.resolver_sesion(db, "") is None
    assert auth.resolver_sesion(db, "inventado") is None


def test_la_base_guarda_el_hash_del_token_no_el_token(db, settings):
    """Un volcado de la base no debe permitir suplantar sesiones vivas."""
    usuario = _crear(db)
    sesion = auth.abrir_sesion(db, settings, usuario=usuario)
    db.commit()
    fila = db.get(AuthSession, sesion.session_id)
    assert fila.token_hash != sesion.token
    assert len(fila.token_hash) == 64


def test_sesion_expirada_no_resuelve(db, settings):
    usuario = _crear(db)
    sesion = auth.abrir_sesion(db, settings, usuario=usuario)
    db.get(AuthSession, sesion.session_id).expires_at = utcnow() - dt.timedelta(seconds=1)
    db.commit()
    assert auth.resolver_sesion(db, sesion.token) is None


def test_sesion_revocada_no_resuelve(db, settings):
    usuario = _crear(db)
    sesion = auth.abrir_sesion(db, settings, usuario=usuario)
    db.commit()
    auth.cerrar_sesion(db, db.get(AuthSession, sesion.session_id))
    db.commit()
    assert auth.resolver_sesion(db, sesion.token) is None


def test_revocar_sesiones_puede_conservar_la_actual(db, settings):
    usuario = _crear(db)
    a = auth.abrir_sesion(db, settings, usuario=usuario)
    b = auth.abrir_sesion(db, settings, usuario=usuario)
    db.commit()

    assert auth.revocar_sesiones_de(db, usuario.id, excepto=a.session_id) == 1
    db.commit()

    assert auth.resolver_sesion(db, a.token) is not None
    assert auth.resolver_sesion(db, b.token) is None


def test_revocar_sesiones_no_toca_a_otros_usuarios(db, settings):
    ana = _crear(db, "ana@x.com")
    bruno = _crear(db, "bruno@x.com")
    sesion_bruno = auth.abrir_sesion(db, settings, usuario=bruno)
    auth.abrir_sesion(db, settings, usuario=ana)
    db.commit()

    auth.revocar_sesiones_de(db, ana.id)
    db.commit()

    assert auth.resolver_sesion(db, sesion_bruno.token) is not None


def test_purgar_sesiones_expiradas(db, settings):
    usuario = _crear(db)
    viva = auth.abrir_sesion(db, settings, usuario=usuario)
    muerta = auth.abrir_sesion(db, settings, usuario=usuario)
    db.get(AuthSession, muerta.session_id).expires_at = utcnow() - dt.timedelta(days=1)
    db.commit()

    assert auth.purgar_sesiones_expiradas(db) == 1
    db.commit()
    assert auth.resolver_sesion(db, viva.token) is not None


# ---------------------------------------------------------------------------
# Autenticación
# ---------------------------------------------------------------------------


def test_autenticar_actualiza_last_login(db, settings):
    usuario = _crear(db)
    assert usuario.last_login_at is None
    auth.autenticar(db, settings, email=usuario.email, password=PASSWORD_DE_PRUEBA)
    assert usuario.last_login_at is not None


def test_autenticar_limpia_el_contador_de_fallos(db, settings):
    usuario = _crear(db)
    with pytest.raises(auth.CredencialesInvalidas):
        auth.autenticar(db, settings, email=usuario.email, password="Incorrecta123")
    assert usuario.failed_login_count == 1

    auth.autenticar(db, settings, email=usuario.email, password=PASSWORD_DE_PRUEBA)
    assert usuario.failed_login_count == 0
    assert usuario.locked_until is None


def test_usuario_suspendido_no_puede_entrar(db, settings):
    usuario = _crear(db, status=USER_SUSPENDED)
    with pytest.raises(auth.CuentaSuspendida):
        auth.autenticar(db, settings, email=usuario.email, password=PASSWORD_DE_PRUEBA)


def test_la_suspension_no_cuenta_como_intento_fallido(db, settings):
    """Si contara, suspender a alguien acabaría bloqueando su cuenta también."""
    usuario = _crear(db, status=USER_SUSPENDED)
    for _ in range(6):
        with pytest.raises(auth.CuentaSuspendida):
            auth.autenticar(db, settings, email=usuario.email, password=PASSWORD_DE_PRUEBA)
    assert usuario.failed_login_count == 0


def test_el_bloqueo_expira_pasada_la_ventana(db, settings):
    usuario = _crear(db)
    for _ in range(settings.login_max_attempts):
        with pytest.raises(auth.CredencialesInvalidas):
            auth.autenticar(db, settings, email=usuario.email, password="Incorrecta123")

    assert usuario.locked_until is not None
    with pytest.raises(auth.CuentaBloqueada):
        auth.autenticar(db, settings, email=usuario.email, password=PASSWORD_DE_PRUEBA)

    # Un rato después de la ventana, la cuenta vuelve a funcionar.
    despues = utcnow() + dt.timedelta(minutes=settings.login_window_minutes + 1)
    sesion = auth.autenticar(
        db, settings, email=usuario.email, password=PASSWORD_DE_PRUEBA, ahora=despues
    )
    assert sesion.user.id == usuario.id


def test_purgar_intentos_antiguos(db, settings):
    usuario = _crear(db)
    with pytest.raises(auth.CredencialesInvalidas):
        auth.autenticar(db, settings, email=usuario.email, password="Incorrecta123")

    assert db.query(LoginAttempt).count() == 1
    assert auth.purgar_intentos_antiguos(db) == 0, "el intento es reciente"

    futuro = utcnow() + dt.timedelta(hours=auth.RETENCION_INTENTOS_HORAS + 1)
    assert auth.purgar_intentos_antiguos(db, ahora=futuro) == 1


# ---------------------------------------------------------------------------
# Cambio de contraseña
# ---------------------------------------------------------------------------


def test_cambiar_password_sin_exigir_actual(db):
    usuario = _crear(db, must_change_password=True)
    auth.cambiar_password(
        db,
        usuario=usuario,
        password_actual=None,
        password_nueva="NuevaClave456",
        exigir_actual=False,
    )
    assert not usuario.must_change_password


def test_cambiar_password_limpia_el_bloqueo(db):
    usuario = _crear(db)
    usuario.failed_login_count = 3
    usuario.locked_until = utcnow() + dt.timedelta(minutes=10)
    auth.cambiar_password(
        db,
        usuario=usuario,
        password_actual=PASSWORD_DE_PRUEBA,
        password_nueva="NuevaClave456",
    )
    assert usuario.failed_login_count == 0
    assert usuario.locked_until is None


# ---------------------------------------------------------------------------
# must_change_password bloquea la API
# ---------------------------------------------------------------------------


def test_must_change_password_viaja_hasta_el_frontend(client, db):
    """La SPA usa este flag para forzar la pantalla de cambio de contraseña.

    El bloqueo efectivo de las rutas operativas lo aporta la dependencia
    `usuario_operativo`, que se ejercita con las rutas de producto.
    """
    registrar(client, "admin@ejemplo.com")
    usuario = auth.buscar_por_email(db, "admin@ejemplo.com")
    usuario.must_change_password = True
    db.commit()

    entrar(client, "admin@ejemplo.com")
    assert client.get("/api/v1/auth/me").json()["user"]["must_change_password"] is True


def test_con_must_change_password_se_puede_cambiar_sin_la_actual(client, db):
    registrar(client, "admin@ejemplo.com")
    usuario = auth.buscar_por_email(db, "admin@ejemplo.com")
    usuario.must_change_password = True
    db.commit()

    entrar(client, "admin@ejemplo.com")
    r = client.post(
        "/api/v1/auth/password",
        json={"password_nueva": "NuevaClave456"},
        headers={"X-CSRF-Token": client.cookies.get("hld_csrf")},
    )
    assert r.status_code == 200, r.text
    assert client.get("/api/v1/auth/me").json()["user"]["must_change_password"] is False


# ---------------------------------------------------------------------------
# CLI create-admin
# ---------------------------------------------------------------------------


def test_create_admin_crea_un_admin_activo(monkeypatch, settings, capsys):
    monkeypatch.setenv("DASHBOARD_ADMIN_PASSWORD", PASSWORD_DE_PRUEBA)
    codigo = cli_main(["create-admin", "--email", "jefe@ejemplo.com"])
    assert codigo == 0
    assert "jefe@ejemplo.com" in capsys.readouterr().out

    from homelab_dashboard.db import create_db_engine, make_session_factory

    with make_session_factory(create_db_engine(settings.db_path))() as db:
        usuario = auth.buscar_por_email(db, "jefe@ejemplo.com")
        assert usuario.role == ROLE_ADMIN
        assert usuario.status == USER_ACTIVE


def test_create_admin_no_pisa_una_cuenta_existente(monkeypatch, settings, capsys):
    monkeypatch.setenv("DASHBOARD_ADMIN_PASSWORD", PASSWORD_DE_PRUEBA)
    cli_main(["create-admin", "--email", "jefe@ejemplo.com"])
    codigo = cli_main(["create-admin", "--email", "jefe@ejemplo.com"])
    assert codigo == 1
    assert "--promote" in capsys.readouterr().err


def test_create_admin_promote_asciende_a_un_usuario_existente(monkeypatch, settings):
    from homelab_dashboard.db import create_db_engine, make_session_factory
    from homelab_dashboard.migrate import upgrade_to_head

    upgrade_to_head(settings)
    factory = make_session_factory(create_db_engine(settings.db_path))
    with factory() as db:
        _crear(db, "normal@ejemplo.com", role=ROLE_USER, status=USER_PENDING)

    monkeypatch.setenv("DASHBOARD_ADMIN_PASSWORD", "OtraClave789")
    assert cli_main(["create-admin", "--email", "normal@ejemplo.com", "--promote"]) == 0

    with factory() as db:
        usuario = auth.buscar_por_email(db, "normal@ejemplo.com")
        assert usuario.role == ROLE_ADMIN
        assert usuario.status == USER_ACTIVE
        from homelab_dashboard.security import verificar_password

        assert verificar_password(usuario.password_hash, "OtraClave789")


def test_create_admin_rechaza_password_debil(monkeypatch, settings, capsys):
    monkeypatch.setenv("DASHBOARD_ADMIN_PASSWORD", "corta")
    assert cli_main(["create-admin", "--email", "jefe@ejemplo.com"]) == 1
    assert "Error" in capsys.readouterr().err
