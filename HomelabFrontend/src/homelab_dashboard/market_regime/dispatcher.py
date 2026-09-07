"""Cola durable, reclamo CAS y un worker; el scheduler central solo llama tick."""

from __future__ import annotations

import datetime as dt
import logging
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor

from sqlalchemy import and_, exists, or_, select, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import aliased

from ..db import utcnow
from .calendar import NY, CalendarUnavailable, due_week, session_close
from .models import RegimeConfig, RegimeOutbox, RegimeRun, new_id

log = logging.getLogger(__name__)
LEASE_SECONDS = 180
HEARTBEAT_SECONDS = 30
MAX_ATTEMPTS = 3


class RegimeDispatcher:
    """Los flags del módulo habilitan automatización, no bloquean la cola manual autorizada."""

    def __init__(self, settings, session_factory, execute: Callable[[str, int], None]) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.execute = execute
        self._executor: ThreadPoolExecutor | None = None
        self._future: Future | None = None
        self._lock = threading.Lock()
        self._closed = False

    def start(self) -> None:
        with self._lock:
            if self._executor is None and not self._closed:
                self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="regime")

    def shutdown(self, wait: bool = True) -> None:
        with self._lock:
            self._closed = True
            executor = self._executor
            self._executor = None
        if executor is not None:
            executor.shutdown(wait=wait)

    def _enqueue(self, db, now: dt.datetime) -> None:
        settings = getattr(self.settings, "regime", self.settings)
        config = db.get(RegimeConfig, 1)
        if not settings.enabled or config is None or not config.enabled:
            return
        day = now.astimezone(NY).date()
        requests = [("ingest", f"ingest:{day.isoformat()}", now)]
        try:
            closing = session_close(day)
        except CalendarUnavailable:
            closing = None
        if closing is not None and now >= closing + dt.timedelta(minutes=90):
            requests.append(("snapshot", f"snapshot:{day.isoformat()}", closing))
        due = due_week(now)
        if due is not None:
            week, cutoff = due
            requests.append(("report", f"report:{week}", cutoff))
            # Una caída de semanas no autoriza despachar informes antiguos.
            db.execute(
                update(RegimeRun)
                .where(
                    RegimeRun.kind == "report",
                    RegimeRun.status == "PENDIENTE",
                    RegimeRun.dedupe_key.like("report:%"),
                    RegimeRun.dedupe_key != f"report:{week}",
                    RegimeRun.cutoff < cutoff,
                )
                .values(status="ERROR", finished_at=now, detail="Venció la ventana de catch-up.")
            )
        for kind, key, cutoff in requests:
            db.execute(
                insert(RegimeRun)
                .values(
                    id=new_id(),
                    kind=kind,
                    cutoff=cutoff,
                    dedupe_key=key,
                    status="PENDIENTE",
                    requested_at=now,
                    attempts=0,
                    detail="",
                    result={},
                )
                .on_conflict_do_nothing(index_elements=["dedupe_key"])
            )

    def _claim(self, db, now: dt.datetime) -> tuple[str, int] | None:
        orphan = and_(
            RegimeRun.status == "EJECUTANDO",
            or_(RegimeRun.lease_until <= now, RegimeRun.lease_until.is_(None)),
        )
        ready = or_(RegimeRun.status == "PENDIENTE", orphan)
        db.execute(
            update(RegimeRun)
            .where(
                ready,
                RegimeRun.attempts >= MAX_ATTEMPTS,
            )
            .values(
                status="ERROR",
                lease_until=None,
                finished_at=now,
                detail="Se agotaron los intentos de recuperación.",
            )
        )
        candidate = (
            select(RegimeRun.id)
            .where(
                ready,
                RegimeRun.attempts < MAX_ATTEMPTS,
            )
            .order_by(RegimeRun.requested_at, RegimeRun.id)
            .limit(1)
            .scalar_subquery()
        )
        active = aliased(RegimeRun)
        # El NOT EXISTS se evalúa en el mismo UPDATE que toma el lease:
        # limita el módulo completo incluso entre dos procesos independientes.
        result = db.execute(
            update(RegimeRun)
            .where(
                RegimeRun.id == candidate,
                ~exists(
                    select(active.id).where(
                        active.status == "EJECUTANDO",
                        active.lease_until > now,
                    )
                ),
                ~exists(
                    select(RegimeOutbox.id).where(
                        RegimeOutbox.status == "ENVIANDO",
                        RegimeOutbox.lease_until > now,
                    )
                ),
            )
            .values(
                status="EJECUTANDO",
                attempts=RegimeRun.attempts + 1,
                started_at=now,
                lease_until=now + dt.timedelta(seconds=LEASE_SECONDS),
                finished_at=None,
            )
            .returning(RegimeRun.id, RegimeRun.attempts),
            execution_options={"synchronize_session": False},
        )
        row = result.first()
        return (row.id, row.attempts) if row is not None else None

    def tick(self) -> int:
        """Solo DB y submit; devuelve el número de ejecuciones reclamadas (0/1)."""
        self.start()
        with self._lock:
            if self._closed or self._executor is None:
                return 0
            if self._future is not None and not self._future.done():
                return 0
            if not getattr(self.settings, "scheduler_enabled", True):
                return 0
            with self.session_factory() as db:
                now = utcnow()
                self._enqueue(db, now)
                claimed = self._claim(db, now)
                db.commit()
            self._future = self._executor.submit(self._work, claimed)
            return int(claimed is not None)

    def _heartbeat(self, run_id: str, attempt: int, stopped: threading.Event) -> None:
        while not stopped.wait(HEARTBEAT_SECONDS):
            now = utcnow()
            with self.session_factory() as db:
                result = db.execute(
                    update(RegimeRun)
                    .where(
                        RegimeRun.id == run_id,
                        RegimeRun.attempts == attempt,
                        RegimeRun.status == "EJECUTANDO",
                        RegimeRun.lease_until > now,
                    )
                    .values(lease_until=now + dt.timedelta(seconds=LEASE_SECONDS))
                )
                db.commit()
                if not result.rowcount:
                    return

    def _work(self, claimed: tuple[str, int] | None, *, deliveries: bool = True) -> None:
        if claimed is not None:
            run_id, attempt = claimed
            stopped = threading.Event()
            heartbeat = threading.Thread(
                target=self._heartbeat,
                args=(run_id, attempt, stopped),
                name="regime-heartbeat",
                daemon=True,
            )
            heartbeat.start()
            try:
                self.execute(run_id, attempt)
            except Exception:
                # No serializar excepciones del proveedor: pueden contener URL/secretos.
                with self.session_factory() as db:
                    db.execute(
                        update(RegimeRun)
                        .where(
                            RegimeRun.id == run_id,
                            RegimeRun.attempts == attempt,
                            RegimeRun.status == "EJECUTANDO",
                        )
                        .values(
                            status="ERROR",
                            lease_until=None,
                            finished_at=utcnow(),
                            detail="La ejecución falló; revisa el estado de las fuentes.",
                        )
                    )
                    db.commit()
                log.warning("Falló una ejecución del módulo de régimen.")
            finally:
                stopped.set()
                heartbeat.join()
        from .outbox import process_outbox

        if deliveries:
            process_outbox(self.session_factory, self.settings)
