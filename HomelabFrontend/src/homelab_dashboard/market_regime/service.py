"""Aplicacion del modulo; la red nunca ocurre dentro de una transaccion SQLite."""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
import shutil
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..db import utcnow
from ..settings import Settings
from .models import (
    RegimeConfig,
    RegimeLicense,
    RegimeObservation,
    RegimePayloadLicense,
    RegimeReport,
    RegimeRun,
    RegimeSnapshot,
    RegimeSourceState,
    RegimeTransition,
)
from .repository import (
    content_hash,
    events_as_of,
    evidence_ids,
    freeze_model,
    observations_as_of,
    persist_payload,
)
from .schemas import CoverageItem, SnapshotData, SourceInfo

log = logging.getLogger(__name__)


class LostRunLease(RuntimeError):
    pass


def require_run_lease(db: Session, run_id: str, attempt: int) -> None:
    owned = db.execute(
        update(RegimeRun)
        .where(
            RegimeRun.id == run_id,
            RegimeRun.attempts == attempt,
            RegimeRun.status == "EJECUTANDO",
            RegimeRun.lease_until > utcnow(),
        )
        .values(lease_until=RegimeRun.lease_until),
        execution_options={"synchronize_session": False},
    )
    if not owned.rowcount:
        raise LostRunLease("La ejecucion ya no pertenece a este intento.")


def credentials(settings: Settings) -> dict[str, str]:
    return {
        "bls": settings.regime.bls_key,
        "bea": settings.regime.bea_key,
        "fred": settings.regime.fred_key,
    }


def get_config(db: Session) -> RegimeConfig:
    from .config import DEFAULT_CONFIG

    value = db.get(RegimeConfig, 1)
    if value is None:
        value = RegimeConfig(id=1, version=1, enabled=False, data=dict(DEFAULT_CONFIG))
        db.add(value)
        db.flush()
    return value


def licensed(db: Session, source_id: str, *, notification: bool = False) -> bool:
    required = {"storage", "processing", "display", "derived"}
    if notification:
        required.add("notification")
    for row in db.scalars(
        select(RegimeLicense).where(
            RegimeLicense.source_id == source_id, RegimeLicense.revoked_at.is_(None)
        )
    ):
        if row.valid_until is not None and row.valid_until <= utcnow():
            continue
        if all(row.permissions.get(use) is True for use in required):
            return True
    return False


def usable_observations(db: Session, observations):
    from .catalog import SERIES, SOURCES

    sources = {source.id: source for source in SOURCES}
    imported = {item.id for item in observations if item.source_id == "authorized_import"}
    approvals = {}
    if imported:
        approvals = dict(
            db.execute(
                select(RegimeObservation.id, RegimeLicense)
                .join(RegimePayloadLicense, RegimePayloadLicense.raw_id == RegimeObservation.raw_id)
                .join(RegimeLicense, RegimeLicense.id == RegimePayloadLicense.license_id)
                .where(RegimeObservation.id.in_(imported))
            ).all()
        )
    result = []
    for item in observations:
        spec = SERIES.get(item.series_id)
        source = sources.get(item.source_id)
        if spec is None or source is None:
            continue
        owner = sources[str(spec["source_id"])]
        if item.source_id == "authorized_import":
            approval = approvals.get(item.id)
            if (
                approval is None
                or approval.source_id != owner.id
                or not approval.evidence_sha256
                or approval.revoked_at is not None
                or (approval.valid_until is not None and approval.valid_until <= utcnow())
                or not all(
                    approval.permissions.get(use) is True
                    for use in ("storage", "processing", "display", "derived")
                )
            ):
                continue
        elif source.restricted or owner.restricted:
            continue
        result.append(item)
    return result


def can_display_snapshot(db: Session, row: RegimeSnapshot) -> bool:
    from .catalog import SOURCES

    sources = {source.id: source for source in SOURCES}
    snapshot = SnapshotData.model_validate(row.data)
    for item in snapshot.coverage:
        if item.available and (
            item.source_id not in sources
            or (sources[item.source_id].restricted and not licensed(db, item.source_id))
        ):
            return False
    try:
        ids = evidence_ids(row.data)
    except ValueError:
        return False
    if ids:
        observations = db.scalars(
            select(RegimeObservation).where(RegimeObservation.id.in_(ids))
        ).all()
        if {item.id for item in usable_observations(db, observations)} != ids:
            return False
    return True


def can_display_report(db: Session, report: RegimeReport) -> bool:
    ids = report.data.get("snapshot_ids") or [report.snapshot_id]
    if report.snapshot_id not in ids:
        return False
    for identifier in ids:
        snapshot = db.get(RegimeSnapshot, identifier)
        if snapshot is None or not can_display_snapshot(db, snapshot):
            return False
    return True


def effective_config(config: dict) -> dict:
    from .calendar import load_calendar

    result = deepcopy(config)
    calendar = load_calendar()
    day = dt.date.fromisoformat(calendar.data["valid_from"])
    end = dt.date.fromisoformat(calendar.data["valid_until"])
    sessions = []
    while day <= end:
        if calendar.session_close(day) is not None:
            sessions.append(day.isoformat())
        day += dt.timedelta(days=1)
    result["rules"]["verified_sessions"] = sessions
    return result


def model_manifest(config: dict) -> dict:
    from .calendar import load_calendar

    digest = hashlib.sha256()
    root = Path(__file__).parent
    for path in sorted(root.rglob("*.py")):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return {
        "engine": config,
        "implementation_sha256": digest.hexdigest(),
        "calendar_sha256": load_calendar().sha256,
        "calendar_version": load_calendar().version,
    }


def source_infos(db: Session, settings: Settings) -> list[SourceInfo]:
    from .catalog import source_infos as catalog_sources

    result = catalog_sources(credentials(settings))
    states = {row.source_id: row for row in db.scalars(select(RegimeSourceState))}
    for item in result:
        state = states.get(item.id)
        if state is not None:
            item.last_success_at = state.last_success_at
            if not item.restricted and item.status != "NO_CONFIGURADO":
                item.status = state.status
                item.detail = state.detail
        if item.restricted and licensed(db, item.id):
            item.detail = "Permiso registrado; requiere importacion o proveedor autorizado."
    return result


def coverage(db: Session, settings: Settings, as_of: dt.datetime) -> list[CoverageItem]:
    from .catalog import REQUIRED_SERIES, SERIES

    available = usable_observations(db, observations_as_of(db, as_of))
    sources = {item.id: item for item in source_infos(db, settings)}
    latest = {}
    for item in available:
        latest[item.series_id] = item
    ttl = {"daily": 7, "weekly": 14, "monthly": 65, "quarterly": 150, "event": 100}
    result = []
    for identifier, spec in SERIES.items():
        source_id = str(spec["source_id"])
        source = sources[source_id]
        item = latest.get(identifier)
        allowed = not source.restricted or licensed(db, source_id)
        reason = ""
        if not allowed:
            reason = "BLOQUEADO_LICENCIA: no hay derechos acreditados para este uso."
        elif item is None:
            reason = source.detail or "No hay observaciones disponibles al corte."
        else:
            max_age = int(spec.get("max_age_days", ttl[item.frequency]))
            if identifier == "USDJPY":
                max_age = max(max_age, 14)
            if as_of - item.observed_at > dt.timedelta(days=max_age):
                reason = "Dato atrasado para la cadencia de publicacion."
        result.append(
            CoverageItem(
                series_id=identifier,
                name=str(spec["name"]),
                source_id=source_id,
                required=identifier in REQUIRED_SERIES,
                available=not reason,
                reason=reason,
                observed_at=item.observed_at if item and allowed else None,
                published_at=item.published_at if item and allowed else None,
                ingested_at=item.ingested_at if item and allowed else None,
                source_url=item.source_url if item and allowed else source.url,
            )
        )
    return result


def build_snapshot(
    db: Session,
    settings: Settings,
    as_of: dt.datetime,
    *,
    reconstructed: bool = False,
) -> RegimeSnapshot:
    from .calendar import bar_key
    from .scoring import calculate
    from .transitions import advance_transition

    config = get_config(db)
    active_config = effective_config(config.data)
    model_id = freeze_model(db, model_manifest(active_config))
    inputs = usable_observations(db, observations_as_of(db, as_of))
    coverage_items = coverage(db, settings, as_of)
    eligible = {item.series_id for item in coverage_items if item.available}
    # Los datos restringidos no entran al calculo aunque quedaran almacenados.
    inputs = [item for item in inputs if item.series_id in eligible]
    result = calculate(inputs, as_of=as_of, config=active_config, coverage=coverage_items)
    result.model_version = model_id
    result.events = events_as_of(db, as_of)
    if reconstructed:
        result.mode = "RECONSTRUCCION"
    for index, horizon in enumerate(result.horizons):
        key = bar_key(horizon.horizon, as_of)
        if key is None:
            horizon.transition_status = "NO_EVALUABLE"
            continue
        state = db.get(RegimeTransition, horizon.horizon)
        if reconstructed or (state is not None and state.updated_at > as_of):
            horizon.transition_status = "NO_EVALUABLE"
            horizon.changes.append("La reconstruccion no altera confirmaciones operacionales.")
            continue
        prior = (
            deepcopy(state.state)
            if state and state.state.get("model_id") == model_id
            else {
                "rules": active_config["transition"],
            }
        )
        if horizon.horizon == "SHORT":
            midnight = dt.datetime.combine(
                dt.date.fromisoformat(key),
                dt.time.min,
                ZoneInfo("America/New_York"),
            )
            prior["expected_previous_bar"] = bar_key("SHORT", midnight)
        updated, next_state = advance_transition(horizon, prior, bar_key=key, as_of=as_of)
        next_state["model_id"] = model_id
        result.horizons[index] = updated
        if state is None:
            db.add(RegimeTransition(horizon=horizon.horizon, state=next_state))
        else:
            state.state = next_state
            state.updated_at = utcnow()
    data = result.model_dump(mode="json")
    row = RegimeSnapshot(
        as_of=as_of,
        model_id=model_id,
        data=data,
        sha256=content_hash(data),
        mode=result.mode,
    )
    db.add(row)
    db.flush()
    return row


def build_report(
    db: Session,
    snapshot: RegimeSnapshot,
    *,
    week_key: str,
) -> RegimeReport:
    from .reports import render_report
    from .subscriptions import enqueue_report

    existing = db.scalar(select(RegimeReport).where(RegimeReport.week_key == week_key))
    if existing is not None:
        return existing
    previous = db.scalar(
        select(RegimeSnapshot)
        .where(RegimeSnapshot.as_of < snapshot.as_of, RegimeSnapshot.mode == snapshot.mode)
        .order_by(RegimeSnapshot.as_of.desc())
        .limit(1)
    )
    if previous is not None and not can_display_snapshot(db, previous):
        previous = None
    report = render_report(
        SnapshotData.model_validate(snapshot.data),
        week_key=week_key,
        previous=SnapshotData.model_validate(previous.data) if previous else None,
    )
    report.snapshot_ids = [snapshot.id] + ([previous.id] if previous is not None else [])
    data = report.model_dump(mode="json")
    row = RegimeReport(
        week_key=week_key,
        snapshot_id=snapshot.id,
        data=data,
        sha256=content_hash(data),
    )
    db.add(row)
    db.flush()
    enqueue_report(db, row)
    return row


def enqueue_run(
    db: Session,
    *,
    kind: str,
    created_by: str | None = None,
    cutoff: dt.datetime | None = None,
    dedupe_key: str | None = None,
) -> RegimeRun:
    if kind not in {"ingest", "snapshot", "report"}:
        raise ValueError("Tipo de ejecucion desconocido.")
    if dedupe_key:
        existing = db.scalar(select(RegimeRun).where(RegimeRun.dedupe_key == dedupe_key))
        if existing:
            return existing
    row = RegimeRun(
        kind=kind,
        created_by=created_by,
        cutoff=cutoff,
        dedupe_key=dedupe_key,
        status="PENDIENTE",
    )
    db.add(row)
    db.flush()
    return row


def ingest_sources(
    factory: Callable[[], Session],
    settings: Settings,
    *,
    guard: Callable[[Session], None] | None = None,
) -> dict[str, object]:
    from .providers import collect_source
    from .providers.http import DAILY_REQUEST_BUDGETS, MAX_REQUESTS_PER_COLLECTION

    if shutil.disk_usage(settings.data_dir).free < settings.regime.disk_min_free_mb * 1024**2:
        raise ValueError("Espacio insuficiente: se detuvo solo la ingestion del modulo.")
    with factory() as db:
        sources = source_infos(db, settings)
    total = 0
    statuses: dict[str, str] = {}
    for source in sources:
        if source.restricted or source.status == "NO_CONFIGURADO":
            statuses[source.id] = source.status
            continue
        now = utcnow()
        with factory() as db:
            if guard is not None:
                guard(db)
            state = db.get(RegimeSourceState, source.id)
            if state is None:
                state = RegimeSourceState(source_id=source.id, status="PENDIENTE")
                db.add(state)
                db.flush()
            day = now.date().isoformat()
            if state.budget_day != day:
                state.budget_day, state.daily_requests = day, 0
            reservation = MAX_REQUESTS_PER_COLLECTION[source.id]
            if state.daily_requests + reservation > DAILY_REQUEST_BUDGETS[source.id]:
                state.status, state.detail = "ERROR", "Presupuesto local diario agotado."
                db.commit()
                statuses[source.id] = "ERROR"
                continue
            # Reserva durable del peor caso, incluidos los reintentos HTTP.
            state.daily_requests += reservation
            state.last_attempt_at = now
            db.commit()
        result = collect_source(source.id, credentials(settings), now=now)
        with factory() as db:
            if guard is not None:
                guard(db)
            state = db.get(RegimeSourceState, source.id)
            state.status, state.detail = result.status, result.detail
            statuses[source.id] = result.status
            for payload in result.payloads:
                total += persist_payload(
                    db,
                    source_id=payload.source_id,
                    source_url=payload.source_url,
                    raw=payload.raw,
                    observations=payload.observations,
                    ingested_at=utcnow(),
                    events=payload.events,
                )
            if result.status == "DISPONIBLE":
                state.last_success_at = utcnow()
            db.commit()
    return {"observations_added": total, "sources": statuses}


def execute_run(
    factory: Callable[[], Session],
    settings: Settings,
    run_id: str,
    *,
    attempt: int,
) -> None:
    from .calendar import due_week

    result: dict[str, object] = {}
    try:
        with factory() as db:
            require_run_lease(db, run_id, attempt)
            run = db.get(RegimeRun, run_id)
            kind, cutoff = run.kind, run.cutoff
        if kind in {"ingest", "report"}:
            result.update(
                ingest_sources(
                    factory,
                    settings,
                    guard=lambda db: require_run_lease(db, run_id, attempt),
                )
            )
        as_of = cutoff or utcnow()
        due = due_week(as_of) if kind == "report" else None
        if kind == "report":
            if due is None:
                raise ValueError("Aun no vence el reporte semanal; usa recalcular snapshot.")
            as_of = due[1]
        with factory() as db:
            require_run_lease(db, run_id, attempt)
            snapshot = build_snapshot(
                db,
                settings,
                as_of,
                reconstructed=kind == "report" and utcnow() - as_of > dt.timedelta(minutes=5),
            )
            result["snapshot_id"] = snapshot.id
            data = SnapshotData.model_validate(snapshot.data)
            if kind == "report":
                report = build_report(db, snapshot, week_key=due[0])
                result["report_id"] = report.id
            require_run_lease(db, run_id, attempt)
            run = db.get(RegimeRun, run_id)
            run.status = (
                "COMPLETO"
                if all(h.data_status == "COMPLETO" for h in data.horizons)
                else "INCOMPLETO"
            )
            run.result = result
            run.detail = (
                "Analisis persistido."
                if run.status == "COMPLETO"
                else "Evidencia parcial persistida; no se emitieron scores sin cobertura."
            )
            run.finished_at, run.lease_until = utcnow(), None
            db.commit()
    except LostRunLease:
        log.warning("Regimen: intento %s de %s abortado por perdida de lease.", attempt, run_id)
    except (ValueError, OSError) as exc:
        with factory() as db:
            try:
                require_run_lease(db, run_id, attempt)
            except LostRunLease:
                log.warning("Regimen: error de un intento sin lease; no modifica %s.", run_id)
                return
            run = db.get(RegimeRun, run_id)
            run.status, run.detail = "ERROR", str(exc)
            run.finished_at, run.lease_until = utcnow(), None
            db.commit()
        log.warning("Regimen: corrida %s no completada: %s", run_id, exc)
