"""Ejecución programática de las migraciones de Alembic.

En producción no se invoca el binario `alembic`: `homelab-dashboard migrate`
llama a estas funciones. Así el despliegue no depende de que el directorio de
trabajo contenga `alembic.ini` ni de que `script_location` sea una ruta
relativa al repo — las migraciones viajan dentro del paquete instalado.

Se pasa una conexión ya abierta vía `config.attributes`, en vez de una URL,
para no tener que escapar rutas dentro del ConfigParser de Alembic y para que
todo el `upgrade` ocurra en una sola transacción sobre la misma SQLite.
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

from .db import create_db_engine
from .settings import Settings

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def alembic_config() -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    return config


def upgrade_to_head(settings: Settings) -> None:
    """Lleva la base al último esquema, creándola si no existe."""
    settings.ensure_directories()
    engine = create_db_engine(settings.db_path)
    try:
        config = alembic_config()
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
    finally:
        engine.dispose()


def current_revision(settings: Settings) -> str | None:
    """Revisión aplicada actualmente, o None si la base está sin migrar."""
    engine = create_db_engine(settings.db_path)
    try:
        with engine.connect() as connection:
            return MigrationContext.configure(connection).get_current_revision()
    finally:
        engine.dispose()


def head_revision() -> str | None:
    """Última revisión disponible en el código."""
    return ScriptDirectory.from_config(alembic_config()).get_current_head()


def is_up_to_date(settings: Settings) -> bool:
    return current_revision(settings) == head_revision()
