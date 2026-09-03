"""Rutas de administración: `/api/v1/admin/*`.

A diferencia de `/me/*`, aquí sí llegan identificadores de usuario por URL, así
que cada ruta pasa por `usuario_admin`. Ese dependency devuelve **404** a quien
no es admin: un 403 confirmaría que el panel de administración existe.
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from sqlalchemy import func, or_, select

from .. import admin as servicio
from .. import watchers
from ..models import (
    JOB_RUNNING,
    AuditLog,
    JobRun,
    Schedule,
    User,
)
from ..runner import (
    AppNoDisponible,
    DemasiadosJobs,
    ErrorDeEjecucion,
    JobRunner,
    NoEstaListo,
    YaEstaCorriendo,
)
from . import schemas
from .deps import AdminDep, DbDep, SettingsDep
from .errors import ApiError, conflicto, no_encontrado, prohibido

router = APIRouter(prefix="/admin", tags=["admin"])

CAMPOS_ORDENABLES = {
    "email": User.email,
    "created_at": User.created_at,
    "last_login_at": User.last_login_at,
    "status": User.status,
    "role": User.role,
}


def _runner(request: Request) -> JobRunner:
    return request.app.state.runner


def _buscar(db, user_id: str) -> User:
    usuario = db.get(User, user_id)
    if usuario is None:
        raise no_encontrado("No se encontró ese usuario.")
    return usuario


def _comandos_de(request: Request, app_name: str) -> dict[str, str]:
    definicion = _runner(request).app_de(app_name)
    return {c.key: c.label for c in (definicion.commands if definicion else [])}


def _programacion_out(schedule: Schedule, etiquetas: dict[str, str]):
    return schemas.ProgramacionOut(
        app_name=schedule.app_name,
        command_key=schedule.command_key,
        command_label=etiquetas.get(schedule.command_key, schedule.command_key),
        enabled=schedule.enabled,
        kind=schedule.kind,
        interval_minutes=schedule.interval_minutes,
        cron_expr=schedule.cron_expr,
        next_run_at=schedule.next_run_at,
        last_run_at=schedule.last_run_at,
    )


# ---------------------------------------------------------------------------
# Usuarios
# ---------------------------------------------------------------------------


@router.get("/users", response_model=schemas.UsuariosAdminOut)
def listar_usuarios(
    db: DbDep,
    admin: AdminDep,
    q: str | None = None,
    status: str | None = None,
    role: str | None = None,
    sort: str = Query(default="created_at"),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    filtros = []
    if q:
        aguja = f"%{q.strip().lower()}%"
        filtros.append(or_(func.lower(User.email).like(aguja)))
    if status:
        filtros.append(User.status == status)
    if role:
        filtros.append(User.role == role)

    columna = CAMPOS_ORDENABLES.get(sort, User.created_at)
    columna = columna.desc() if order == "desc" else columna.asc()

    total = db.scalar(select(func.count()).select_from(User).where(*filtros)) or 0
    filas = db.scalars(
        select(User).where(*filtros).order_by(columna).limit(limit).offset(offset)
    ).all()
    return schemas.UsuariosAdminOut(
        items=list(filas), total=total, limit=limit, offset=offset
    )


@router.get("/users/{user_id}", response_model=schemas.UsuarioDetalleOut)
def ver_usuario(user_id: str, request: Request, db: DbDep, admin: AdminDep):
    usuario = _buscar(db, user_id)
    resumen = servicio.resumen_de_usuario(db, usuario)
    etiquetas = {n: _comandos_de(request, n) for n in watchers.WATCHERS}
    ultimas = db.scalars(
        select(JobRun)
        .where(JobRun.user_id == usuario.id)
        .order_by(JobRun.started_at.desc(), JobRun.id.desc())
        .limit(10)
    ).all()
    return schemas.UsuarioDetalleOut(
        user=usuario,
        watches=resumen["watches"],
        watches_enabled=resumen["watches_enabled"],
        holdings=resumen["holdings"],
        closed_positions=resumen["closed_positions"],
        total_runs=resumen["total_runs"],
        channels=[
            schemas.CanalResumenOut(channel=c, destination=d)
            for c, d in resumen["channels"].items()
        ],
        schedules=[
            _programacion_out(s, etiquetas.get(s.app_name, {}))
            for s in resumen["schedules"]
        ],
        recent_runs=[schemas.EjecucionOut.model_validate(r) for r in ultimas],
    )


@router.patch("/users/{user_id}", response_model=schemas.UsuarioAdminOut)
def cambiar_usuario(
    user_id: str, datos: schemas.CambiarUsuarioIn, db: DbDep, admin: AdminDep
):
    usuario = _buscar(db, user_id)
    try:
        if datos.status is not None:
            servicio.cambiar_estado(db, admin, usuario, datos.status)
        if datos.role is not None:
            servicio.cambiar_rol(db, admin, usuario, datos.role)
    except servicio.ErrorDeAdmin as exc:
        raise conflicto(str(exc), code=exc.codigo) from exc
    db.flush()
    return usuario


@router.post("/users/{user_id}/password", status_code=204)
def cambiar_password(
    user_id: str, datos: schemas.PasswordAdminIn, db: DbDep, admin: AdminDep
) -> None:
    usuario = _buscar(db, user_id)
    if datos.force_reset:
        servicio.forzar_reset(db, admin, usuario)
    else:
        servicio.establecer_password(db, admin, usuario, datos.new_password)


@router.delete("/users/{user_id}", status_code=204)
def eliminar_usuario(
    user_id: str,
    request: Request,
    db: DbDep,
    admin: AdminDep,
    settings: SettingsDep,
) -> None:
    usuario = _buscar(db, user_id)
    if usuario.id == admin.id:
        # Un admin que se borra a sí mismo pierde la sesión a media petición.
        raise prohibido(
            "No puedes eliminar tu propia cuenta desde el panel de administración.",
            code="autoborrado",
        )
    try:
        servicio.eliminar_usuario(db, admin, usuario, settings, _runner(request))
    except servicio.ErrorDeAdmin as exc:
        raise conflicto(str(exc), code=exc.codigo) from exc


# ---------------------------------------------------------------------------
# Ejecuciones de cualquier usuario
# ---------------------------------------------------------------------------


@router.post(
    "/users/{user_id}/apps/{app_name}/runs",
    response_model=schemas.EjecucionOut,
    status_code=201,
)
def lanzar(
    user_id: str,
    app_name: str,
    datos: schemas.LanzarIn,
    request: Request,
    db: DbDep,
    admin: AdminDep,
):
    usuario = _buscar(db, user_id)
    if not watchers.es_watcher_conocido(app_name):
        raise no_encontrado("Esa aplicación no existe.")
    try:
        return _runner(request).lanzar(
            db, usuario, app_name, datos.command_key, dry_run=datos.dry_run
        )
    except YaEstaCorriendo as exc:
        raise conflicto(str(exc), code=exc.codigo) from exc
    except (NoEstaListo, DemasiadosJobs) as exc:
        raise conflicto(str(exc), code=exc.codigo) from exc
    except AppNoDisponible as exc:
        raise no_encontrado(str(exc)) from exc
    except ErrorDeEjecucion as exc:
        raise ApiError(500, exc.codigo, str(exc)) from exc


@router.delete("/users/{user_id}/apps/{app_name}/runs/current", status_code=204)
def cancelar(
    user_id: str, app_name: str, request: Request, db: DbDep, admin: AdminDep
) -> None:
    usuario = _buscar(db, user_id)
    if not _runner(request).cancelar(usuario.id, app_name):
        raise no_encontrado("Ese usuario no tiene ninguna ejecución en curso.")
    servicio.registrar(db, admin, "job.cancelado", usuario, app_name=app_name)


@router.get("/runs", response_model=schemas.EjecucionesAdminOut)
def listar_ejecuciones(
    db: DbDep,
    admin: AdminDep,
    status: str | None = None,
    app_name: str | None = None,
    user_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
):
    consulta = select(JobRun, User.email).join(
        User, User.id == JobRun.user_id, isouter=True
    )
    if status:
        consulta = consulta.where(JobRun.status == status)
    if app_name:
        consulta = consulta.where(JobRun.app_name == app_name)
    if user_id:
        consulta = consulta.where(JobRun.user_id == user_id)
    filas = db.execute(
        consulta.order_by(JobRun.started_at.desc(), JobRun.id.desc()).limit(limit)
    ).all()
    return schemas.EjecucionesAdminOut(
        items=[
            schemas.EjecucionAdminOut(
                **schemas.EjecucionOut.model_validate(run).model_dump(),
                user_id=run.user_id,
                user_email=email,
            )
            for run, email in filas
        ]
    )


@router.get("/runs/{run_id}/log", response_model=schemas.LogOut)
def ver_log(
    run_id: int,
    request: Request,
    db: DbDep,
    admin: AdminDep,
    lines: int = Query(default=200, ge=1, le=5000),
):
    run = db.get(JobRun, run_id)
    if run is None:
        raise no_encontrado("No se encontró esa ejecución.")
    return schemas.LogOut(
        run_id=run.id,
        status=run.status,
        content=_runner(request).tail(run, lines),
        running=run.status == JOB_RUNNING,
    )


# ---------------------------------------------------------------------------
# Métricas y bitácora
# ---------------------------------------------------------------------------


@router.get("/metrics", response_model=schemas.MetricasOut)
def metricas(request: Request, db: DbDep, admin: AdminDep):
    return schemas.MetricasOut(**servicio.metricas(db, _runner(request)))


@router.get("/audit", response_model=schemas.BitacoraOut)
def bitacora(
    db: DbDep,
    admin: AdminDep,
    limit: int = Query(default=50, ge=1, le=200),
):
    filas = db.scalars(
        select(AuditLog).order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(limit)
    ).all()
    return schemas.BitacoraOut(items=list(filas))
