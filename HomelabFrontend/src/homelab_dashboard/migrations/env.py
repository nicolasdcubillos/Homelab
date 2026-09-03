"""Entorno de Alembic.

La URL de la base se toma de la configuración de la aplicación, no de
`alembic.ini`, para que `alembic upgrade head` y el servidor apunten siempre al
mismo archivo aunque se haya cambiado `DASHBOARD_DATA_DIR` en el systemd.

`render_as_batch=True` es obligatorio en SQLite: no soporta `ALTER TABLE ...
ALTER COLUMN`, así que Alembic tiene que recrear la tabla y copiar los datos.
"""

from __future__ import annotations

from alembic import context
from sqlalchemy import engine_from_config, pool

from homelab_dashboard import models  # noqa: F401  (registra las tablas en Base)
from homelab_dashboard.db import Base
from homelab_dashboard.settings import load_settings

config = context.config
target_metadata = Base.metadata


def _database_url() -> str:
    # Permite forzar la URL desde fuera (los tests migran sobre un tmp_path).
    configured = config.get_main_option("sqlalchemy.url", None)
    if configured:
        return configured
    return load_settings().database_url


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # Si quien invoca ya nos pasó una conexión (caso del CLI programático), se
    # reutiliza en vez de abrir una segunda conexión a la misma SQLite.
    connection = config.attributes.get("connection", None)
    if connection is not None:
        _run(connection)
        return

    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as conn:
        _run(conn)


def _run(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
