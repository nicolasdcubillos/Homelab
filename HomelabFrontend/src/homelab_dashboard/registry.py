"""Carga y validación del archivo de registro declarativo `apps.yaml`.

El archivo `apps.yaml` describe qué apps administra el dashboard: dónde viven
en el filesystem, qué archivos de configuración son editables, y qué comandos
predefinidos se pueden disparar. Nunca se aceptan comandos arbitrarios del
usuario: solo los que están declarados aquí.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEFAULT_APPS_FILE = "apps.yaml"


class RegistryError(ValueError):
    """Error al cargar o validar `apps.yaml`."""


@dataclass(frozen=True)
class ConfigFile:
    label: str
    path: str  # relative to the app's base path
    type: str = "yaml"


@dataclass(frozen=True)
class Command:
    label: str
    args: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        """Identificador estable y determinístico para este comando."""
        return "-".join(["cmd", *[a.strip("-") or "x" for a in self.args]]) or "cmd"


@dataclass(frozen=True)
class AppDefinition:
    name: str
    display_name: str
    path: str
    venv_bin: str
    entrypoint: str
    config_files: list[ConfigFile] = field(default_factory=list)
    commands: list[Command] = field(default_factory=list)

    @property
    def base_path(self) -> Path:
        return Path(self.path)

    @property
    def is_installed(self) -> bool:
        return self.base_path.is_dir()

    @property
    def executable(self) -> Path:
        return Path(self.venv_bin) / self.entrypoint

    def command_by_key(self, key: str) -> Command | None:
        for cmd in self.commands:
            if cmd.key == key:
                return cmd
        return None

    def config_file_by_path(self, rel_path: str) -> ConfigFile | None:
        for cf in self.config_files:
            if cf.path == rel_path:
                return cf
        return None

    def resolve_config_path(self, rel_path: str) -> Path:
        """Resuelve `rel_path` dentro de `base_path`, bloqueando path traversal.

        Lanza ValueError si el resultado escapa del directorio base.
        """
        base = self.base_path.resolve()
        candidate = (base / rel_path).resolve()
        try:
            candidate.relative_to(base)
        except ValueError as exc:
            raise ValueError(
                f"Ruta '{rel_path}' se sale del directorio base de la app '{self.name}'"
            ) from exc
        return candidate


def _require_str(d: dict, key: str, ctx: str) -> str:
    value = d.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RegistryError(f"'{key}' es requerido y debe ser texto no vacío en {ctx}")
    return value


def _parse_config_file(raw: dict, ctx: str) -> ConfigFile:
    if not isinstance(raw, dict):
        raise RegistryError(f"config_file inválido en {ctx}: {raw!r}")
    label = _require_str(raw, "label", ctx)
    path = _require_str(raw, "path", ctx)
    if path.startswith("/") or ".." in Path(path).parts:
        raise RegistryError(f"config_file.path no puede ser absoluto ni contener '..' en {ctx}")
    ftype = raw.get("type", "yaml")
    return ConfigFile(label=label, path=path, type=ftype)


def _parse_command(raw: dict, ctx: str) -> Command:
    if not isinstance(raw, dict):
        raise RegistryError(f"command inválido en {ctx}: {raw!r}")
    label = _require_str(raw, "label", ctx)
    args = raw.get("args", [])
    if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
        raise RegistryError(f"command.args debe ser una lista de strings en {ctx}")
    return Command(label=label, args=list(args))


def _parse_app(raw: dict) -> AppDefinition:
    if not isinstance(raw, dict):
        raise RegistryError(f"Entrada de app inválida: {raw!r}")
    name = _require_str(raw, "name", "app")
    ctx = f"app '{name}'"
    display_name = _require_str(raw, "display_name", ctx)
    path = _require_str(raw, "path", ctx)
    venv_bin = _require_str(raw, "venv_bin", ctx)
    entrypoint = _require_str(raw, "entrypoint", ctx)

    config_files_raw = raw.get("config_files", []) or []
    if not isinstance(config_files_raw, list):
        raise RegistryError(f"config_files debe ser una lista en {ctx}")
    config_files = [_parse_config_file(cf, ctx) for cf in config_files_raw]

    commands_raw = raw.get("commands", []) or []
    if not isinstance(commands_raw, list):
        raise RegistryError(f"commands debe ser una lista en {ctx}")
    commands = [_parse_command(c, ctx) for c in commands_raw]

    return AppDefinition(
        name=name,
        display_name=display_name,
        path=path,
        venv_bin=venv_bin,
        entrypoint=entrypoint,
        config_files=config_files,
        commands=commands,
    )


def load_registry(apps_file: str | os.PathLike | None = None) -> list[AppDefinition]:
    """Carga y valida `apps.yaml`, devolviendo la lista de `AppDefinition`.

    Lanza `RegistryError` si el archivo no existe, no es YAML válido, o su
    esquema no cumple lo esperado (evita que la app arranque con un registro
    corrupto en vez de fallar silenciosamente después).
    """
    path = Path(apps_file or os.environ.get("DASHBOARD_APPS_FILE", DEFAULT_APPS_FILE))
    if not path.is_file():
        raise RegistryError(
            f"No se encontró el archivo de registro '{path}'. "
            "Copia apps.yaml.example a apps.yaml y ajústalo."
        )
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise RegistryError(f"'{path}' no es YAML válido: {exc}") from exc

    if not isinstance(data, dict) or "apps" not in data:
        raise RegistryError(f"'{path}' debe tener una clave raíz 'apps' con una lista de apps")

    apps_raw = data["apps"]
    if not isinstance(apps_raw, list):
        raise RegistryError("'apps' debe ser una lista")

    apps = [_parse_app(a) for a in apps_raw]

    names = [a.name for a in apps]
    if len(names) != len(set(names)):
        dupes = {n for n in names if names.count(n) > 1}
        raise RegistryError(f"Nombres de app duplicados en apps.yaml: {dupes}")

    return apps
