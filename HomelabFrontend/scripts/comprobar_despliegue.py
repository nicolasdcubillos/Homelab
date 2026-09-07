"""Preflight aislado y copias consistentes; nunca restaura la base productiva."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sqlite3
import time
from contextlib import closing, contextmanager
from pathlib import Path


def fingerprint(db_path: Path) -> str:
    with closing(sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        schema = db.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name"
        ).fetchall()
        has_version = any(row[1] == "alembic_version" for row in schema)
        versions = (
            db.execute("SELECT version_num FROM alembic_version ORDER BY version_num").fetchall()
            if has_version
            else []
        )
    return hashlib.sha256(json.dumps([schema, versions]).encode()).hexdigest()


def backup_database(source: Path, destination: Path, *, timeout: float = 60) -> None:
    """SQLite backup incluye WAL; O_EXCL evita pisar copias o seguir enlaces."""
    if not source.is_file():
        raise FileNotFoundError(source)
    fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    complete = False
    deadline = time.monotonic() + timeout

    def progress(_status: int, _remaining: int, _total: int) -> None:
        if time.monotonic() >= deadline:
            raise TimeoutError("Se agoto el plazo para copiar SQLite.")

    try:
        with (
            closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as src,
            closing(sqlite3.connect(destination)) as dst,
        ):
            src.backup(dst, pages=256, progress=progress, sleep=0.05)
            if dst.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                raise RuntimeError("La copia SQLite no supero quick_check.")
        complete = True
    finally:
        if not complete:
            destination.unlink(missing_ok=True)


def validate_environment(path: Path) -> None:
    if path.is_symlink():
        raise ValueError("El EnvironmentFile no puede ser un enlace.")
    if not path.exists():
        return
    if not path.is_file():
        raise ValueError("El EnvironmentFile debe ser un archivo regular.")
    stat = path.stat()
    if os.name == "posix" and (stat.st_uid != 0 or stat.st_mode & 0o077):
        raise ValueError("El EnvironmentFile debe pertenecer a root y tener permisos 0600.")
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        # Este archivo no puede redirigir la DB ni reactivar el scheduler global.
        if not re.match(r"^DASHBOARD_REGIME_[A-Z0-9_]+=", line) or line.endswith("\\"):
            raise ValueError(f"Entrada no admitida en EnvironmentFile, linea {number}.")


def validate_runtime_environment(environ: bytes, db_path: Path) -> None:
    entries = dict(item.split(b"=", 1) for item in environ.split(b"\0") if b"=" in item)
    actual = entries.get(b"DASHBOARD_DB_FILE")
    if actual is None or Path(os.fsdecode(actual)).resolve() != db_path.resolve():
        raise ValueError("La DB efectiva del servicio no coincide con la ruta del respaldo.")


@contextmanager
def offline_environment():
    previous = {key: value for key, value in os.environ.items() if key.startswith("DASHBOARD_")}
    for key in previous:
        del os.environ[key]
    os.environ["DASHBOARD_REGIME_ENABLED"] = "false"
    os.environ["DASHBOARD_REGIME_DELIVERIES_ENABLED"] = "false"
    try:
        yield
    finally:
        for key in list(os.environ):
            if key.startswith("DASHBOARD_"):
                del os.environ[key]
        os.environ.update(previous)


def preflight(source: Path, work: Path, dist: Path, *, require_regime: bool) -> None:
    import httpx

    work.mkdir(mode=0o700)
    copy = work / "dashboard.db"
    backup_database(source, copy)
    with offline_environment():
        from homelab_dashboard.app import create_app
        from homelab_dashboard.migrate import upgrade_to_head
        from homelab_dashboard.settings import load_settings

        settings = load_settings(
            db_path=copy,
            data_dir=work / "data",
            logs_dir=work / "logs",
            apps_file=work / "apps.yaml",
            frontend_dist=dist,
            tradinglab_db=work / "tradinglab-no-disponible.db",
            scheduler_enabled=False,
        )
        # No cargar configuraciones de usuarios ni iniciar lifespan/workers.
        settings.apps_file.write_text("apps: []\n", encoding="utf-8")
        upgrade_to_head(settings)
        first = fingerprint(copy)
        upgrade_to_head(settings)
        if first != fingerprint(copy):
            raise RuntimeError("La migracion no es idempotente.")
        app = create_app(settings=settings, run_migrations=False)
        protected = ["/api/v1/auth/me", "/api/v1/trading/bots"]

        async def check() -> None:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="https://preflight.invalid"
            ) as client:
                for path in ("/", "/trading", "/regimen"):
                    response = await client.get(path)
                    if (
                        response.status_code != 200
                        or response.content != (dist / "index.html").read_bytes()
                    ):
                        raise RuntimeError(f"SPA incorrecto en {path}.")
                for path in protected:
                    response = await client.get(path)
                    if response.status_code != 401:
                        raise RuntimeError(f"{path}: se esperaba 401, no {response.status_code}.")

        try:
            if require_regime:
                paths = [
                    path
                    for path, methods in app.openapi()["paths"].items()
                    if path.startswith("/api/v1/market-regime")
                    and "get" in methods
                    and "{" not in path
                ]
                if not paths:
                    raise RuntimeError("Falta registrar la API de regimen de mercado.")
                protected.extend(paths)
            asyncio.run(check())
        finally:
            app.state.db_engine.dispose()
    print("PREFLIGHT_OK: migracion y API sobre copia; sin workers ni envios.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    backup = commands.add_parser("backup")
    backup.add_argument("source", type=Path)
    backup.add_argument("destination", type=Path)
    schema = commands.add_parser("fingerprint")
    schema.add_argument("db", type=Path)
    env = commands.add_parser("environment")
    env.add_argument("path", type=Path)
    runtime = commands.add_parser("runtime")
    runtime.add_argument("--pid", type=int, required=True)
    runtime.add_argument("--db", type=Path, required=True)
    pre = commands.add_parser("preflight")
    pre.add_argument("--db", type=Path, required=True)
    pre.add_argument("--work", type=Path, required=True)
    pre.add_argument("--dist", type=Path, required=True)
    pre.add_argument("--require-regime", action="store_true")
    args = parser.parse_args()
    if args.command == "backup":
        backup_database(args.source, args.destination)
        print("BACKUP_OK")
    elif args.command == "fingerprint":
        print(fingerprint(args.db))
    elif args.command == "environment":
        validate_environment(args.path)
    elif args.command == "runtime":
        if args.pid <= 0:
            raise ValueError("El servicio no tiene un PID activo.")
        validate_runtime_environment(
            (Path("/proc") / str(args.pid) / "environ").read_bytes(), args.db
        )
    else:
        preflight(args.db, args.work, args.dist, require_regime=args.require_regime)


if __name__ == "__main__":
    main()
