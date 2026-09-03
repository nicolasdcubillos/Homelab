"""Tests de los endpoints de autenticación."""

from __future__ import annotations

import pytest
from conftest import PASSWORD_DE_PRUEBA, ClienteAutenticado, entrar, registrar

from homelab_dashboard.models import ROLE_ADMIN, ROLE_USER, USER_ACTIVE, USER_PENDING

# ---------------------------------------------------------------------------
# Registro
# ---------------------------------------------------------------------------


def test_el_primer_registro_nace_admin_activo(client):
    """Una instalación vacía necesita alguien que pueda aprobar al resto."""
    r = registrar(client, "primero@ejemplo.com")
    assert r.status_code == 201, r.text
    usuario = r.json()["user"]
    assert usuario["role"] == ROLE_ADMIN
    assert usuario["status"] == USER_ACTIVE


def test_los_registros_siguientes_nacen_pendientes(client):
    registrar(client, "admin@ejemplo.com")
    r = registrar(client, "segundo@ejemplo.com")
    assert r.status_code == 201
    usuario = r.json()["user"]
    assert usuario["role"] == ROLE_USER
    assert usuario["status"] == USER_PENDING


def test_el_registro_nunca_devuelve_el_hash(client):
    r = registrar(client, "primero@ejemplo.com")
    assert "$argon2" not in r.text
    assert "password_hash" not in r.text
    assert PASSWORD_DE_PRUEBA not in r.text


def test_email_duplicado_da_409(client):
    registrar(client, "admin@ejemplo.com")
    r = registrar(client, "admin@ejemplo.com")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "email_ya_registrado"


def test_email_duplicado_ignora_mayusculas(client):
    registrar(client, "admin@ejemplo.com")
    r = registrar(client, "ADMIN@Ejemplo.com")
    assert r.status_code == 409


def test_password_debil_da_422_con_mensaje_en_espanol(client):
    r = client.post(
        "/api/v1/auth/register", json={"email": "a@b.com", "password": "corta"}
    )
    assert r.status_code == 422
    cuerpo = r.json()["error"]
    assert cuerpo["code"] == "validacion"
    assert "password" in cuerpo["fields"]


def test_email_invalido_da_422(client):
    r = client.post(
        "/api/v1/auth/register", json={"email": "no-es-correo", "password": PASSWORD_DE_PRUEBA}
    )
    assert r.status_code == 422


def test_campo_desconocido_se_rechaza(client):
    """`extra="forbid"` evita que un typo del frontend se guarde a medias."""
    r = client.post(
        "/api/v1/auth/register",
        json={"email": "a@b.com", "password": PASSWORD_DE_PRUEBA, "role": "admin"},
    )
    assert r.status_code == 422


def test_no_se_puede_escalar_a_admin_por_el_body(client):
    """Aunque el campo se colara, el rol nunca sale del cuerpo del request."""
    registrar(client, "admin@ejemplo.com")
    r = client.post(
        "/api/v1/auth/register",
        json={"email": "atacante@ejemplo.com", "password": PASSWORD_DE_PRUEBA},
    )
    assert r.json()["user"]["role"] == ROLE_USER


def test_timezone_invalida_se_rechaza(client):
    r = client.post(
        "/api/v1/auth/register",
        json={
            "email": "a@b.com",
            "password": PASSWORD_DE_PRUEBA,
            "timezone": "Marte/Olympus",
        },
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


def test_login_correcto_deja_cookies(client):
    registrar(client, "admin@ejemplo.com")
    r = entrar(client, "admin@ejemplo.com")
    assert r.status_code == 200
    assert client.cookies.get("hld_session")
    assert client.cookies.get("hld_csrf")
    assert r.json()["csrf_token"] == client.cookies.get("hld_csrf")


def test_la_cookie_de_sesion_es_httponly_y_lax(client):
    registrar(client, "admin@ejemplo.com")
    r = entrar(client, "admin@ejemplo.com")
    # `headers.items()` colapsa las cabeceras repetidas; hay que pedir la lista.
    cookies = r.headers.get_list("set-cookie")
    sesion = [c for c in cookies if c.startswith("hld_session=")]
    assert sesion, cookies
    assert "HttpOnly" in sesion[0]
    assert "samesite=lax" in sesion[0].lower()


def test_la_cookie_csrf_no_es_httponly(client):
    """La SPA tiene que poder leerla para reenviarla en la cabecera."""
    registrar(client, "admin@ejemplo.com")
    r = entrar(client, "admin@ejemplo.com")
    csrf = [c for c in r.headers.get_list("set-cookie") if c.startswith("hld_csrf=")]
    assert csrf
    assert "HttpOnly" not in csrf[0]


def test_password_incorrecta_da_401(client):
    registrar(client, "admin@ejemplo.com")
    r = entrar(client, "admin@ejemplo.com", "OtraCosa123")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "credenciales_invalidas"


def test_usuario_inexistente_da_el_mismo_error_que_password_mala(client):
    """No debe existir un oráculo de enumeración de correos."""
    registrar(client, "admin@ejemplo.com")
    r_inexistente = entrar(client, "nadie@ejemplo.com")
    r_mala = entrar(client, "admin@ejemplo.com", "OtraCosa123")
    assert r_inexistente.status_code == r_mala.status_code == 401
    assert r_inexistente.json() == r_mala.json()


def test_login_con_correo_en_mayusculas_funciona(client):
    registrar(client, "admin@ejemplo.com")
    assert entrar(client, "ADMIN@EJEMPLO.COM").status_code == 200


def test_usuario_pendiente_puede_entrar_pero_no_operar(client):
    registrar(client, "admin@ejemplo.com")
    registrar(client, "nuevo@ejemplo.com")
    r = entrar(client, "nuevo@ejemplo.com")
    assert r.status_code == 200, "debe poder ver el estado de su cuenta"
    assert r.json()["user"]["status"] == USER_PENDING


# ---------------------------------------------------------------------------
# Límite de intentos
# ---------------------------------------------------------------------------


def test_tras_varios_fallos_la_cuenta_se_bloquea(client):
    registrar(client, "admin@ejemplo.com")
    for _ in range(5):
        entrar(client, "admin@ejemplo.com", "Incorrecta123")
    r = entrar(client, "admin@ejemplo.com", "Incorrecta123")
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "cuenta_bloqueada"


def test_el_bloqueo_ignora_la_password_correcta(client):
    """Si no, un atacante que acierte tras 100 intentos entraría igual."""
    registrar(client, "admin@ejemplo.com")
    for _ in range(5):
        entrar(client, "admin@ejemplo.com", "Incorrecta123")
    r = entrar(client, "admin@ejemplo.com")
    assert r.status_code == 429


def test_el_bloqueo_no_afecta_a_otra_cuenta(client):
    registrar(client, "admin@ejemplo.com")
    registrar(client, "otro@ejemplo.com")
    for _ in range(5):
        entrar(client, "otro@ejemplo.com", "Incorrecta123")
    assert entrar(client, "admin@ejemplo.com").status_code == 200


# ---------------------------------------------------------------------------
# Sesión
# ---------------------------------------------------------------------------


def test_me_sin_sesion_da_401(client):
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "no_autenticado"


def test_me_devuelve_al_usuario_en_sesion(admin):
    r = admin.get("/api/v1/auth/me")
    assert r.status_code == 200
    assert r.json()["user"]["email"] == "admin@ejemplo.com"


def test_logout_invalida_la_sesion(admin, client):
    assert admin.post("/api/v1/auth/logout").status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 401


def test_logout_sin_sesion_no_falla(client):
    assert client.post("/api/v1/auth/logout").status_code == 200


def test_una_cookie_inventada_no_abre_sesion(client):
    client.cookies.set("hld_session", "token-inventado")
    assert client.get("/api/v1/auth/me").status_code == 401


def test_la_sesion_no_se_reactiva_tras_logout(admin, client):
    token = client.cookies.get("hld_session")
    admin.post("/api/v1/auth/logout")
    client.cookies.set("hld_session", token)
    assert client.get("/api/v1/auth/me").status_code == 401


# ---------------------------------------------------------------------------
# CSRF
# ---------------------------------------------------------------------------


def test_peticion_mutante_sin_csrf_se_rechaza(admin, client):
    r = client.put("/api/v1/auth/profile", json={"timezone": "Europe/Madrid"})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "csrf_invalido"


def test_peticion_mutante_con_csrf_incorrecto_se_rechaza(admin, client):
    r = client.put(
        "/api/v1/auth/profile",
        json={"timezone": "Europe/Madrid"},
        headers={"X-CSRF-Token": "no-es-el-token"},
    )
    assert r.status_code == 403


def test_peticion_mutante_con_csrf_correcto_pasa(admin):
    r = admin.put("/api/v1/auth/profile", json={"timezone": "Europe/Madrid"})
    assert r.status_code == 200
    assert r.json()["timezone"] == "Europe/Madrid"


def test_el_get_no_exige_csrf(admin, client):
    assert client.get("/api/v1/auth/me").status_code == 200


def test_csrf_de_otra_sesion_no_sirve(client):
    """El token está atado a la fila de sesión, no es global."""
    registrar(client, "admin@ejemplo.com")
    entrar(client, "admin@ejemplo.com")
    token_ajeno = client.cookies.get("hld_csrf")
    client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": token_ajeno})

    entrar(client, "admin@ejemplo.com")
    r = client.put(
        "/api/v1/auth/profile",
        json={"timezone": "Europe/Madrid"},
        headers={"X-CSRF-Token": token_ajeno},
    )
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# Cambio de contraseña
# ---------------------------------------------------------------------------


def test_cambiar_password_exige_la_actual(admin):
    r = admin.post(
        "/api/v1/auth/password",
        json={"password_actual": "Incorrecta123", "password_nueva": "NuevaClave456"},
    )
    assert r.status_code == 401


def test_cambiar_password_funciona_y_la_nueva_sirve(admin, client):
    r = admin.post(
        "/api/v1/auth/password",
        json={"password_actual": PASSWORD_DE_PRUEBA, "password_nueva": "NuevaClave456"},
    )
    assert r.status_code == 200, r.text
    admin.post("/api/v1/auth/logout")
    assert entrar(client, "admin@ejemplo.com", "NuevaClave456").status_code == 200
    assert entrar(client, "admin@ejemplo.com", PASSWORD_DE_PRUEBA).status_code == 401


def test_cambiar_password_no_cierra_la_sesion_actual(admin):
    admin.post(
        "/api/v1/auth/password",
        json={"password_actual": PASSWORD_DE_PRUEBA, "password_nueva": "NuevaClave456"},
    )
    assert admin.get("/api/v1/auth/me").status_code == 200


def test_la_password_nueva_debe_ser_distinta(admin):
    r = admin.post(
        "/api/v1/auth/password",
        json={"password_actual": PASSWORD_DE_PRUEBA, "password_nueva": PASSWORD_DE_PRUEBA},
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "password_repetida"


def test_la_password_nueva_tambien_valida_politica(admin):
    r = admin.post(
        "/api/v1/auth/password",
        json={"password_actual": PASSWORD_DE_PRUEBA, "password_nueva": "corta"},
    )
    assert r.status_code == 422


def test_cambiar_password_cierra_las_sesiones_de_otros_dispositivos(app, admin):
    """Un cambio de credencial debe expulsar al resto de sesiones."""
    from fastapi.testclient import TestClient

    with TestClient(app) as otro_dispositivo:
        assert entrar(otro_dispositivo, "admin@ejemplo.com").status_code == 200
        assert otro_dispositivo.get("/api/v1/auth/me").status_code == 200

        admin.post(
            "/api/v1/auth/password",
            json={"password_actual": PASSWORD_DE_PRUEBA, "password_nueva": "NuevaClave456"},
        )

        assert otro_dispositivo.get("/api/v1/auth/me").status_code == 401


# ---------------------------------------------------------------------------
# Aislamiento entre usuarios
# ---------------------------------------------------------------------------


@pytest.fixture()
def dos_usuarios(app, client):
    """Devuelve dos clientes autenticados como usuarios distintos."""
    registrar(client, "admin@ejemplo.com")
    registrar(client, "ana@ejemplo.com")
    registrar(client, "bruno@ejemplo.com")

    from fastapi.testclient import TestClient

    ana = TestClient(app)
    bruno = TestClient(app)
    entrar(ana, "ana@ejemplo.com")
    entrar(bruno, "bruno@ejemplo.com")
    return ClienteAutenticado(ana), ClienteAutenticado(bruno)


def test_cada_sesion_ve_solo_a_su_usuario(dos_usuarios):
    ana, bruno = dos_usuarios
    assert ana.get("/api/v1/auth/me").json()["user"]["email"] == "ana@ejemplo.com"
    assert bruno.get("/api/v1/auth/me").json()["user"]["email"] == "bruno@ejemplo.com"


def test_el_cambio_de_password_de_uno_no_afecta_al_otro(dos_usuarios, app):
    ana, bruno = dos_usuarios
    ana.post(
        "/api/v1/auth/password",
        json={"password_actual": PASSWORD_DE_PRUEBA, "password_nueva": "NuevaClave456"},
    )
    assert bruno.get("/api/v1/auth/me").status_code == 200
