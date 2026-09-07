"""Regimen compartido y preferencias privadas con permisos independientes."""

from __future__ import annotations

import calendar
import datetime as dt
from typing import Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import delete, func, select, update

from ..admin import registrar
from ..db import utcnow
from ..market_regime import api_models as out
from ..market_regime import service
from ..market_regime.models import (
    RegimeAccess,
    RegimeConfig,
    RegimeOutbox,
    RegimeReport,
    RegimeRun,
    RegimeSnapshot,
)
from ..models import User
from .deps import AdminDep, DbDep, RegimeLectorDep, RegimeOperadorDep, SettingsDep
from .errors import ApiError, conflicto, no_encontrado

router = APIRouter(prefix="/market-regime", tags=["market-regime"])


def _snapshot_out(row: RegimeSnapshot) -> out.SnapshotOut:
    return out.SnapshotOut(
        id=row.id,
        created_at=row.created_at,
        sha256=row.sha256,
        data=row.data,
    )


def _report_out(row: RegimeReport) -> out.ReportOut:
    return out.ReportOut(
        id=row.id,
        week_key=row.week_key,
        snapshot_id=row.snapshot_id,
        created_at=row.created_at,
        sha256=row.sha256,
        data=row.data,
    )


def _run_out(row: RegimeRun) -> out.RunOut:
    return out.RunOut(
        id=row.id,
        kind=row.kind,
        status=row.status,
        requested_at=row.requested_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
        detail=row.detail,
        result=row.result,
    )


def _can_display(db, row: RegimeSnapshot) -> bool:
    return service.can_display_snapshot(db, row)


def _get_snapshot(db, identifier: str) -> RegimeSnapshot:
    row = db.get(RegimeSnapshot, identifier)
    if row is None:
        raise no_encontrado("No se encontro ese snapshot.")
    if not _can_display(db, row):
        raise ApiError(403, "licencia_no_vigente", "La evidencia ya no tiene permiso de difusion.")
    return row


@router.get("/overview", response_model=out.OverviewOut)
def overview(db: DbDep, settings: SettingsDep, user: RegimeLectorDep):
    from ..market_regime.calendar import weekly_schedule

    row = db.scalar(
        select(RegimeSnapshot)
        .where(
            RegimeSnapshot.mode == "OPERACIONAL",
        )
        .order_by(RegimeSnapshot.as_of.desc())
        .limit(1)
    )
    if row is not None and not _can_display(db, row):
        row = None
    config = service.get_config(db)
    now = utcnow()
    next_report, calendar_status = None, "DISPONIBLE"
    try:
        _week, next_report = weekly_schedule(now)
    except ValueError as exc:
        calendar_status = str(exc)
    current_coverage = service.coverage(db, settings, now)
    warning = "Score heuristico no validado; no es probabilidad de ganancias."
    if row is not None and any(item.required and not item.available for item in current_coverage):
        warning += (
            " La cobertura actual es incompleta: el snapshot es una lectura historica al corte "
            "mostrado, no una clasificacion vigente."
        )
    return out.OverviewOut(
        enabled=config.enabled,
        engine_enabled=settings.regime.enabled,
        deliveries_enabled=settings.regime.deliveries_enabled,
        snapshot_id=row.id if row else None,
        snapshot=row.data if row else None,
        coverage=current_coverage,
        first_snapshot_at=db.scalar(
            select(func.min(RegimeSnapshot.created_at)).where(RegimeSnapshot.mode == "OPERACIONAL")
        ),
        next_report_at=next_report,
        calendar_status=calendar_status,
        warning=warning,
    )


@router.get("/sources", response_model=out.SourcesOut)
def sources(db: DbDep, settings: SettingsDep, user: RegimeLectorDep):
    return out.SourcesOut(items=service.source_infos(db, settings))


@router.get("/coverage", response_model=out.CoverageOut)
def coverage(db: DbDep, settings: SettingsDep, user: RegimeLectorDep):
    return out.CoverageOut(items=service.coverage(db, settings, utcnow()))


@router.get("/history", response_model=out.HistoryOut)
def history(
    db: DbDep,
    user: RegimeLectorDep,
    range: Literal["1w", "1m", "3m", "6m", "12m"] = "1m",
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    now = utcnow()
    if range == "1w":
        start = now - dt.timedelta(days=7)
    else:
        months = int(range[:-1])
        year, month_zero = divmod(now.year * 12 + now.month - 1 - months, 12)
        month = month_zero + 1
        start = now.replace(
            year=year, month=month, day=min(now.day, calendar.monthrange(year, month)[1])
        )
    clauses = [RegimeSnapshot.created_at >= start, RegimeSnapshot.mode == "OPERACIONAL"]
    rows = db.scalars(
        select(RegimeSnapshot)
        .where(*clauses)
        .order_by(RegimeSnapshot.as_of.desc())
        .limit(limit)
        .offset(offset)
    )
    first = db.scalar(
        select(func.min(RegimeSnapshot.created_at)).where(RegimeSnapshot.mode == "OPERACIONAL")
    )
    return out.HistoryOut(
        items=[_snapshot_out(row) for row in rows if _can_display(db, row)],
        first_available_at=first,
        requested_from=start,
        unavailable_before_first=first is None or start < first,
        total=db.scalar(select(func.count()).select_from(RegimeSnapshot).where(*clauses)) or 0,
        limit=limit,
        offset=offset,
    )


@router.get("/snapshots/{snapshot_id}", response_model=out.SnapshotOut)
def snapshot(snapshot_id: str, db: DbDep, user: RegimeLectorDep):
    return _snapshot_out(_get_snapshot(db, snapshot_id))


@router.get("/reports", response_model=out.ReportsOut)
def reports(
    db: DbDep,
    user: RegimeLectorDep,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    rows = db.scalars(
        select(RegimeReport).order_by(RegimeReport.created_at.desc()).limit(limit).offset(offset)
    )
    items = []
    for row in rows:
        if service.can_display_report(db, row):
            items.append(_report_out(row))
    return out.ReportsOut(
        items=items,
        total=db.scalar(select(func.count()).select_from(RegimeReport)) or 0,
        limit=limit,
        offset=offset,
    )


def _get_report(db, identifier: str) -> RegimeReport:
    row = db.get(RegimeReport, identifier)
    if row is None:
        raise no_encontrado("No se encontro ese informe.")
    _get_snapshot(db, row.snapshot_id)
    if not service.can_display_report(db, row):
        raise ApiError(403, "licencia_no_vigente", "Un antecedente ya no permite difusion.")
    return row


@router.get("/reports/{report_id}", response_model=out.ReportOut)
def report(report_id: str, db: DbDep, user: RegimeLectorDep):
    return _report_out(_get_report(db, report_id))


@router.get("/reports/{report_id}/html", response_class=HTMLResponse)
def report_html(report_id: str, db: DbDep, user: RegimeLectorDep):
    report = _get_report(db, report_id)
    return HTMLResponse(
        report.data["html"],
        headers={
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
            "Cache-Control": "private, no-store",
        },
    )


def _config_out(config: RegimeConfig) -> out.ConfigOut:
    return out.ConfigOut(
        version=config.version,
        enabled=config.enabled,
        config=config.data,
        updated_at=config.updated_at,
    )


@router.get("/config", response_model=out.ConfigOut)
def config(db: DbDep, user: RegimeLectorDep):
    return _config_out(service.get_config(db))


@router.patch("/config", response_model=out.ConfigOut)
def change_config(data: out.ConfigIn, db: DbDep, user: RegimeOperadorDep):
    from ..market_regime.config import validate_config

    service.get_config(db)
    try:
        validated = validate_config(data.config)
        if validated["rules"]["verified_sessions"]:
            raise ValueError(
                "Las sesiones verificadas las provee el calendario, no la configuracion."
            )
    except ValueError as exc:
        raise ApiError(422, "config_invalida", str(exc)) from exc
    changed = db.execute(
        update(RegimeConfig)
        .where(
            RegimeConfig.id == 1,
            RegimeConfig.version == data.version,
        )
        .values(
            data=validated,
            enabled=data.enabled,
            version=data.version + 1,
            updated_at=utcnow(),
            updated_by=user.id,
        )
    )
    if changed.rowcount != 1:
        raise conflicto("Otra persona cambio el modelo; recarga antes de guardar.")
    registrar(db, user, "regime.config", version=data.version + 1)
    db.expire_all()
    return _config_out(service.get_config(db))


@router.post("/runs", response_model=out.RunOut, status_code=202)
def create_run(
    data: out.RunIn,
    request: Request,
    db: DbDep,
    settings: SettingsDep,
    user: RegimeOperadorDep,
):
    if request.app.state.scheduler is None:
        raise ApiError(409, "scheduler_deshabilitado", "El scheduler central esta deshabilitado.")
    if not settings.regime.enabled or not service.get_config(db).enabled:
        raise ApiError(
            409, "regime_deshabilitado", "Habilita el modulo y su configuracion primero."
        )
    active = db.scalar(
        select(RegimeRun.id)
        .where(
            RegimeRun.status.in_(["PENDIENTE", "EJECUTANDO"]),
        )
        .limit(1)
    )
    if active:
        raise conflicto("Ya existe una ejecucion pendiente o activa.", code="regime_ocupado")
    row = service.enqueue_run(db, kind=data.kind, created_by=user.id)
    registrar(db, user, "regime.run", run_id=row.id, kind=data.kind)
    return _run_out(row)


@router.get("/runs/{run_id}", response_model=out.RunOut)
def run(run_id: str, db: DbDep, user: RegimeLectorDep):
    row = db.get(RegimeRun, run_id)
    if row is None:
        raise no_encontrado("No se encontro esa ejecucion.")
    return _run_out(row)


@router.get("/operations", response_model=out.RunsOut)
def operations(db: DbDep, user: RegimeOperadorDep):
    rows = db.scalars(select(RegimeRun).order_by(RegimeRun.requested_at.desc()).limit(50))
    return out.RunsOut(items=[_run_out(row) for row in rows])


@router.get("/me/subscription", response_model=out.SubscriptionOut)
def subscription(db: DbDep, user: RegimeLectorDep):
    from ..market_regime.subscriptions import get_subscription

    return get_subscription(db, user)


@router.put("/me/subscription", response_model=out.SubscriptionOut)
def update_subscription(data: out.SubscriptionIn, db: DbDep, user: RegimeLectorDep):
    from ..market_regime.subscriptions import update_subscription

    try:
        return update_subscription(db, user, data.model_dump())
    except ValueError as exc:
        raise ApiError(422, "suscripcion_invalida", str(exc)) from exc


@router.get("/me/deliveries", response_model=out.DeliveriesOut)
def deliveries(db: DbDep, user: RegimeLectorDep):
    rows = db.scalars(
        select(RegimeOutbox)
        .where(RegimeOutbox.user_id == user.id)
        .order_by(RegimeOutbox.created_at.desc())
        .limit(100)
    )
    return out.DeliveriesOut(
        items=[
            out.DeliveryOut(
                id=row.id,
                report_id=row.report_id,
                channel=row.channel,
                status=row.status,
                attempts=row.attempts,
                created_at=row.created_at,
                detail=row.detail,
            )
            for row in rows
        ]
    )


@router.get("/access", response_model=out.AccessesOut)
def access_list(db: DbDep, admin: AdminDep):
    rows = db.scalars(select(RegimeAccess).order_by(RegimeAccess.user_id))
    return out.AccessesOut(
        items=[out.AccessOut(user_id=row.user_id, level=row.level) for row in rows]
    )


@router.put("/access/{user_id}", response_model=out.AccessOut)
def grant(user_id: str, data: out.AccessIn, db: DbDep, admin: AdminDep):
    target = db.get(User, user_id)
    if target is None:
        raise no_encontrado("No se encontro ese usuario.")
    row = db.get(RegimeAccess, user_id)
    if row is None:
        row = RegimeAccess(user_id=user_id, level=data.level, granted_by=admin.id)
        db.add(row)
    else:
        row.level, row.granted_by = data.level, admin.id
    registrar(db, admin, "regime.acceso_concedido", target, level=data.level)
    return out.AccessOut(user_id=user_id, level=data.level)


@router.delete("/access/{user_id}", status_code=204)
def revoke(user_id: str, db: DbDep, admin: AdminDep):
    target = db.get(User, user_id)
    if target is None:
        raise no_encontrado("No se encontro ese usuario.")
    db.execute(delete(RegimeAccess).where(RegimeAccess.user_id == user_id))
    db.execute(
        update(RegimeOutbox)
        .where(
            RegimeOutbox.user_id == user_id,
            RegimeOutbox.status.in_(["PENDIENTE", "ERROR_REINTENTABLE", "BLOQUEADO"]),
        )
        .values(status="CANCELADO", detail="Acceso revocado.")
    )
    registrar(db, admin, "regime.acceso_revocado", target)
