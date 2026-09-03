"""Ejecución de comandos en segundo plano, logging a archivo, e historial en SQLite.

Reglas clave:
- Los comandos ejecutados son siempre los que vienen predefinidos en `apps.yaml`
  (ver registry.Command) - nunca se aceptan args arbitrarios del usuario.
- Cada app solo puede tener un job corriendo a la vez (se usa un lock en
  memoria por app + el estado persistido en SQLite para decidir si ya hay uno
  corriendo).
- stdout/stderr del subproceso se redirigen a un archivo de log bajo el
  directorio `logs/` del propio dashboard (nunca dentro del repo de la app
  administrada).
- El historial de ejecuciones se persiste en una tabla SQLite `job_runs` para
  sobrevivir reinicios del dashboard.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

from .registry import AppDefinition, Command

DEFAULT_DB_FILE = "dashboard.db"
DEFAULT_LOGS_DIR = "logs"

STATUS_RUNNING = "running"
STATUS_SUCCESS = "success"
STATUS_ERROR = "error"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS job_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    app_name TEXT NOT NULL,
    command_label TEXT NOT NULL,
    args_json TEXT NOT NULL,
    log_path TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    duration_seconds REAL,
    status TEXT NOT NULL,
    return_code INTEGER
);
"""


@dataclass
class JobRecord:
    id: int
    app_name: str
    command_label: str
    args_json: str
    log_path: str
    started_at: str
    finished_at: str | None
    duration_seconds: float | None
    status: str
    return_code: int | None


class JobAlreadyRunningError(RuntimeError):
    """Se intentó lanzar un job para una app que ya tiene uno corriendo."""


class JobManager:
    """Coordina la ejecución de comandos, sus logs, y su historial en SQLite."""

    def __init__(
        self,
        db_path: str | Path = DEFAULT_DB_FILE,
        logs_dir: str | Path = DEFAULT_LOGS_DIR,
    ):
        self.db_path = Path(db_path)
        self.logs_dir = Path(logs_dir)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()
        self._running_procs: dict[str, subprocess.Popen] = {}
        self._init_db()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _lock_for(self, app_name: str) -> threading.Lock:
        with self._locks_guard:
            if app_name not in self._locks:
                self._locks[app_name] = threading.Lock()
            return self._locks[app_name]

    def is_running(self, app_name: str) -> bool:
        proc = self._running_procs.get(app_name)
        if proc is None:
            return False
        return proc.poll() is None

    def start_job(self, app: AppDefinition, command: Command) -> JobRecord:
        """Lanza `command` para `app` en segundo plano.

        Lanza JobAlreadyRunningError si ya hay un job corriendo para esta app.
        """
        lock = self._lock_for(app.name)
        if not lock.acquire(blocking=False):
            raise JobAlreadyRunningError(f"Ya hay un job corriendo para '{app.name}'")
        try:
            if self.is_running(app.name):
                raise JobAlreadyRunningError(f"Ya hay un job corriendo para '{app.name}'")

            started_at = dt.datetime.now(dt.timezone.utc)
            app_logs_dir = self.logs_dir / app.name
            app_logs_dir.mkdir(parents=True, exist_ok=True)
            stamp = started_at.strftime("%Y%m%d-%H%M%S")
            log_path = app_logs_dir / f"{stamp}_{command.key}.log"

            import json

            args_json = json.dumps(command.args)

            with self._connect() as conn:
                cur = conn.execute(
                    "INSERT INTO job_runs "
                    "(app_name, command_label, args_json, log_path, started_at, status) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        app.name,
                        command.label,
                        args_json,
                        str(log_path),
                        started_at.isoformat(),
                        STATUS_RUNNING,
                    ),
                )
                run_id = cur.lastrowid

            log_file = open(log_path, "ab", buffering=0)
            cmd = [str(app.executable), *command.args]
            try:
                proc = subprocess.Popen(
                    cmd,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    cwd=str(app.base_path),
                )
            except OSError as exc:
                log_file.write(f"\n[dashboard] Error al lanzar el comando: {exc}\n".encode())
                log_file.close()
                self._finish_job(run_id, started_at, STATUS_ERROR, None)
                raise

            self._running_procs[app.name] = proc

            watcher = threading.Thread(
                target=self._watch_job,
                args=(app.name, run_id, proc, started_at, log_file),
                daemon=True,
            )
            watcher.start()

            return self.get_run(run_id)
        finally:
            lock.release()

    def _watch_job(
        self,
        app_name: str,
        run_id: int,
        proc: subprocess.Popen,
        started_at: dt.datetime,
        log_file,
    ) -> None:
        return_code = proc.wait()
        try:
            log_file.close()
        except Exception:
            pass
        status = STATUS_SUCCESS if return_code == 0 else STATUS_ERROR
        self._finish_job(run_id, started_at, status, return_code)
        self._running_procs.pop(app_name, None)

    def _finish_job(
        self,
        run_id: int,
        started_at: dt.datetime,
        status: str,
        return_code: int | None,
    ) -> None:
        finished_at = dt.datetime.now(dt.timezone.utc)
        duration = (finished_at - started_at).total_seconds()
        with self._connect() as conn:
            conn.execute(
                "UPDATE job_runs SET finished_at = ?, duration_seconds = ?, "
                "status = ?, return_code = ? WHERE id = ?",
                (finished_at.isoformat(), duration, status, return_code, run_id),
            )

    def get_run(self, run_id: int) -> JobRecord:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM job_runs WHERE id = ?", (run_id,)).fetchone()
        return _row_to_record(row)

    def last_run(self, app_name: str) -> JobRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM job_runs WHERE app_name = ? ORDER BY id DESC LIMIT 1",
                (app_name,),
            ).fetchone()
        return _row_to_record(row) if row else None

    def history(self, app_name: str, limit: int = 15) -> list[JobRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM job_runs WHERE app_name = ? ORDER BY id DESC LIMIT ?",
                (app_name, limit),
            ).fetchall()
        return [_row_to_record(r) for r in rows]

    def tail_log(self, log_path: str | Path, lines: int = 200) -> str:
        path = Path(log_path)
        if not path.is_file():
            return "(sin log todavía)"
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.readlines()
        return "".join(content[-lines:])


def _row_to_record(row: sqlite3.Row) -> JobRecord:
    return JobRecord(
        id=row["id"],
        app_name=row["app_name"],
        command_label=row["command_label"],
        args_json=row["args_json"],
        log_path=row["log_path"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        duration_seconds=row["duration_seconds"],
        status=row["status"],
        return_code=row["return_code"],
    )
