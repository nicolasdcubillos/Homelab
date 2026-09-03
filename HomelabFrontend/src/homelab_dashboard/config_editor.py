"""Lectura, validación, backup y escritura de archivos de configuración YAML.

Todas las rutas se resuelven y validan a través de `AppDefinition.resolve_config_path`
para evitar path traversal antes de tocar el filesystem.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import yaml

from .registry import AppDefinition, ConfigFile


class ConfigEditorError(ValueError):
    """Error de usuario al leer/validar/escribir un archivo de configuración."""


def _resolve(app: AppDefinition, config_file: ConfigFile) -> Path:
    return app.resolve_config_path(config_file.path)


def read_config(app: AppDefinition, config_file: ConfigFile) -> str:
    """Lee el contenido crudo (texto) de un config_file. Si no existe, "" ."""
    target = _resolve(app, config_file)
    if not target.is_file():
        return ""
    return target.read_text(encoding="utf-8")


def validate_yaml(content: str) -> None:
    """Lanza ConfigEditorError si `content` no es YAML parseable."""
    try:
        yaml.safe_load(content)
    except yaml.YAMLError as exc:
        raise ConfigEditorError(f"YAML inválido: {exc}") from exc


def backup_path_for(target: Path, when: dt.datetime | None = None) -> Path:
    when = when or dt.datetime.now()
    stamp = when.strftime("%Y%m%d-%H%M%S")
    return target.with_name(f"{target.name}.bak.{stamp}")


def write_config(app: AppDefinition, config_file: ConfigFile, content: str) -> Path:
    """Valida `content` como YAML, hace backup del archivo existente (si lo
    hay), y luego escribe el nuevo contenido. Devuelve la ruta escrita.

    Lanza ConfigEditorError si el contenido no es YAML válido. No se toca el
    archivo real hasta que la validación pasa.
    """
    validate_yaml(content)

    target = _resolve(app, config_file)
    target.parent.mkdir(parents=True, exist_ok=True)

    if target.is_file():
        backup = backup_path_for(target)
        backup.write_bytes(target.read_bytes())

    target.write_text(content, encoding="utf-8")
    return target
