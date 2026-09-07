"""Scheduler: dispara las ejecuciones programadas de cada usuario.

La base es la fuente de verdad. Un tick periódico busca las programaciones
vencidas y las despacha. APScheduler solo se usa para dos cosas: el hilo del
tick y el cálculo del siguiente disparo (`CronTrigger`).

Se prefiere este diseño a registrar un job de APScheduler por fila porque:

- sobrevive a un reinicio sin serializar ningún jobstore;
- "próxima ejecución" es una columna que la UI lee directamente;
- editar una programación es un UPDATE, no un re-registro.

El precio es una granularidad igual al periodo del tick (30 s por defecto),
irrelevante para watchers que corren cada hora o cada día.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select, update

from . import config_service
from .db import utcnow
from .models import (
    SCHEDULE_CRON,
    SCHEDULE_INTERVAL,
    TRIGGER_SCHEDULE,
    USER_ACTIVE,
    JobRun,
    Schedule,
    User,
)
from .runner import ErrorDeEjecucion, JobRunner
from .settings import Settings

if TYPE_CHECKING:
    from .market_regime.dispatcher import RegimeDispatcher

log = logging.getLogger(__name__)

INTERVALO_MINIMO = 5
INTERVALO_MAXIMO = 60 * 24 * 30


class ErrorDeProgramacion(ValueError):
    """La programación pedida no es válida."""


def zona_de(usuario: User, settings: Settings) -> ZoneInfo:
    """Zona horaria del usuario, con caída elegante a la del servidor."""
    for candidata in (usuario.timezone, settings.default_timezone, "UTC"):
        if not candidata:
            continue
        try:
            return ZoneInfo(candidata)
        except (ZoneInfoNotFoundError, ValueError):
            continue
    return ZoneInfo("UTC")


def validar_cron(expr: str) -> CronTrigger:
    """Valida una expresión cron de cinco campos."""
    try:
        return CronTrigger.from_crontab(expr.strip())
    except (ValueError, TypeError) as exc:
        raise ErrorDeProgramacion(
            "La expresión cron no es válida. Usa cinco campos, por ejemplo "
            "«0 8 * * *» para todos los días a las 8:00."
        ) from exc


def calcular_siguiente(
    schedule: Schedule,
    zona: ZoneInfo,
    *,
    desde: dt.datetime | None = None,
) -> dt.datetime | None:
    """Momento del próximo disparo, en UTC."""
    if not schedule.enabled:
        return None
    referencia = desde or utcnow()

    if schedule.kind == SCHEDULE_INTERVAL:
        minutos = schedule.interval_minutes or INTERVALO_MINIMO
        return referencia + dt.timedelta(minutes=minutos)

    if schedule.kind == SCHEDULE_CRON:
        if not schedule.cron_expr:
            return None
        disparador = CronTrigger.from_crontab(schedule.cron_expr, timezone=zona)
        siguiente = disparador.get_next_fire_time(None, referencia.astimezone(zona))
        return siguiente.astimezone(dt.timezone.utc) if siguiente else None

    return None


def validar_programacion(kind: str, interval_minutes: int | None, cron_expr: str | None) -> None:
    """Comprueba la coherencia antes de guardar."""
    if kind == SCHEDULE_INTERVAL:
        if interval_minutes is None:
            raise ErrorDeProgramacion("Indica cada cuántos minutos debe ejecutarse.")
        if interval_minutes < INTERVALO_MINIMO:
            raise ErrorDeProgramacion(f"El intervalo mínimo es de {INTERVALO_MINIMO} minutos.")
        if interval_minutes > INTERVALO_MAXIMO:
            raise ErrorDeProgramacion("El intervalo máximo es de 30 días.")
    elif kind == SCHEDULE_CRON:
        if not cron_expr:
            raise ErrorDeProgramacion("Escribe una expresión cron.")
        validar_cron(cron_expr)
    else:
        raise ErrorDeProgramacion("Tipo de programación desconocido.")


class Scheduler:
    """Despachador de las programaciones de todos los usuarios."""

    def __init__(
        self,
        settings: Settings,
        session_factory,
        runner: JobRunner,
        *,
        regime_dispatcher: RegimeDispatcher | None = None,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.runner = runner
        self.regime_dispatcher = regime_dispatcher
        self._sched: BackgroundScheduler | None = None

    # -- ciclo de vida ------------------------------------------------------

    def start(self) -> None:
        if self._sched is not None:
            return
        self._sched = BackgroundScheduler(timezone="UTC")
        self._sched.add_job(
            self.tick,
            "interval",
            seconds=self.settings.scheduler_tick_seconds,
            id="tick",
            # Si un tick se alarga, se descartan los acumulados en vez de
            # ejecutarlos todos de golpe.
            coalesce=True,
            max_instances=1,
        )
        if self.regime_dispatcher is not None:
            self._sched.add_job(
                self.regime_dispatcher.tick,
                "interval",
                seconds=self.settings.scheduler_tick_seconds,
                id="market-regime",
                coalesce=True,
                max_instances=1,
            )
        self._sched.start()
        log.info("Scheduler activo, tick cada %ss", self.settings.scheduler_tick_seconds)

    def shutdown(self) -> None:
        if self._sched is not None:
            self._sched.shutdown(wait=False)
            self._sched = None
        if self.regime_dispatcher is not None:
            self.regime_dispatcher.shutdown()

    # -- tick ---------------------------------------------------------------

    def tick(self) -> int:
        """Despacha lo vencido. Devuelve cuántas corridas lanzó."""
        ahora = utcnow()
        lanzadas = 0
        with self.session_factory() as db:
            vencidas = db.scalars(
                select(Schedule)
                .where(
                    Schedule.enabled.is_(True),
                    Schedule.next_run_at.is_not(None),
                    Schedule.next_run_at <= ahora,
                )
                .order_by(Schedule.next_run_at)
            ).all()

            for schedule in vencidas:
                # El fallo de un usuario no puede dejar sin ejecutar a los
                # demás, así que cada despacho va aislado.
                try:
                    if self._despachar(db, schedule, ahora):
                        lanzadas += 1
                except Exception:
                    log.exception("Fallo al despachar la programación %s", schedule.id)
                    db.rollback()
        return lanzadas

    def _reclamar(self, db, schedule: Schedule, ahora: dt.datetime) -> bool:
        """Toma la programación de forma atómica.

        El UPDATE condicionado a `next_run_at` hace que, si dos procesos
        compiten, solo uno vea `rowcount == 1`. Es lo que evita la ejecución
        doble si algún día se arranca uvicorn con más de un worker.
        """
        usuario = db.get(User, schedule.user_id)
        zona = zona_de(usuario, self.settings) if usuario else ZoneInfo("UTC")
        siguiente = calcular_siguiente(schedule, zona, desde=ahora)

        resultado = db.execute(
            update(Schedule)
            .where(
                Schedule.id == schedule.id,
                Schedule.next_run_at == schedule.next_run_at,
            )
            .values(next_run_at=siguiente, last_run_at=ahora, updated_at=ahora)
        )
        db.commit()
        return resultado.rowcount == 1

    def _despachar(self, db, schedule: Schedule, ahora: dt.datetime) -> bool:
        usuario = db.get(User, schedule.user_id)
        if usuario is None:
            return False

        if not self._reclamar(db, schedule, ahora):
            return False

        if usuario.status != USER_ACTIVE:
            self._omitir(db, usuario, schedule, "La cuenta no está activa.")
            return False

        estado = config_service.evaluar_readiness(db, usuario, schedule.app_name)
        if not estado.listo:
            # Sin esto el watcher abortaría con ConfigError y el usuario vería
            # un "error" sin explicación.
            self._omitir(db, usuario, schedule, estado.motivo)
            return False

        if self.runner.esta_corriendo(usuario.id, schedule.app_name):
            self._omitir(
                db,
                usuario,
                schedule,
                "La ejecución anterior todavía no terminaba.",
            )
            return False

        try:
            self.runner.lanzar(
                db,
                usuario,
                schedule.app_name,
                schedule.command_key,
                trigger=TRIGGER_SCHEDULE,
                schedule_id=schedule.id,
            )
        except ErrorDeEjecucion as exc:
            self._omitir(db, usuario, schedule, str(exc))
            return False
        return True

    def _omitir(self, db, usuario: User, schedule: Schedule, motivo: str) -> None:
        self.runner.registrar_omitida(
            db,
            usuario,
            schedule.app_name,
            schedule.command_key,
            motivo,
            trigger=TRIGGER_SCHEDULE,
            schedule_id=schedule.id,
        )

    # -- utilidades ---------------------------------------------------------

    def reprogramar(self, db, schedule: Schedule, usuario: User) -> None:
        """Recalcula `next_run_at` tras un cambio de la programación."""
        zona = zona_de(usuario, self.settings)
        schedule.next_run_at = calcular_siguiente(schedule, zona)
        schedule.updated_at = utcnow()

    def proximas_de(self, db, user_id: str) -> dict[str, dt.datetime | None]:
        filas = db.scalars(select(Schedule).where(Schedule.user_id == user_id)).all()
        return {f"{s.app_name}:{s.command_key}": s.next_run_at for s in filas}


def ultima_corrida(db, user_id: str, app_name: str) -> JobRun | None:
    return db.scalars(
        select(JobRun)
        .where(JobRun.user_id == user_id, JobRun.app_name == app_name)
        .order_by(JobRun.started_at.desc())
        .limit(1)
    ).first()
