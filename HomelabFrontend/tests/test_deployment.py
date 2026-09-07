from __future__ import annotations

import importlib.util
import os
import socket
import sqlite3
import subprocess
import textwrap
from contextlib import closing
from pathlib import Path

import pytest
from alembic import command

from homelab_dashboard.db import create_db_engine
from homelab_dashboard.migrate import alembic_config, current_revision, head_revision
from homelab_dashboard.settings import load_settings

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "comprobar_despliegue.py"
spec = importlib.util.spec_from_file_location("dashboard_deployment", SCRIPT)
assert spec is not None and spec.loader is not None
deployment = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deployment)
DEPLOY = SCRIPT.with_name("deploy-market-regime.sh")


def test_backup_incluye_wal_sin_alterar_origen(tmp_path):
    source = tmp_path / "source.db"
    destination = tmp_path / "backup.db"
    with closing(sqlite3.connect(source)) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE example (value TEXT)")
        db.execute("INSERT INTO example VALUES ('persistido')")
        db.commit()
        assert Path(str(source) + "-wal").exists()
        deployment.backup_database(source, destination)
        assert db.execute("SELECT value FROM example").fetchall() == [("persistido",)]
    with closing(sqlite3.connect(destination)) as db:
        assert db.execute("SELECT value FROM example").fetchall() == [("persistido",)]
    if os.name == "posix":
        assert destination.stat().st_mode & 0o777 == 0o600


def test_backup_no_sobrescribe_ni_crea_origen(tmp_path):
    source, destination = tmp_path / "source.db", tmp_path / "backup.db"
    with pytest.raises(FileNotFoundError):
        deployment.backup_database(source, destination)
    assert not source.exists() and not destination.exists()
    with closing(sqlite3.connect(source)) as db:
        db.execute("CREATE TABLE example (value TEXT)")
    destination.write_bytes(b"copia previa")
    with pytest.raises(FileExistsError):
        deployment.backup_database(source, destination)
    assert destination.read_bytes() == b"copia previa"


def test_backup_corrupto_elimina_solo_salida_incompleta(tmp_path):
    source, destination = tmp_path / "source.db", tmp_path / "backup.db"
    source.write_bytes(b"not a database")
    with pytest.raises(sqlite3.DatabaseError):
        deployment.backup_database(source, destination)
    assert source.read_bytes() == b"not a database"
    assert not destination.exists()


def test_backup_tiene_plazo_y_no_deja_copia_parcial(tmp_path):
    source, destination = tmp_path / "source.db", tmp_path / "backup.db"
    with closing(sqlite3.connect(source)) as db:
        db.execute("CREATE TABLE example (value TEXT)")
    with pytest.raises(TimeoutError):
        deployment.backup_database(source, destination, timeout=0)
    assert not destination.exists()


def test_fingerprint_incluye_revision_y_ddl_pero_no_datos(tmp_path):
    path = tmp_path / "source.db"
    with closing(sqlite3.connect(path)) as db:
        db.execute("CREATE TABLE example (value TEXT)")
        before = deployment.fingerprint(path)
        db.execute("INSERT INTO example VALUES ('valor')")
        db.commit()
        assert before == deployment.fingerprint(path)
        db.execute("ALTER TABLE example ADD COLUMN extra TEXT")
        assert before != deployment.fingerprint(path)
        db.execute("CREATE TABLE alembic_version (version_num TEXT)")
        db.execute("INSERT INTO alembic_version VALUES ('primera')")
        db.commit()
        before = deployment.fingerprint(path)
        db.execute("UPDATE alembic_version SET version_num='segunda'")
        db.commit()
        assert before != deployment.fingerprint(path)


@pytest.mark.parametrize(
    "line",
    [
        "DASHBOARD_DB_FILE=/otro.db",
        "DASHBOARD_SCHEDULER_ENABLED=true",
        "export DASHBOARD_REGIME_ENABLED=true",
        "DASHBOARD_REGIME_FRED_KEY=valor\\",
        "ACS_CONNECTION_STRING=secreto",
    ],
)
def test_environment_rechaza_redirecciones_sin_publicar_valores(tmp_path, line):
    path = tmp_path / "market-regime.env"
    path.write_text(line)
    path.chmod(0o600)
    with pytest.raises(ValueError) as error:
        deployment.validate_environment(path)
    assert "secreto" not in str(error.value)
    assert "/otro.db" not in str(error.value)


def test_environment_acepta_ausencia_y_claves_del_modulo(tmp_path):
    path = tmp_path / "market-regime.env"
    deployment.validate_environment(path)
    path.write_text("# comentario\nDASHBOARD_REGIME_ENABLED=false\n")
    path.chmod(0o600)
    if os.name == "posix" and os.getuid() != 0:
        with pytest.raises(ValueError, match="root"):
            deployment.validate_environment(path)
    else:
        deployment.validate_environment(path)


def test_preflight_desactiva_y_restaura_entorno_incluso_con_error(monkeypatch):
    monkeypatch.setenv("DASHBOARD_REGIME_ENABLED", "true")
    monkeypatch.setenv("DASHBOARD_REGIME_FRED_KEY", "clave-sintetica")
    monkeypatch.setenv("DASHBOARD_DB_FILE", "produccion.db")
    with pytest.raises(RuntimeError):
        with deployment.offline_environment():
            assert os.environ["DASHBOARD_REGIME_ENABLED"] == "false"
            assert os.environ["DASHBOARD_REGIME_DELIVERIES_ENABLED"] == "false"
            assert "DASHBOARD_REGIME_FRED_KEY" not in os.environ
            assert "DASHBOARD_DB_FILE" not in os.environ
            raise RuntimeError("interrumpido")
    assert os.environ["DASHBOARD_REGIME_ENABLED"] == "true"
    assert os.environ["DASHBOARD_REGIME_FRED_KEY"] == "clave-sintetica"
    assert os.environ["DASHBOARD_DB_FILE"] == "produccion.db"


def test_runtime_confirma_db_efectiva_sin_exponer_secretos(tmp_path):
    db = tmp_path / "dashboard.db"
    environ = b"DASHBOARD_DB_FILE=" + os.fsencode(db) + b"\0SECRET=oculto\0"
    deployment.validate_runtime_environment(environ, db)
    with pytest.raises(ValueError) as error:
        deployment.validate_runtime_environment(environ, tmp_path / "otra.db")
    assert "oculto" not in str(error.value)
    with pytest.raises(ValueError):
        deployment.validate_runtime_environment(b"SECRET=oculto\0", db)


def test_preflight_migra_copia_y_prueba_api_sin_red(tmp_path, monkeypatch):
    source = tmp_path / "original.db"
    engine = create_db_engine(source)
    try:
        with engine.begin() as connection:
            config = alembic_config()
            config.attributes["connection"] = connection
            command.upgrade(config, "3871b415f74d")
    finally:
        engine.dispose()
    before = deployment.fingerprint(source)
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>SPA de prueba</html>")

    def no_network(*_args, **_kwargs):
        pytest.fail("El preflight no debe abrir conexiones externas")

    monkeypatch.setattr(socket, "create_connection", no_network)
    work = tmp_path / "preflight"
    deployment.preflight(source, work, dist, require_regime=False)
    assert deployment.fingerprint(source) == before
    assert current_revision(load_settings(db_path=source)) == "3871b415f74d"
    assert current_revision(load_settings(db_path=work / "dashboard.db")) == head_revision()
    assert (work / "data").is_dir()


@pytest.mark.skipif(os.name != "posix", reason="Contrato Bash/Linux del instalador")
@pytest.mark.parametrize("record_matches", [True, False])
@pytest.mark.parametrize("active", [True, False])
def test_recovery_exige_configuracion_registrada(tmp_path, record_matches, active):
    import hashlib

    release = tmp_path / "release"
    release.mkdir()
    (tmp_path / "current").symlink_to(release, target_is_directory=True)
    unit_hash = hashlib.sha256(b"[Service]\n").hexdigest()
    if not record_matches:
        unit_hash = "configuracion-distinta"
    (tmp_path / "recovery-required").write_text(
        f"{tmp_path / 'dashboard.db'}\n{release}\n{unit_hash}\n"
    )
    source = DEPLOY.read_text()
    guard = "was_active=0\n" + source.split("was_active=0\n", 1)[1].split('work="$(mktemp', 1)[0]
    shell = textwrap.dedent(
        f"""
        set -eu
        base="$1"; db="$base/dashboard.db"; current="$base/current"
        recovery_marker="$base/recovery-required"; service=dashboard; recover=1
        systemctl() {{
          case "$1" in
            is-active) return {0 if active else 1} ;;
            show) echo inactive ;;
            cat) echo '[Service]' ;;
          esac
        }}
        """
    )
    result = subprocess.run(
        ["bash", "-c", shell + guard + '\ntest "$was_active" = 0\n', "test", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert (result.returncode == 0) is (record_matches and not active), result.stderr


@pytest.mark.skipif(os.name != "posix", reason="Contrato Bash/Linux del instalador")
def test_primera_instalacion_no_inventa_release_previo(tmp_path):
    source = DEPLOY.read_text()
    guard = source[source.index('previous=""\n') : source.index('work="$(mktemp')]
    result = subprocess.run(
        [
            "bash",
            "-c",
            'set -eu; current="$1/current"\n' + guard + '\ntest -z "$previous"\n',
            "test",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(os.name != "posix", reason="Contrato Bash/Linux del instalador")
@pytest.mark.parametrize(
    ("migration_started", "migration_needed", "recover", "keep_candidate"),
    [(0, 1, 0, False), (1, 0, 0, False), (1, 1, 0, True), (1, 0, 1, True)],
)
def test_rollback_conserva_datos_y_no_restaura_codigo_incompatible(
    tmp_path, migration_started, migration_needed, recover, keep_candidate
):
    release = tmp_path / "candidate"
    release.mkdir()
    current = tmp_path / "current"
    current.symlink_to(release, target_is_directory=True)
    backup = tmp_path / "backup"
    backup.mkdir()
    (backup / "unit").write_text("unit anterior")
    (tmp_path / "unit").write_text("unit candidato")
    (tmp_path / "dashboard.db").write_text("datos que no se pueden perder")
    source = DEPLOY.read_text()
    rollback = (
        "rollback() {\n"
        + source.split("rollback() {\n", 1)[1].split("trap 'rollback $?' ERR", 1)[0]
    )
    # Ejecutar el rollback real con systemctl simulado, sin tocar servicios.
    setup = textwrap.dedent(
        f"""
        set -eu
        base="$1"; current="$base/current"; backup="$base/backup"
        unit="$base/unit"; release="$base/candidate"; service=dashboard
        recovery_marker="$base/recovery-required"; previous=""
        migration_started={migration_started}; migration_needed={migration_needed}
        recover={recover}; switched=1; stopped=1; was_active=1; caddy_changed=0
        systemctl() {{ printf '%s\\n' "$*" >> "$base/systemctl.log"; }}
        """
    )
    result = subprocess.run(
        ["bash", "-c", setup + rollback + "\nrollback 42\n", "test", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 42, result.stderr
    assert (tmp_path / "dashboard.db").read_text() == "datos que no se pueden perder"
    if keep_candidate:
        assert current.resolve() == release
        assert (tmp_path / "unit").read_text() == "unit candidato"
        assert "start dashboard" not in (tmp_path / "systemctl.log").read_text()
    else:
        assert not current.is_symlink()
        assert (tmp_path / "unit").read_text() == "unit anterior"
        assert "start dashboard" in (tmp_path / "systemctl.log").read_text()
