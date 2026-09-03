"""Fixtures compartidas para los tests de homelab_dashboard."""

from __future__ import annotations

import stat
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from homelab_dashboard.app import create_app
from homelab_dashboard.db import create_db_engine, make_session_factory
from homelab_dashboard.migrate import upgrade_to_head
from homelab_dashboard.settings import load_settings

FAKE_ENTRYPOINT_SCRIPT = """#!/usr/bin/env python3
import sys
import time

def main():
    print("fake-entrypoint called with args:", sys.argv[1:])
    if "--fail" in sys.argv:
        time.sleep(0.05)
        print("simulated failure", file=sys.stderr)
        sys.exit(1)
    if "--slow" in sys.argv:
        time.sleep(1.5)
    print("done")
    sys.exit(0)

if __name__ == "__main__":
    main()
"""


@pytest.fixture()
def fake_app_dir(tmp_path: Path) -> Path:
    """Crea una estructura de app falsa: venv/bin/fakeapp + config/*.yaml."""
    app_dir = tmp_path / "fakeapp"
    (app_dir / "config").mkdir(parents=True)
    (app_dir / "config" / "settings.yaml").write_text("key: value\n", encoding="utf-8")

    venv_bin = app_dir / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    script_path = venv_bin / "fakeapp"
    script_path.write_text(FAKE_ENTRYPOINT_SCRIPT, encoding="utf-8")
    script_path.chmod(script_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    return app_dir


@pytest.fixture()
def apps_yaml_file(tmp_path: Path, fake_app_dir: Path) -> Path:
    content = f"""
apps:
  - name: fakeapp
    display_name: "Fake App"
    path: {fake_app_dir}
    venv_bin: {fake_app_dir}/.venv/bin
    entrypoint: fakeapp
    config_files:
      - label: "Settings"
        path: config/settings.yaml
        type: yaml
    commands:
      - label: "Run OK"
        args: ["--ok"]
      - label: "Run Fail"
        args: ["--fail"]
      - label: "Run Slow"
        args: ["--slow"]
  - name: notinstalled
    display_name: "Not Installed App"
    path: {tmp_path}/does-not-exist
    venv_bin: {tmp_path}/does-not-exist/.venv/bin
    entrypoint: notinstalled
    config_files: []
    commands:
      - label: "Run"
        args: ["run"]
"""
    path = tmp_path / "apps.yaml"
    path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Fixtures de la aplicación multiusuario
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _entorno_limpio(monkeypatch):
    """Aísla los tests de las variables `DASHBOARD_*` de la máquina real."""
    import os

    for nombre in list(os.environ):
        if nombre.startswith("DASHBOARD_"):
            monkeypatch.delenv(nombre, raising=False)
    # Las cookies `Secure` no viajan por http://, que es lo que usa TestClient.
    monkeypatch.setenv("DASHBOARD_SECURE_COOKIES", "false")
    monkeypatch.setenv("DASHBOARD_SCHEDULER_ENABLED", "false")


@pytest.fixture()
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv("DASHBOARD_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DASHBOARD_LOGS_DIR", str(tmp_path / "logs"))
    s = load_settings(apps_file=tmp_path / "apps.yaml")
    s.ensure_directories()
    return s


@pytest.fixture()
def db(settings):
    """Sesión de base directa, para probar servicios sin pasar por HTTP."""
    upgrade_to_head(settings)
    factory = make_session_factory(create_db_engine(settings.db_path))
    with factory() as sesion:
        yield sesion


@pytest.fixture()
def app(settings, apps_yaml_file):
    return create_app(settings=replace(settings, apps_file=apps_yaml_file))


@pytest.fixture()
def client(app):
    with TestClient(app) as c:
        yield c


class ClienteAutenticado:
    """TestClient que reenvía el token CSRF como lo haría la SPA.

    Lee la cookie legible y la manda en la cabecera, para que los tests
    ejerciten el camino real en vez de saltárselo.
    """

    def __init__(self, client: TestClient) -> None:
        self._client = client

    @property
    def cookies(self):
        return self._client.cookies

    def _headers(self, extra: dict | None) -> dict:
        headers = dict(extra or {})
        token = self._client.cookies.get("hld_csrf")
        if token:
            headers.setdefault("X-CSRF-Token", token)
        return headers

    def get(self, url, **kw):
        return self._client.get(url, **kw)

    def post(self, url, *, headers=None, **kw):
        return self._client.post(url, headers=self._headers(headers), **kw)

    def put(self, url, *, headers=None, **kw):
        return self._client.put(url, headers=self._headers(headers), **kw)

    def patch(self, url, *, headers=None, **kw):
        return self._client.patch(url, headers=self._headers(headers), **kw)

    def delete(self, url, *, headers=None, **kw):
        return self._client.delete(url, headers=self._headers(headers), **kw)

    def request(self, metodo, url, *, headers=None, **kw):
        """Para métodos que llevan cuerpo, como DELETE con confirmación."""
        return self._client.request(metodo, url, headers=self._headers(headers), **kw)

    @property
    def raw(self) -> TestClient:
        """El cliente sin el reenvío de CSRF, para probar que se exige."""
        return self._client


PASSWORD_DE_PRUEBA = "Contrasena123"


def registrar(client: TestClient, email: str, password: str = PASSWORD_DE_PRUEBA):
    return client.post(
        "/api/v1/auth/register", json={"email": email, "password": password}
    )


def entrar(client: TestClient, email: str, password: str = PASSWORD_DE_PRUEBA):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


@pytest.fixture()
def admin(client):
    """Cliente autenticado como administrador.

    El primer registro de una instalación vacía nace admin y activo, así que
    este fixture debe pedirse antes de crear cualquier otra cuenta.
    """
    registrar(client, "admin@ejemplo.com")
    respuesta = entrar(client, "admin@ejemplo.com")
    assert respuesta.status_code == 200, respuesta.text
    return ClienteAutenticado(client)


@pytest.fixture()
def nuevo_usuario(app):
    """Crea usuarios con su propio cliente y su propia bolsa de cookies.

    Es imprescindible para los tests de aislamiento: si dos usuarios
    compartieran el `TestClient`, el segundo login pisaría la cookie del
    primero y estaríamos comprobando el aislamiento contra nosotros mismos.
    """
    abiertos: list[TestClient] = []

    def _crear(email: str, password: str = PASSWORD_DE_PRUEBA) -> ClienteAutenticado:
        cliente = TestClient(app)
        abiertos.append(cliente)
        alta = registrar(cliente, email, password)
        assert alta.status_code == 201, alta.text
        acceso = entrar(cliente, email, password)
        assert acceso.status_code == 200, acceso.text
        return ClienteAutenticado(cliente)

    yield _crear

    for cliente in abiertos:
        cliente.close()


@pytest.fixture()
def usuario_cliente(nuevo_usuario):
    """Un usuario cualquiera, ya autenticado. Atajo para los tests de una sola
    cuenta, donde el aislamiento no es lo que se prueba."""
    return nuevo_usuario("usuario@ejemplo.com")


def crear_usuario(db, email: str, *, password: str = PASSWORD_DE_PRUEBA, **kw):
    """Crea un usuario directamente en base, sin pasar por HTTP."""
    from homelab_dashboard import auth

    usuario = auth.crear_usuario(db, email=email, password=password, **kw)
    db.commit()
    return usuario
#: Vuelca argumentos y entorno para poder afirmar sobre ellos, y admite
#: modos de fallo y de bloqueo.
WATCHER_FALSO = """#!/usr/bin/env python3
import json, os, sys, time

datos = {
    "argv": sys.argv[1:],
    "cwd": os.getcwd(),
    "env": {
        k: os.environ.get(k, "")
        for k in (
            "WHATSAPP_TO",
            "EMAIL_TO",
            "STOCKWATCHER_STATE_PATH",
            "PORTFOLIOWATCHER_STATE_PATH",
            "PORTFOLIOWATCHER_NOTIFIERS",
            "PORTFOLIOWATCHER_CONFIG_PATH",
        )
    },
}
print("VOLCADO " + json.dumps(datos), flush=True)

if "--fallar" in sys.argv:
    sys.exit(3)
if "--colgar" in sys.argv:
    time.sleep(60)
sys.exit(0)
"""


def _script(destino: Path) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(WATCHER_FALSO, encoding="utf-8")
    destino.chmod(destino.stat().st_mode | stat.S_IEXEC)


@pytest.fixture()
def apps_watchers(tmp_path: Path) -> Path:
    """Un `apps.yaml` con los dos watchers reales, pero con binarios falsos."""
    bloques = []
    for nombre in ("stockwatcher", "portfoliowatcher"):
        base = tmp_path / nombre
        (base / "config").mkdir(parents=True, exist_ok=True)
        (base / "config" / "stores.yaml").write_text("stores: []\n", encoding="utf-8")
        _script(base / ".venv" / "bin" / nombre)
        bloques.append(
            f"""
  - name: {nombre}
    display_name: "{nombre}"
    path: {base}
    venv_bin: {base}/.venv/bin
    entrypoint: {nombre}
    commands:
      - label: "Ejecutar"
        args: ["run"]
      - label: "Fallar"
        args: ["run", "--fallar"]
      - label: "Colgarse"
        args: ["run", "--colgar"]
"""
        )
    destino = tmp_path / "apps-watchers.yaml"
    destino.write_text("apps:" + "".join(bloques), encoding="utf-8")
    return destino



@pytest.fixture()
def app_watchers(settings, apps_watchers):
    """App cuyo registro conoce los dos watchers reales, con binarios falsos.

    Los tests que necesitan validar contra los nombres y comandos de verdad la
    piden en vez del `app` genérico.
    """
    from dataclasses import replace as _replace

    return create_app(settings=_replace(settings, apps_file=apps_watchers))

