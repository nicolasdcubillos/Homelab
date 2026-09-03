"""Configuración de proceso del dashboard, leída del entorno.

Un único objeto `Settings` centraliza rutas y parámetros operativos para que
ni las rutas de la API ni el scheduler tengan que leer `os.environ` por su
cuenta (lo que haría imposible testearlos con directorios temporales).

Notas de diseño:

- No hay ninguna "secret key" de aplicación. Los tokens de sesión son valores
  aleatorios de 256 bits de los que solo se guarda el hash SHA-256 en la base,
  y el token CSRF vive en la propia fila de sesión. Así no hay ningún secreto
  que rotar, versionar ni filtrar por accidente.
- Se conservan las variables `DASHBOARD_DB_FILE` y `DASHBOARD_LOGS_DIR` que ya
  usa el systemd desplegado, para que una actualización no rompa la VM.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_TIMEZONE = "America/Bogota"


def _env_str(name: str, default: str) -> str:
    value = os.environ.get(name, "").strip()
    return value or default


def _env_int(name: str, default: int, *, minimum: int = 1) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"{name} debe ser un entero, se recibió {raw!r}") from None
    if value < minimum:
        raise ValueError(f"{name} debe ser >= {minimum}, se recibió {value}")
    return value


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} debe ser booleano (true/false), se recibió {raw!r}")


@dataclass(frozen=True)
class Settings:
    """Parámetros de ejecución resueltos una sola vez por proceso."""

    apps_file: Path
    data_dir: Path
    db_path: Path
    logs_dir: Path
    frontend_dist: Path

    secure_cookies: bool
    session_ttl_hours: int

    login_max_attempts: int
    login_window_minutes: int
    login_lockout_minutes: int

    scheduler_enabled: bool
    scheduler_tick_seconds: int
    max_concurrent_jobs: int
    default_timezone: str

    @property
    def users_dir(self) -> Path:
        """Raíz de los workspaces por usuario (`<data_dir>/users`)."""
        return self.data_dir / "users"

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.db_path}"

    def ensure_directories(self) -> None:
        """Crea los directorios que el dashboard necesita para escribir.

        `users_dir` se crea con permisos restrictivos porque debajo cuelgan las
        configuraciones y el estado de cada usuario, que no deben ser legibles
        por otras cuentas de la máquina.
        """
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.users_dir.mkdir(parents=True, exist_ok=True)
        self.users_dir.chmod(0o700)


def load_settings(**overrides) -> Settings:
    """Construye `Settings` desde el entorno, aceptando overrides explícitos.

    Los overrides existen para los tests, que necesitan apuntar todo a un
    `tmp_path` sin ensuciar el entorno del proceso de pytest.
    """
    data_dir = Path(_env_str("DASHBOARD_DATA_DIR", "data")).expanduser()

    # `DASHBOARD_DB_FILE` ya existe en el systemd desplegado; si está definida
    # manda sobre la ubicación derivada de `data_dir`.
    db_file = os.environ.get("DASHBOARD_DB_FILE", "").strip()
    db_path = Path(db_file).expanduser() if db_file else data_dir / "dashboard.db"

    settings = Settings(
        apps_file=Path(_env_str("DASHBOARD_APPS_FILE", "apps.yaml")).expanduser(),
        data_dir=data_dir,
        db_path=db_path,
        logs_dir=Path(_env_str("DASHBOARD_LOGS_DIR", "logs")).expanduser(),
        frontend_dist=Path(_env_str("DASHBOARD_FRONTEND_DIST", "frontend/dist")).expanduser(),
        secure_cookies=_env_bool("DASHBOARD_SECURE_COOKIES", True),
        session_ttl_hours=_env_int("DASHBOARD_SESSION_TTL_HOURS", 720),
        login_max_attempts=_env_int("DASHBOARD_LOGIN_MAX_ATTEMPTS", 5),
        login_window_minutes=_env_int("DASHBOARD_LOGIN_WINDOW_MINUTES", 15),
        login_lockout_minutes=_env_int("DASHBOARD_LOGIN_LOCKOUT_MINUTES", 15),
        scheduler_enabled=_env_bool("DASHBOARD_SCHEDULER_ENABLED", True),
        scheduler_tick_seconds=_env_int("DASHBOARD_SCHEDULER_TICK_SECONDS", 30),
        max_concurrent_jobs=_env_int("DASHBOARD_MAX_CONCURRENT_JOBS", 4),
        default_timezone=_env_str("DASHBOARD_DEFAULT_TIMEZONE", DEFAULT_TIMEZONE),
    )

    if overrides:
        from dataclasses import replace

        settings = replace(settings, **overrides)
    return settings
