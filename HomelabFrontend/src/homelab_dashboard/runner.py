"""Ejecución de watchers por usuario.

Sustituye al `JobManager` original en todo lo multiusuario. Las diferencias
que importan:

- El lock de exclusión es por `(user_id, app_name)`, no por app: que Ana esté
  corriendo StockWatcher no debe impedir que Bruno corra el suyo.
- Cada corrida escribe su configuración en el workspace del usuario y recibe
  sus destinos de notificación por el entorno del subproceso.
- Hay un tope global de procesos simultáneos para no tumbar una VM pequeña.
  Al superarlo la corrida se registra como `skipped` con su motivo, en vez de
  perderse en silencio.
- Los comandos siguen saliendo de `apps.yaml`; nunca se acepta un argumento
  arbitrario del usuario. Lo único que se añade son las rutas generadas y, si
  se pide, `--dry-run`.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config_service, watchers
from .db import utcnow
from .models import (
    JOB_CANCELLED,
    JOB_ERROR,
    JOB_RUNNING,
    JOB_SKIPPED,
    JOB_SUCCESS,
    TRIGGER_MANUAL,
    JobRun,
    User,
)
from .registry import AppDefinition, Command
from .settings import Settings

log = logging.getLogger(__name__)

#: Margen entre el SIGTERM y el SIGKILL al cancelar.
ESPERA_TRAS_SIGTERM = 10.0


class ErrorDeEjecucion(RuntimeError):
    """No se pudo lanzar la corrida."""

    codigo = "error_de_ejecucion"


class YaEstaCorriendo(ErrorDeEjecucion):
    codigo = "ya_esta_corriendo"


class NoEstaListo(ErrorDeEjecucion):
    """Falta configuración; el watcher abortaría con ConfigError."""

    codigo = "no_esta_listo"


class DemasiadosJobs(ErrorDeEjecucion):
    codigo = "demasiados_jobs"


class AppNoDisponible(ErrorDeEjecucion):
    codigo = "app_no_disponible"


@dataclass
class _EnCurso:
    """Un proceso vivo y lo que hace falta para vigilarlo o matarlo."""

    run_id: int
    proc: subprocess.Popen
    user_id: str
    app_name: str
    #: Se marca al cancelar, para no confundir la parada con un fallo.
    cancelado: bool = False


class JobRunner:
    """Lanza, vigila y cancela las corridas de cada usuario."""

    def __init__(
        self,
        settings: Settings,
        session_factory,
        registry_apps: dict[str, AppDefinition] | None = None,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self._apps = registry_apps or {}
        self._guard = threading.Lock()
        self._en_curso: dict[tuple[str, str], _EnCurso] = {}

    # -- registro de apps ---------------------------------------------------

    def set_apps(self, apps: dict[str, AppDefinition]) -> None:
        self._apps = apps

    def app_de(self, app_name: str) -> AppDefinition | None:
        return self._apps.get(app_name)

    # -- consulta -----------------------------------------------------------

    def esta_corriendo(self, user_id: str, app_name: str) -> bool:
        with self._guard:
            return (user_id, app_name) in self._en_curso

    def jobs_activos(self) -> int:
        with self._guard:
            return len(self._en_curso)

    def corriendo_de(self, user_id: str) -> list[str]:
        with self._guard:
            return [app for (uid, app) in self._en_curso if uid == user_id]

    # -- lanzamiento --------------------------------------------------------

    def lanzar(
        self,
        db: Session,
        usuario: User,
        app_name: str,
        command_key: str,
        *,
        dry_run: bool = False,
        trigger: str = TRIGGER_MANUAL,
        schedule_id: str | None = None,
    ) -> JobRun:
        """Lanza una corrida y devuelve su fila de historial.

        La fila se confirma antes de arrancar el proceso, para que una corrida
        nunca quede huérfana si el dashboard muere justo después del `Popen`.
        """
        app = self.app_de(app_name)
        spec = watchers.spec_de(app_name)
        if app is None or spec is None:
            raise AppNoDisponible(f"La aplicación «{app_name}» no está disponible.")
        if not app.is_installed:
            raise AppNoDisponible(
                f"{spec.display_name} no está instalada en este servidor."
            )

        comando = app.command_by_key(command_key)
        if comando is None:
            raise AppNoDisponible("Ese comando no está declarado para la aplicación.")

        estado = config_service.evaluar_readiness(db, usuario, app_name)
        if not estado.listo:
            raise NoEstaListo(estado.motivo)

        clave = (usuario.id, app_name)
        with self._guard:
            if clave in self._en_curso:
                raise YaEstaCorriendo(
                    f"Ya tienes una ejecución de {spec.display_name} en curso."
                )
            if len(self._en_curso) >= self.settings.max_concurrent_jobs:
                raise DemasiadosJobs(
                    "El servidor está ocupado ahora mismo. Inténtalo en unos minutos."
                )
            # Se reserva el hueco antes de soltar el lock; el placeholder se
            # sustituye por el proceso real más abajo.
            self._en_curso[clave] = _EnCurso(0, None, usuario.id, app_name)  # type: ignore[arg-type]  # noqa: E501

        try:
            return self._arrancar(
                db, usuario, app, spec, comando, dry_run, trigger, schedule_id
            )
        except Exception:
            with self._guard:
                self._en_curso.pop(clave, None)
            raise

    def _arrancar(
        self,
        db: Session,
        usuario: User,
        app: AppDefinition,
        spec: watchers.WatcherSpec,
        comando: Command,
        dry_run: bool,
        trigger: str,
        schedule_id: str | None,
    ) -> JobRun:
        plan = config_service.preparar(
            db,
            self.settings,
            usuario,
            spec.app_name,
            stores_path=self._stores_path(app, spec),
        )
        argv = [str(app.executable), *plan.argumentos, *comando.args]
        if dry_run:
            argv = self._con_dry_run(argv, spec, plan.argumentos, comando)

        log_path = self._ruta_de_log(usuario.id, spec.app_name, comando.key)
        run = JobRun(
            user_id=usuario.id,
            app_name=spec.app_name,
            command_key=comando.key,
            command_label=comando.label,
            args_json=json.dumps(comando.args),
            log_path=str(log_path),
            status=JOB_RUNNING,
            trigger=trigger,
            schedule_id=schedule_id,
            started_at=utcnow(),
        )
        db.add(run)
        db.commit()
        db.refresh(run)

        entorno = {**os.environ, **plan.entorno}
        archivo = open(log_path, "ab", buffering=0)
        archivo.write(self._cabecera(spec, comando, dry_run, plan.config_path))
        try:
            proc = subprocess.Popen(
                argv,
                stdout=archivo,
                stderr=subprocess.STDOUT,
                cwd=str(app.base_path),
                env=entorno,
                # Grupo propio: al cancelar se mata también a los hijos que
                # el watcher haya lanzado.
                start_new_session=True,
            )
        except OSError as exc:
            archivo.write(f"\n[panel] No se pudo lanzar el comando: {exc}\n".encode())
            archivo.close()
            self._cerrar(run.id, JOB_ERROR, None, nota=str(exc))
            raise ErrorDeEjecucion(f"No se pudo lanzar el comando: {exc}") from exc

        with self._guard:
            self._en_curso[(usuario.id, spec.app_name)] = _EnCurso(
                run_id=run.id, proc=proc, user_id=usuario.id, app_name=spec.app_name
            )

        threading.Thread(
            target=self._vigilar,
            args=(usuario.id, spec.app_name, run.id, proc, archivo),
            daemon=True,
        ).start()
        return run

    def _con_dry_run(
        self,
        argv: list[str],
        spec: watchers.WatcherSpec,
        generados: list[str],
        comando: Command,
    ) -> list[str]:
        """Inserta `--dry-run` donde cada CLI lo espera.

        PortfolioWatcher lo declara en el parser global y StockWatcher dentro
        del subcomando `run`; ponerlo en el sitio equivocado hace que argparse
        aborte con código 2.
        """
        if spec.dry_run_flag in comando.args:
            return argv
        if spec.dry_run_global:
            return [argv[0], spec.dry_run_flag, *generados, *comando.args]
        return [*argv, spec.dry_run_flag]

    def _stores_path(
        self, app: AppDefinition, spec: watchers.WatcherSpec
    ) -> str | None:
        """Registro de tiendas compartido, en solo lectura.

        Se comparte a propósito (hallazgo 6): si cada usuario tuviera el suyo,
        todos repetirían el mismo descubrimiento contra las mismas tiendas.
        """
        if spec.app_name != watchers.APP_STOCKWATCHER:
            return None
        candidato = app.base_path / "config" / "stores.yaml"
        return str(candidato) if candidato.is_file() else None

    def _cabecera(
        self,
        spec: watchers.WatcherSpec,
        comando: Command,
        dry_run: bool,
        config_path: str,
    ) -> bytes:
        modo = " (prueba, sin enviar)" if dry_run else ""
        return (
            f"[panel] {spec.display_name}: {comando.label}{modo}\n"
            f"[panel] Configuración generada en {config_path}\n"
            f"[panel] Inicio: {utcnow().isoformat()}\n\n"
        ).encode()

    def _ruta_de_log(self, user_id: str, app_name: str, command_key: str) -> Path:
        carpeta = self.settings.logs_dir / user_id / app_name
        carpeta.mkdir(parents=True, exist_ok=True)
        os.chmod(carpeta.parent, 0o700)
        marca = utcnow().strftime("%Y%m%d-%H%M%S")
        return carpeta / f"{marca}_{command_key}.log"

    # -- vigilancia ---------------------------------------------------------

    def _vigilar(
        self,
        user_id: str,
        app_name: str,
        run_id: int,
        proc: subprocess.Popen,
        archivo,
    ) -> None:
        try:
            codigo = proc.wait()
        finally:
            try:
                archivo.close()
            except Exception:  # pragma: no cover - cierre best-effort
                pass
        with self._guard:
            actual = self._en_curso.get((user_id, app_name))
            cancelado = bool(actual and actual.cancelado)
        if cancelado:
            estado, nota = JOB_CANCELLED, "Detenida a petición del usuario."
        elif codigo == 0:
            estado, nota = JOB_SUCCESS, ""
        else:
            estado, nota = JOB_ERROR, ""
        # Solo una corrida completa (código 0) puede tener el JSON final
        # intacto; una cancelada o fallida puede haber cortado el proceso a
        # mitad del `print`, así que ni se intenta leerlo.
        resultado = self._extraer_resultado(archivo.name) if estado == JOB_SUCCESS else None
        try:
            self._cerrar(run_id, estado, codigo, nota=nota, resultado=resultado)
        finally:
            # Se libera el hueco *después* de persistir, para que nadie vea
            # "libre" mientras la fila todavía dice `running`.
            with self._guard:
                self._en_curso.pop((user_id, app_name), None)

    #: Lo que imprime ``stockwatcher run`` justo antes del resumen: ver
    #: ``stockwatcher.cli._cmd_run``. Otros watchers simplemente no lo
    #: imprimen, así que la búsqueda falla en silencio y `resultado` queda
    #: en `None` — no hace falta distinguir por `app_name`.
    _MARCA_RESUMEN = '{\n  "summary"'

    def _extraer_resultado(self, log_path: str) -> str | None:
        """Lee del log el resumen JSON de la corrida, si lo hay.

        Se guarda solo el subconjunto que la SPA pinta (no el resumen
        completo) para no inflar la fila con datos que nadie lee de vuelta.
        """
        if not log_path:
            return None
        ruta = Path(log_path)
        if not ruta.is_file():
            return None
        try:
            texto = ruta.read_text(encoding="utf-8", errors="replace")
        except OSError:  # pragma: no cover - defensivo
            return None
        inicio = texto.find(self._MARCA_RESUMEN)
        if inicio == -1:
            return None
        try:
            payload, _ = json.JSONDecoder().raw_decode(texto[inicio:])
        except (ValueError, TypeError):
            return None
        resumen = payload.get("summary") if isinstance(payload, dict) else None
        if not isinstance(resumen, dict):
            return None
        return json.dumps(
            {
                "new_hits": resumen.get("new_hits", 0),
                "stores_scanned": resumen.get("stores_scanned", 0),
                "stores_failed": resumen.get("stores_failed", 0),
                "hit_details": resumen.get("hit_details") or [],
            }
        )

    def _cerrar(
        self,
        run_id: int,
        estado: str,
        codigo: int | None,
        *,
        nota: str = "",
        resultado: str | None = None,
    ) -> None:
        with self.session_factory() as db:
            run = db.get(JobRun, run_id)
            if run is None:  # pragma: no cover - la fila fue borrada
                return
            fin = utcnow()
            run.finished_at = fin
            run.status = estado
            run.return_code = codigo
            if run.started_at is not None:
                run.duration_seconds = (fin - run.started_at).total_seconds()
            if nota:
                run.skip_reason = nota
            if resultado is not None:
                run.result_json = resultado
            db.commit()

    # -- cancelación --------------------------------------------------------

    def cancelar(self, user_id: str, app_name: str) -> bool:
        """Detiene la corrida en curso. SIGTERM y, si insiste, SIGKILL."""
        with self._guard:
            actual = self._en_curso.get((user_id, app_name))
            if actual is None or actual.proc is None:
                return False
            actual.cancelado = True
            proc = actual.proc

        self._terminar(proc)
        return True

    def _terminar(self, proc: subprocess.Popen) -> None:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            return
        limite = time.monotonic() + ESPERA_TRAS_SIGTERM
        while time.monotonic() < limite:
            if proc.poll() is not None:
                return
            time.sleep(0.1)
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):  # pragma: no cover
            pass

    def cancelar_todo(self) -> None:
        """Para el apagado del servidor."""
        with self._guard:
            procesos = [e.proc for e in self._en_curso.values() if e.proc is not None]
        for proc in procesos:
            self._terminar(proc)

    # -- arranque -----------------------------------------------------------

    def reconciliar_huerfanos(self) -> int:
        """Cierra las corridas que un reinicio dejó marcadas como `running`.

        El proceso murió con el dashboard, así que dejarlas en `running` haría
        que el usuario viera para siempre un job que no existe.
        """
        with self.session_factory() as db:
            colgadas = list(
                db.scalars(select(JobRun).where(JobRun.status == JOB_RUNNING))
            )
            for run in colgadas:
                run.status = JOB_ERROR
                run.finished_at = utcnow()
                run.skip_reason = "Interrumpida porque el panel se reinició."
            db.commit()
            return len(colgadas)

    def registrar_omitida(
        self,
        db: Session,
        usuario: User,
        app_name: str,
        command_key: str,
        motivo: str,
        *,
        trigger: str,
        schedule_id: str | None = None,
    ) -> JobRun:
        """Deja constancia de una corrida que no llegó a lanzarse.

        Sin esto, una ejecución programada que se salta por falta de
        configuración desaparecería sin dejar rastro para el usuario.
        """
        ahora = utcnow()
        run = JobRun(
            user_id=usuario.id,
            app_name=app_name,
            command_key=command_key,
            command_label=command_key,
            args_json="[]",
            log_path="",
            status=JOB_SKIPPED,
            trigger=trigger,
            schedule_id=schedule_id,
            started_at=ahora,
            finished_at=ahora,
            duration_seconds=0.0,
            skip_reason=motivo,
        )
        db.add(run)
        db.commit()
        return run

    # -- logs ---------------------------------------------------------------

    def tail(self, run: JobRun, lineas: int = 200) -> str:
        if not run.log_path:
            return "(esta ejecución no generó log)"
        ruta = Path(run.log_path)
        if not ruta.is_file():
            return "(sin log todavía)"
        with open(ruta, encoding="utf-8", errors="replace") as f:
            contenido = f.readlines()
        return "".join(contenido[-lineas:])
