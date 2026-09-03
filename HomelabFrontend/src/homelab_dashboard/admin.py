"""Servicio de administración: acciones sobre otros usuarios.

Vive aparte de las rutas porque las barandas (no quedarse sin administradores,
no dispararse en el pie) son reglas de negocio que también deben valer si algún
día se llaman desde la CLI.

Toda acción deja rastro en `audit_log`. La bitácora guarda además el correo del
actor y del objetivo en texto, porque las claves foráneas se ponen a NULL
cuando se borra un usuario y una bitácora que olvida a quién se borró no sirve
de nada.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .db import utcnow
from .models import (
    JOB_ERROR,
    ROLE_ADMIN,
    ROLE_USER,
    USER_ACTIVE,
    USER_STATUSES,
    USER_SUSPENDED,
    AppChannelPref,
    AuditLog,
    AuthSession,
    JobRun,
    NotificationChannel,
    PortfolioClosedPosition,
    PortfolioHolding,
    PortfolioProfile,
    Schedule,
    StockWatch,
    User,
)
from .security import hash_password
from .settings import Settings
from .workspace import UserWorkspace

#: Tablas con datos propios del usuario. El orden no importa porque no hay
#: claves foráneas entre ellas, pero sí que estén todas: olvidar una dejaría
#: datos huérfanos de una cuenta borrada.
TABLAS_DE_USUARIO = (
    StockWatch,
    PortfolioHolding,
    PortfolioClosedPosition,
    PortfolioProfile,
    NotificationChannel,
    AppChannelPref,
    Schedule,
    JobRun,
    AuthSession,
)


class ErrorDeAdmin(Exception):
    """Una acción administrativa que no puede realizarse."""

    def __init__(self, mensaje: str, *, codigo: str = "admin_invalido") -> None:
        super().__init__(mensaje)
        self.codigo = codigo


def registrar(
    db: Session,
    actor: User,
    accion: str,
    objetivo: User | None = None,
    **detalle,
) -> AuditLog:
    entrada = AuditLog(
        actor_user_id=actor.id,
        actor_email=actor.email,
        action=accion,
        target_user_id=objetivo.id if objetivo else None,
        target_email=objetivo.email if objetivo else "",
        detail_json=detalle,
    )
    db.add(entrada)
    return entrada


def contar_admins_activos(db: Session, excluyendo: str | None = None) -> int:
    consulta = select(func.count()).where(
        User.role == ROLE_ADMIN, User.status == USER_ACTIVE
    )
    if excluyendo:
        consulta = consulta.where(User.id != excluyendo)
    return db.scalar(consulta) or 0


def _proteger_ultimo_admin(db: Session, objetivo: User, accion: str) -> None:
    """Impide dejar la instalación sin ningún administrador que pueda entrar.

    Se comprueba sobre el estado *actual* del objetivo: solo importa si el
    usuario que se va a tocar es, ahora mismo, un admin activo.
    """
    if objetivo.role != ROLE_ADMIN or objetivo.status != USER_ACTIVE:
        return
    if contar_admins_activos(db, excluyendo=objetivo.id) == 0:
        raise ErrorDeAdmin(
            f"No puedes {accion}: es el último administrador activo y la "
            "instalación quedaría sin acceso.",
            codigo="ultimo_admin",
        )


def cambiar_estado(db: Session, actor: User, objetivo: User, estado: str) -> User:
    if estado not in USER_STATUSES:
        raise ErrorDeAdmin(f"Estado desconocido: {estado}", codigo="estado_invalido")
    if estado == objetivo.status:
        return objetivo
    if estado != USER_ACTIVE:
        _proteger_ultimo_admin(db, objetivo, "suspender a este usuario")

    anterior = objetivo.status
    objetivo.status = estado
    if estado == USER_SUSPENDED:
        # Suspender sin cerrar la sesión abierta no suspendería nada hasta que
        # la cookie caducara.
        revocar_sesiones(db, objetivo)
    registrar(db, actor, "usuario.estado", objetivo, antes=anterior, despues=estado)
    return objetivo


def cambiar_rol(db: Session, actor: User, objetivo: User, rol: str) -> User:
    if rol not in (ROLE_USER, ROLE_ADMIN):
        raise ErrorDeAdmin(f"Rol desconocido: {rol}", codigo="rol_invalido")
    if rol == objetivo.role:
        return objetivo
    if rol == ROLE_USER:
        _proteger_ultimo_admin(db, objetivo, "quitarle el rol de administrador")

    anterior = objetivo.role
    objetivo.role = rol
    registrar(db, actor, "usuario.rol", objetivo, antes=anterior, despues=rol)
    return objetivo


def revocar_sesiones(db: Session, objetivo: User) -> int:
    ahora = utcnow()
    sesiones = db.scalars(
        select(AuthSession).where(
            AuthSession.user_id == objetivo.id, AuthSession.revoked_at.is_(None)
        )
    ).all()
    for sesion in sesiones:
        sesion.revoked_at = ahora
    return len(sesiones)


def establecer_password(
    db: Session, actor: User, objetivo: User, password: str
) -> User:
    """Fija una contraseña nueva y obliga a cambiarla al entrar.

    El admin conoce la contraseña que acaba de escribir, así que dejarla como
    definitiva sería darle acceso permanente a la cuenta ajena.
    """
    objetivo.password_hash = hash_password(password)
    objetivo.must_change_password = True
    objetivo.failed_login_count = 0
    objetivo.locked_until = None
    revocar_sesiones(db, objetivo)
    registrar(db, actor, "usuario.password", objetivo, forzado=False)
    return objetivo


def forzar_reset(db: Session, actor: User, objetivo: User) -> User:
    """Invalida la contraseña actual sin poner una nueva.

    Se guarda un hash imposible de obtener por ninguna entrada: la cuenta queda
    inaccesible hasta que un admin le asigne una contraseña.
    """
    objetivo.password_hash = "!"
    objetivo.must_change_password = True
    objetivo.failed_login_count = 0
    objetivo.locked_until = None
    revocar_sesiones(db, objetivo)
    registrar(db, actor, "usuario.password", objetivo, forzado=True)
    return objetivo


def eliminar_usuario(
    db: Session, actor: User, objetivo: User, settings: Settings, runner=None
) -> None:
    """Borra al usuario y todo lo suyo: datos, workspace y logs.

    Antes se cancelan sus procesos en vuelo; si no, un watcher seguiría
    escribiendo en un workspace recién borrado y notificando en su nombre.
    """
    _proteger_ultimo_admin(db, objetivo, "eliminar a este usuario")

    if runner is not None:
        for app_name in runner.corriendo_de(objetivo.id):
            runner.cancelar(objetivo.id, app_name)

    resumen = {
        "watches": db.scalar(
            select(func.count()).where(StockWatch.user_id == objetivo.id)
        ),
        "holdings": db.scalar(
            select(func.count()).where(PortfolioHolding.user_id == objetivo.id)
        ),
    }
    for modelo in TABLAS_DE_USUARIO:
        db.execute(delete(modelo).where(modelo.user_id == objetivo.id))

    # La bitácora se escribe antes del borrado para conservar el correo; la
    # clave foránea quedará en NULL y el texto seguirá ahí.
    registrar(db, actor, "usuario.eliminado", objetivo, **resumen)

    UserWorkspace.para(settings, objetivo.id).eliminar()
    _borrar_logs(settings, objetivo.id)
    db.delete(objetivo)


def _borrar_logs(settings: Settings, user_id: str) -> None:
    import shutil

    carpeta = (settings.logs_dir / user_id).resolve()
    raiz = settings.logs_dir.resolve()
    # Nunca borrar fuera del árbol de logs, aunque el id viniera manipulado.
    if carpeta != raiz and raiz in carpeta.parents and carpeta.is_dir():
        shutil.rmtree(carpeta, ignore_errors=True)


# ---------------------------------------------------------------------------
# Consultas de lectura
# ---------------------------------------------------------------------------


def resumen_de_usuario(db: Session, usuario: User) -> dict:
    """Lo que el admin necesita ver de un vistazo sobre una cuenta."""

    def _contar(modelo, *filtros):
        return (
            db.scalar(
                select(func.count()).where(modelo.user_id == usuario.id, *filtros)
            )
            or 0
        )

    canales = db.scalars(
        select(NotificationChannel).where(NotificationChannel.user_id == usuario.id)
    ).all()
    programaciones = db.scalars(
        select(Schedule).where(Schedule.user_id == usuario.id)
    ).all()
    return {
        "watches": _contar(StockWatch),
        "watches_enabled": _contar(StockWatch, StockWatch.enabled.is_(True)),
        "holdings": _contar(PortfolioHolding),
        "closed_positions": _contar(PortfolioClosedPosition),
        "channels": {c.channel: c.destination for c in canales},
        "schedules": programaciones,
        "total_runs": _contar(JobRun),
    }


def metricas(db: Session, runner=None, *, ventana_horas: int = 24) -> dict:
    desde = utcnow() - dt.timedelta(hours=ventana_horas)
    por_estado = dict(
        db.execute(select(User.status, func.count()).group_by(User.status)).all()
    )
    return {
        "users_total": sum(por_estado.values()),
        "users_by_status": por_estado,
        "admins": db.scalar(
            select(func.count()).where(User.role == ROLE_ADMIN)
        )
        or 0,
        "jobs_running": runner.jobs_activos() if runner else 0,
        "recent_failures": db.scalar(
            select(func.count()).where(
                JobRun.status == JOB_ERROR, JobRun.started_at >= desde
            )
        )
        or 0,
        "runs_last_24h": db.scalar(
            select(func.count()).where(JobRun.started_at >= desde)
        )
        or 0,
        "window_hours": ventana_horas,
    }
