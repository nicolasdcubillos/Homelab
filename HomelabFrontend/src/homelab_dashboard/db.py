"""Motor SQLAlchemy, fábrica de sesiones y tipos de columna compartidos.

SQLite es suficiente a esta escala (un puñado de usuarios, escrituras
esporádicas), pero necesita tres ajustes que no trae por defecto y que aquí se
aplican en cada conexión:

- `foreign_keys=ON`: SQLite ignora las claves foráneas salvo que se pidan
  explícitamente. Sin esto, borrar un usuario dejaría sus watches huérfanos.
- `journal_mode=WAL`: permite que el scheduler escriba mientras la API lee.
- `busy_timeout`: en vez de fallar al instante con "database is locked",
  espera a que la otra escritura termine.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import DateTime, Engine, TypeDecorator, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """Base declarativa de todos los modelos."""


class UtcDateTime(TypeDecorator):
    """`datetime` siempre consciente de zona horaria y siempre en UTC.

    SQLite no guarda zonas horarias, así que la disciplina la impone este tipo:
    rechaza escribir datetimes ingenuos (un bug silencioso clásico) y devuelve
    siempre datetimes en UTC.

    Al leer también tolera el formato ISO-8601 con `T` y sufijo de zona que
    escribía la versión anterior del dashboard directamente con `sqlite3`, para
    que el historial de ejecuciones previo a la migración siga siendo legible
    aunque quede alguna fila sin convertir.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: dt.datetime | None, dialect) -> dt.datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError(
                "se intentó guardar un datetime sin zona horaria; usa homelab_dashboard.db.utcnow()"
            )
        return value.astimezone(dt.timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value, dialect) -> dt.datetime | None:
        if value is None:
            return None
        if isinstance(value, str):
            value = _parse_legacy_datetime(value)
            if value is None:
                return None
        if value.tzinfo is None:
            return value.replace(tzinfo=dt.timezone.utc)
        return value.astimezone(dt.timezone.utc)


def _parse_legacy_datetime(raw: str) -> dt.datetime | None:
    text = raw.strip()
    if not text:
        return None
    try:
        return dt.datetime.fromisoformat(text)
    except ValueError:
        return None


def utcnow() -> dt.datetime:
    """Ahora, en UTC y con zona horaria explícita."""
    return dt.datetime.now(dt.timezone.utc)


def create_db_engine(db_path: str | Path, *, echo: bool = False) -> Engine:
    """Crea el engine para la base del dashboard, con los PRAGMA necesarios."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine(
        f"sqlite:///{path}",
        echo=echo,
        future=True,
        # El scheduler corre en hilos propios de APScheduler y las rutas
        # síncronas de FastAPI en el threadpool: las conexiones cruzan hilos.
        connect_args={"check_same_thread": False, "timeout": 30},
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record):  # pragma: no cover - trivial
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()

    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """Sesión transaccional: hace commit al salir bien, rollback al fallar."""
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
