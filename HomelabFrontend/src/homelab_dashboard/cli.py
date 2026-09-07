"""Punto de entrada CLI del dashboard.

Subcomandos:

    homelab-dashboard serve         arranca uvicorn (comportamiento por defecto)
    homelab-dashboard migrate       aplica las migraciones pendientes
    homelab-dashboard create-admin  crea o promueve al primer administrador
    homelab-dashboard openapi       vuelca el esquema OpenAPI de la API

Invocarlo sin argumentos equivale a `serve`, para no romper el
`ExecStart=.../homelab-dashboard` que ya está desplegado en la VM.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

from .settings import load_settings


def _cmd_serve(_args: argparse.Namespace) -> int:
    import uvicorn

    from .app import create_app

    host = os.environ.get("DASHBOARD_HOST", "127.0.0.1")
    port = int(os.environ.get("DASHBOARD_PORT", "8000"))
    uvicorn.run(create_app(), host=host, port=port)
    return 0


def _cmd_migrate(_args: argparse.Namespace) -> int:
    from .migrate import current_revision, head_revision, upgrade_to_head

    settings = load_settings()
    antes = current_revision(settings)
    upgrade_to_head(settings)
    despues = current_revision(settings)

    if antes == despues:
        print(f"La base ya estaba al día (revisión {despues}).")
    else:
        print(f"Base migrada: {antes or 'sin migrar'} -> {despues}")
    print(f"Archivo: {settings.db_path}")
    if despues != head_revision():  # pragma: no cover - defensivo
        print("AVISO: la revisión aplicada no coincide con la última disponible.", file=sys.stderr)
        return 1
    return 0


def _pedir_password() -> str:
    """Lee la contraseña de forma interactiva, nunca de la línea de comandos.

    Pasarla como argumento la dejaría en el historial del shell y en la lista
    de procesos de la máquina, así que no se ofrece esa opción. Para
    automatización se admite la variable `DASHBOARD_ADMIN_PASSWORD`.
    """
    desde_entorno = os.environ.get("DASHBOARD_ADMIN_PASSWORD", "")
    if desde_entorno:
        return desde_entorno
    primera = getpass.getpass("Contraseña: ")
    segunda = getpass.getpass("Repite la contraseña: ")
    if primera != segunda:
        raise SystemExit("Las contraseñas no coinciden.")
    return primera


def _cmd_create_admin(args: argparse.Namespace) -> int:
    from . import auth
    from .db import create_db_engine, make_session_factory
    from .migrate import upgrade_to_head
    from .models import ROLE_ADMIN, USER_ACTIVE

    settings = load_settings()
    settings.ensure_directories()
    upgrade_to_head(settings)

    factory = make_session_factory(create_db_engine(settings.db_path))
    with factory() as db:
        existente = auth.buscar_por_email(db, args.email)

        if existente is not None and not args.promote:
            print(
                f"Ya existe una cuenta con el correo {existente.email}.\n"
                "Usa --promote para convertirla en administrador activo "
                "y asignarle una contraseña nueva.",
                file=sys.stderr,
            )
            return 1

        password = _pedir_password()

        try:
            if existente is not None:
                auth.cambiar_password(
                    db,
                    usuario=existente,
                    password_actual=None,
                    password_nueva=password,
                    exigir_actual=False,
                )
                existente.role = ROLE_ADMIN
                existente.status = USER_ACTIVE
                # Promover cambia las credenciales: fuera las sesiones vivas.
                auth.revocar_sesiones_de(db, existente.id)
                usuario = existente
                accion = "promovido a administrador"
            else:
                usuario = auth.crear_usuario(
                    db,
                    email=args.email,
                    password=password,
                    role=ROLE_ADMIN,
                    status=USER_ACTIVE,
                    timezone=args.timezone or settings.default_timezone,
                )
                accion = "creado"
        except auth.ErrorDeAuth as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

        db.commit()
        print(f"Administrador {accion}: {usuario.email}")
        print(f"Base de datos: {settings.db_path}")
    return 0


def _cmd_openapi(args: argparse.Namespace) -> int:
    """Vuelca el esquema OpenAPI sin levantar el servidor.

    El frontend genera sus tipos TypeScript de aquí, así que el contrato no se
    teclea dos veces. La app se construye contra un directorio de datos
    temporal: pedir el esquema no debe depender de que haya una base ya
    migrada, ni tocar la de producción.
    """
    import json
    import tempfile

    from .app import create_app

    with tempfile.TemporaryDirectory(prefix="homelab-openapi-") as tmp:
        entorno = dict(os.environ)
        os.environ["DASHBOARD_DATA_DIR"] = str(Path(tmp) / "data")
        os.environ["DASHBOARD_DB_FILE"] = str(Path(tmp) / "data" / "dashboard.db")
        os.environ["DASHBOARD_LOGS_DIR"] = str(Path(tmp) / "logs")
        os.environ["DASHBOARD_SCHEDULER_ENABLED"] = "false"
        os.environ["DASHBOARD_REGIME_DELIVERIES_ENABLED"] = "false"
        app = None
        try:
            app = create_app()
            esquema = app.openapi()
        finally:
            # Sin esto el pool de SQLAlchemy deja abierto el archivo SQLite y
            # el borrado del temporal falla en Windows, que no permite eliminar
            # archivos en uso.
            if app is not None:
                app.state.db_engine.dispose()
            os.environ.clear()
            os.environ.update(entorno)

    texto = json.dumps(esquema, indent=2, ensure_ascii=False, sort_keys=True) + "\n"

    if args.output and args.output != "-":
        destino = Path(args.output)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(texto, encoding="utf-8")
        print(f"Esquema OpenAPI escrito en {destino}")
    else:
        sys.stdout.write(texto)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="homelab-dashboard",
        description="Panel de control multiusuario para las apps de la homelab.",
    )
    sub = parser.add_subparsers(dest="command")

    serve = sub.add_parser("serve", help="arranca el servidor web")
    serve.set_defaults(func=_cmd_serve)

    migrate = sub.add_parser("migrate", help="aplica las migraciones pendientes")
    migrate.set_defaults(func=_cmd_migrate)

    admin = sub.add_parser(
        "create-admin",
        help="crea el primer administrador (la contraseña se pide por consola)",
    )
    admin.add_argument("--email", required=True, help="correo del administrador")
    admin.add_argument(
        "--timezone",
        default=None,
        help="zona horaria IANA, p. ej. America/Bogota",
    )
    admin.add_argument(
        "--promote",
        action="store_true",
        help="si el correo ya existe, promoverlo a admin y cambiarle la contraseña",
    )
    admin.set_defaults(func=_cmd_create_admin)

    openapi = sub.add_parser(
        "openapi",
        help="vuelca el esquema OpenAPI (para generar los tipos del frontend)",
    )
    openapi.add_argument(
        "-o",
        "--output",
        default="-",
        help="archivo destino; '-' escribe por salida estándar",
    )
    openapi.set_defaults(func=_cmd_openapi)

    from .market_regime.cli import configure_parser

    configure_parser(
        sub.add_parser("market-regime", help="regimen de mercado sin ejecutar ordenes")
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        return _cmd_serve(args)
    return func(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
