"""Tests del workspace aislado por usuario."""

from __future__ import annotations

import pytest

from homelab_dashboard.workspace import UserWorkspace, WorkspaceError, validar_user_id

USER_A = "a" * 32
USER_B = "b" * 32


@pytest.mark.parametrize(
    "malo",
    [
        "",
        "..",
        "../otro",
        "a" * 31,
        "a" * 33,
        "A" * 32,  # mayúsculas: los uuid4 se guardan en minúsculas
        "g" * 32,  # fuera del alfabeto hexadecimal
        "../../etc/passwd",
        "a" * 30 + "/x",
    ],
)
def test_user_id_invalido_se_rechaza(malo):
    with pytest.raises(WorkspaceError):
        validar_user_id(malo)


def test_user_id_valido_pasa():
    assert validar_user_id(USER_A) == USER_A


def test_el_workspace_cuelga_de_la_carpeta_de_usuarios(settings):
    ws = UserWorkspace.para(settings, USER_A)
    assert ws.raiz == settings.users_dir.resolve() / USER_A


def test_dos_usuarios_no_comparten_rutas(settings):
    a = UserWorkspace.para(settings, USER_A)
    b = UserWorkspace.para(settings, USER_B)
    assert a.raiz != b.raiz
    assert a.ruta_estado("stockwatcher", "x.db") != b.ruta_estado("stockwatcher", "x.db")


@pytest.mark.parametrize("malo", ["../fuera.yaml", "sub/dir.yaml", ".oculto", "a\\b"])
def test_nombre_de_archivo_con_traversal_se_rechaza(settings, malo):
    ws = UserWorkspace.para(settings, USER_A)
    with pytest.raises(WorkspaceError):
        ws.ruta_config("stockwatcher", malo)


@pytest.mark.parametrize("malo", ["..", "../otra", "con/barra", "MAYUS", ""])
def test_nombre_de_app_invalido_se_rechaza(settings, malo):
    ws = UserWorkspace.para(settings, USER_A)
    with pytest.raises(WorkspaceError):
        ws.dir_app(malo)


def test_preparar_crea_los_directorios_con_permisos_restrictivos(settings):
    ws = UserWorkspace.para(settings, USER_A)
    ws.preparar("stockwatcher")
    assert ws.dir_config("stockwatcher").is_dir()
    assert ws.dir_estado("stockwatcher").is_dir()
    assert oct(ws.raiz.stat().st_mode)[-3:] == "700"


def test_escribir_config_es_atomica_y_privada(settings):
    ws = UserWorkspace.para(settings, USER_A)
    destino = ws.escribir_config("stockwatcher", "watches.yaml", "watches: []\n")
    assert destino.read_text(encoding="utf-8") == "watches: []\n"
    assert oct(destino.stat().st_mode)[-3:] == "600"


def test_escribir_config_no_deja_temporales(settings):
    ws = UserWorkspace.para(settings, USER_A)
    ws.escribir_config("stockwatcher", "watches.yaml", "watches: []\n")
    ws.escribir_config("stockwatcher", "watches.yaml", "watches: [1]\n")
    archivos = sorted(p.name for p in ws.dir_config("stockwatcher").iterdir())
    assert archivos == ["watches.yaml"]


def test_escribir_config_sobrescribe(settings):
    ws = UserWorkspace.para(settings, USER_A)
    ws.escribir_config("stockwatcher", "watches.yaml", "uno\n")
    destino = ws.escribir_config("stockwatcher", "watches.yaml", "dos\n")
    assert destino.read_text(encoding="utf-8") == "dos\n"


def test_eliminar_borra_solo_el_workspace_del_usuario(settings):
    a = UserWorkspace.para(settings, USER_A)
    b = UserWorkspace.para(settings, USER_B)
    a.escribir_config("stockwatcher", "watches.yaml", "a\n")
    b.escribir_config("stockwatcher", "watches.yaml", "b\n")

    a.eliminar()

    assert not a.raiz.exists()
    assert b.raiz.exists()


def test_eliminar_es_idempotente(settings):
    ws = UserWorkspace.para(settings, USER_A)
    ws.eliminar()
    ws.eliminar()
