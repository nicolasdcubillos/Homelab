"""Workspaces aislados por usuario.

Cada usuario tiene un árbol propio bajo `<data_dir>/users/<user_id>/` donde el
dashboard escribe la configuración generada y donde cada watcher guarda su
estado. El aislamiento del estado no es una optimización: ambos watchers
deduplican contra su base (`is_seen`, transiciones de stock), así que un estado
compartido haría que el segundo usuario no recibiera nunca su alerta.

Los `config/*.yaml` de los repos administrados **nunca** se tocan.
"""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .settings import Settings

#: Los ids de usuario son uuid4 sin guiones. Se valida antes de componer
#: cualquier ruta para que un id manipulado no pueda salirse del árbol.
_RE_USER_ID = re.compile(r"^[0-9a-f]{32}$")


class WorkspaceError(Exception):
    """Error al preparar o resolver el workspace de un usuario."""


def validar_user_id(user_id: str) -> str:
    if not isinstance(user_id, str) or not _RE_USER_ID.match(user_id):
        raise WorkspaceError(f"Identificador de usuario inválido: {user_id!r}")
    return user_id


def _validar_app(app_name: str) -> str:
    """Un nombre de app solo puede ser un segmento simple de ruta."""
    if not app_name or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", app_name):
        raise WorkspaceError(f"Nombre de app inválido: {app_name!r}")
    return app_name


@dataclass(frozen=True)
class UserWorkspace:
    """Rutas del workspace de un usuario. Todas se validan al construirse."""

    user_id: str
    raiz: Path

    @classmethod
    def para(cls, settings: Settings, user_id: str) -> UserWorkspace:
        validar_user_id(user_id)
        raiz = (settings.users_dir / user_id).resolve()
        # Segunda barrera: aunque `users_dir` sea un enlace simbólico raro, la
        # ruta resuelta tiene que seguir colgando de la raíz de usuarios.
        base = settings.users_dir.resolve()
        if raiz != base / user_id:
            raise WorkspaceError("La ruta del workspace se sale del árbol de usuarios.")
        return cls(user_id=user_id, raiz=raiz)

    # -- rutas -------------------------------------------------------------

    def dir_app(self, app_name: str) -> Path:
        return self.raiz / _validar_app(app_name)

    def dir_config(self, app_name: str) -> Path:
        return self.dir_app(app_name) / "config"

    def dir_estado(self, app_name: str) -> Path:
        return self.dir_app(app_name) / "state"

    def ruta_config(self, app_name: str, nombre_archivo: str) -> Path:
        if "/" in nombre_archivo or "\\" in nombre_archivo or nombre_archivo.startswith("."):
            raise WorkspaceError(f"Nombre de archivo inválido: {nombre_archivo!r}")
        destino = (self.dir_config(app_name) / nombre_archivo).resolve()
        self._exigir_dentro(destino)
        return destino

    def ruta_estado(self, app_name: str, nombre_archivo: str) -> Path:
        if "/" in nombre_archivo or "\\" in nombre_archivo or nombre_archivo.startswith("."):
            raise WorkspaceError(f"Nombre de archivo inválido: {nombre_archivo!r}")
        destino = (self.dir_estado(app_name) / nombre_archivo).resolve()
        self._exigir_dentro(destino)
        return destino

    def _exigir_dentro(self, ruta: Path) -> None:
        """Misma técnica que `registry.resolve_config_path`, ahora contra la
        raíz del workspace del usuario."""
        try:
            ruta.relative_to(self.raiz)
        except ValueError as exc:
            raise WorkspaceError(
                f"La ruta {ruta} queda fuera del workspace de {self.user_id}."
            ) from exc

    # -- creación ----------------------------------------------------------

    def preparar(self, app_name: str) -> None:
        """Crea los directorios de una app con permisos restrictivos."""
        for directorio in (self.dir_config(app_name), self.dir_estado(app_name)):
            directorio.mkdir(parents=True, exist_ok=True)
        for directorio in (self.raiz, self.dir_app(app_name)):
            directorio.chmod(0o700)

    def escribir_config(self, app_name: str, nombre_archivo: str, contenido: str) -> Path:
        """Escribe la config generada de forma atómica.

        Se escribe a un temporal en el mismo directorio y se hace `os.replace`
        para que una corrida concurrente nunca llegue a leer un YAML a medio
        escribir. El archivo queda en 0600: puede contener el número de
        WhatsApp o el correo del usuario.
        """
        self.preparar(app_name)
        destino = self.ruta_config(app_name, nombre_archivo)
        descriptor, temporal = tempfile.mkstemp(
            dir=str(destino.parent), prefix=f".{destino.name}.", suffix=".tmp"
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as fh:
                fh.write(contenido)
            os.chmod(temporal, 0o600)
            os.replace(temporal, destino)
        except BaseException:
            Path(temporal).unlink(missing_ok=True)
            raise
        return destino

    def eliminar(self) -> None:
        """Borra todo el workspace del usuario. Se usa al eliminar la cuenta."""
        import shutil

        if self.raiz.exists():
            shutil.rmtree(self.raiz)
