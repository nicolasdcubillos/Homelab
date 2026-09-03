"""Servicio de autenticación: alta de usuarios, login, sesiones y bloqueos.

Toda la lógica vive aquí y no en las rutas de FastAPI, para poder testearla sin
levantar un cliente HTTP y para que el comando `create-admin` reutilice
exactamente el mismo camino de creación que el registro web.

Decisiones que conviene tener presentes al leer:

- El login nunca distingue "el correo no existe" de "la contraseña es
  incorrecta", ni por mensaje ni por latencia.
- Las sesiones se guardan hasheadas. Un volcado de la base no permite
  suplantar a nadie.
- El límite de intentos es doble: por correo (protege una cuenta concreta) y
  por IP (protege contra el barrido de muchas cuentas).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .db import utcnow
from .models import (
    ROLE_ADMIN,
    ROLE_USER,
    USER_ACTIVE,
    USER_PENDING,
    USER_STATUSES,
    AuthSession,
    LoginAttempt,
    User,
)
from .security import (
    PasswordDebil,
    generar_token,
    hash_password,
    hash_token,
    necesita_rehash,
    normalizar_email,
    quemar_tiempo_de_verificacion,
    verificar_password,
)
from .settings import Settings

# Se conserva un histórico corto de intentos: lo justo para la ventana
# deslizante más margen para que el admin vea un ataque reciente.
RETENCION_INTENTOS_HORAS = 24


class ErrorDeAuth(Exception):
    """Error de autenticación con mensaje presentable en español."""

    codigo = "auth_error"

    def __init__(self, mensaje: str, *, codigo: str | None = None) -> None:
        super().__init__(mensaje)
        self.mensaje = mensaje
        if codigo:
            self.codigo = codigo


class EmailYaRegistrado(ErrorDeAuth):
    codigo = "email_ya_registrado"


class CredencialesInvalidas(ErrorDeAuth):
    codigo = "credenciales_invalidas"


class CuentaBloqueada(ErrorDeAuth):
    codigo = "cuenta_bloqueada"


class CuentaSuspendida(ErrorDeAuth):
    codigo = "cuenta_suspendida"


@dataclass(frozen=True)
class SesionCreada:
    """Resultado de un login: los tokens en claro solo existen aquí."""

    session_id: str
    token: str
    csrf_token: str
    expires_at: dt.datetime
    user: User


# --------------------------------------------------------------------------
# Alta de usuarios
# --------------------------------------------------------------------------


def crear_usuario(
    db: Session,
    *,
    email: str,
    password: str,
    role: str = ROLE_USER,
    status: str = USER_PENDING,
    timezone: str | None = None,
    must_change_password: bool = False,
) -> User:
    """Crea un usuario. Único camino de creación de toda la aplicación."""
    email_normalizado = normalizar_email(email)
    if not email_normalizado or "@" not in email_normalizado:
        raise ErrorDeAuth("El correo no es válido.", codigo="email_invalido")
    if role not in (ROLE_USER, ROLE_ADMIN):
        raise ErrorDeAuth(f"Rol desconocido: {role}", codigo="rol_invalido")
    if status not in USER_STATUSES:
        raise ErrorDeAuth(f"Estado desconocido: {status}", codigo="estado_invalido")

    try:
        password_hash = hash_password(password)
    except PasswordDebil as exc:
        raise ErrorDeAuth(str(exc), codigo="password_debil") from exc

    usuario = User(
        email=email_normalizado,
        password_hash=password_hash,
        role=role,
        status=status,
        timezone=timezone or "America/Bogota",
        must_change_password=must_change_password,
    )
    db.add(usuario)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise EmailYaRegistrado(
            "Ya existe una cuenta con ese correo.",
        ) from exc
    return usuario


def buscar_por_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == normalizar_email(email)))


def hay_algun_usuario(db: Session) -> bool:
    """True si la instalación ya tiene usuarios (usado por el bootstrap)."""
    return db.scalar(select(func.count()).select_from(User)) > 0


def contar_admins_activos(db: Session, *, excluyendo: str | None = None) -> int:
    """Cuenta admins que pueden entrar. Sostiene la baranda del último admin."""
    stmt = select(func.count()).select_from(User).where(
        User.role == ROLE_ADMIN, User.status == USER_ACTIVE
    )
    if excluyendo:
        stmt = stmt.where(User.id != excluyendo)
    return db.scalar(stmt) or 0


# --------------------------------------------------------------------------
# Límite de intentos de login
# --------------------------------------------------------------------------


def _intentos_fallidos_recientes(
    db: Session, *, email: str, ip: str, desde: dt.datetime
) -> tuple[int, int]:
    """Devuelve (fallos por correo, fallos por IP) dentro de la ventana."""
    por_email = db.scalar(
        select(func.count())
        .select_from(LoginAttempt)
        .where(
            LoginAttempt.email == email,
            LoginAttempt.successful.is_(False),
            LoginAttempt.created_at >= desde,
        )
    )
    por_ip = 0
    if ip:
        por_ip = db.scalar(
            select(func.count())
            .select_from(LoginAttempt)
            .where(
                LoginAttempt.ip == ip,
                LoginAttempt.successful.is_(False),
                LoginAttempt.created_at >= desde,
            )
        )
    return int(por_email or 0), int(por_ip or 0)


def _registrar_intento(db: Session, *, email: str, ip: str, exitoso: bool) -> None:
    db.add(LoginAttempt(email=email, ip=ip or "", successful=exitoso))


def _persistir_fallo(db: Session, *, email: str, ip: str) -> None:
    """Registra un intento fallido y lo hace duradero de inmediato.

    El commit explícito no es opcional: un login fallido termina lanzando una
    excepción, y la dependencia `get_db` hace rollback ante cualquier
    excepción. Sin este commit el contador de intentos se borraría justo
    cuando hace falta, y el límite de fuerza bruta no existiría en la práctica.
    """
    _registrar_intento(db, email=email, ip=ip, exitoso=False)
    db.commit()


def purgar_intentos_antiguos(db: Session, *, ahora: dt.datetime | None = None) -> int:
    """Borra intentos fuera de la ventana de retención. Devuelve cuántos."""
    limite = (ahora or utcnow()) - dt.timedelta(hours=RETENCION_INTENTOS_HORAS)
    resultado = db.execute(delete(LoginAttempt).where(LoginAttempt.created_at < limite))
    return resultado.rowcount or 0


# --------------------------------------------------------------------------
# Login y sesiones
# --------------------------------------------------------------------------


def autenticar(
    db: Session,
    settings: Settings,
    *,
    email: str,
    password: str,
    ip: str = "",
    user_agent: str | None = None,
    ahora: dt.datetime | None = None,
) -> SesionCreada:
    """Verifica credenciales y abre una sesión.

    Lanza `CuentaBloqueada` si se agotaron los intentos, `CuentaSuspendida` si
    la cuenta está suspendida, y `CredencialesInvalidas` en cualquier otro caso
    de fallo — incluido el correo inexistente.
    """
    ahora = ahora or utcnow()
    email_normalizado = normalizar_email(email)
    ventana_desde = ahora - dt.timedelta(minutes=settings.login_window_minutes)

    fallos_email, fallos_ip = _intentos_fallidos_recientes(
        db, email=email_normalizado, ip=ip, desde=ventana_desde
    )
    # La IP tiene un margen mayor: detrás de un NAT o de Caddy pueden convivir
    # varias personas legítimas, pero un barrido de cuentas sigue chocando.
    if fallos_email >= settings.login_max_attempts or fallos_ip >= settings.login_max_attempts * 4:
        raise CuentaBloqueada(
            "Demasiados intentos fallidos. Espera unos minutos antes de volver a intentarlo.",
        )

    usuario = buscar_por_email(db, email_normalizado)

    if usuario is None:
        # Gastamos el mismo tiempo que un verify real para no revelar por
        # latencia qué correos existen.
        quemar_tiempo_de_verificacion(password)
        _persistir_fallo(db, email=email_normalizado, ip=ip)
        raise CredencialesInvalidas("Correo o contraseña incorrectos.")

    if usuario.locked_until is not None and usuario.locked_until > ahora:
        raise CuentaBloqueada(
            "La cuenta está bloqueada temporalmente por intentos fallidos. Inténtalo más tarde.",
        )

    if not verificar_password(usuario.password_hash, password):
        usuario.failed_login_count += 1
        if usuario.failed_login_count >= settings.login_max_attempts:
            usuario.locked_until = ahora + dt.timedelta(minutes=settings.login_lockout_minutes)
        _persistir_fallo(db, email=email_normalizado, ip=ip)
        raise CredencialesInvalidas("Correo o contraseña incorrectos.")

    # A partir de aquí la contraseña es correcta.
    if usuario.status == "suspended":
        # Se registra como intento exitoso: la credencial era válida, así que
        # no debe contar contra el límite de fuerza bruta.
        _registrar_intento(db, email=email_normalizado, ip=ip, exitoso=True)
        db.commit()
        raise CuentaSuspendida(
            "Tu cuenta está suspendida. Contacta al administrador.",
        )

    if necesita_rehash(usuario.password_hash):
        usuario.password_hash = hash_password(password)

    usuario.failed_login_count = 0
    usuario.locked_until = None
    usuario.last_login_at = ahora
    _registrar_intento(db, email=email_normalizado, ip=ip, exitoso=True)

    return abrir_sesion(
        db, settings, usuario=usuario, ip=ip, user_agent=user_agent, ahora=ahora
    )


def abrir_sesion(
    db: Session,
    settings: Settings,
    *,
    usuario: User,
    ip: str = "",
    user_agent: str | None = None,
    ahora: dt.datetime | None = None,
) -> SesionCreada:
    """Crea una fila de sesión y devuelve los tokens en claro."""
    ahora = ahora or utcnow()
    token = generar_token()
    csrf = generar_token()
    expira = ahora + dt.timedelta(hours=settings.session_ttl_hours)

    sesion = AuthSession(
        user_id=usuario.id,
        token_hash=hash_token(token),
        csrf_token=csrf,
        created_at=ahora,
        last_seen_at=ahora,
        expires_at=expira,
        user_agent=(user_agent or "")[:256] or None,
        ip=ip[:64] or None,
    )
    db.add(sesion)
    db.flush()
    return SesionCreada(
        session_id=sesion.id,
        token=token,
        csrf_token=csrf,
        expires_at=expira,
        user=usuario,
    )


def resolver_sesion(
    db: Session, token: str | None, *, ahora: dt.datetime | None = None
) -> tuple[AuthSession, User] | None:
    """Traduce el token de la cookie a (sesión, usuario) o None."""
    if not token:
        return None
    ahora = ahora or utcnow()
    sesion = db.scalar(select(AuthSession).where(AuthSession.token_hash == hash_token(token)))
    if sesion is None or sesion.revoked_at is not None or sesion.expires_at <= ahora:
        return None
    usuario = db.get(User, sesion.user_id)
    if usuario is None:
        return None
    # `last_seen_at` se refresca con granularidad de minutos para no escribir
    # en la base en cada petición de una SPA que hace polling.
    if (ahora - sesion.last_seen_at) > dt.timedelta(minutes=1):
        sesion.last_seen_at = ahora
    return sesion, usuario


def cerrar_sesion(db: Session, sesion: AuthSession, *, ahora: dt.datetime | None = None) -> None:
    sesion.revoked_at = ahora or utcnow()


def revocar_sesiones_de(
    db: Session,
    user_id: str,
    *,
    excepto: str | None = None,
    ahora: dt.datetime | None = None,
) -> int:
    """Revoca todas las sesiones vivas de un usuario. Devuelve cuántas.

    Se usa al cambiar contraseña, al suspender y al resetear desde el admin:
    cualquier cambio de credencial o de estado debe expulsar las sesiones
    abiertas en otros dispositivos.
    """
    ahora = ahora or utcnow()
    stmt = select(AuthSession).where(
        AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None)
    )
    if excepto:
        stmt = stmt.where(AuthSession.id != excepto)
    sesiones = list(db.scalars(stmt))
    for sesion in sesiones:
        sesion.revoked_at = ahora
    return len(sesiones)


def purgar_sesiones_expiradas(db: Session, *, ahora: dt.datetime | None = None) -> int:
    ahora = ahora or utcnow()
    resultado = db.execute(delete(AuthSession).where(AuthSession.expires_at < ahora))
    return resultado.rowcount or 0


# --------------------------------------------------------------------------
# Cambio de contraseña
# --------------------------------------------------------------------------


def cambiar_password(
    db: Session,
    *,
    usuario: User,
    password_actual: str | None,
    password_nueva: str,
    exigir_actual: bool = True,
) -> None:
    """Cambia la contraseña del usuario.

    `exigir_actual=False` es el caso del reset forzado por un admin: el usuario
    entró con `must_change_password` y no tiene por qué saber la anterior.
    """
    if exigir_actual:
        if not verificar_password(usuario.password_hash, password_actual or ""):
            raise CredencialesInvalidas("La contraseña actual es incorrecta.")
        if password_actual == password_nueva:
            raise ErrorDeAuth(
                "La contraseña nueva debe ser distinta de la actual.",
                codigo="password_repetida",
            )

    try:
        usuario.password_hash = hash_password(password_nueva)
    except PasswordDebil as exc:
        raise ErrorDeAuth(str(exc), codigo="password_debil") from exc

    usuario.must_change_password = False
    usuario.failed_login_count = 0
    usuario.locked_until = None
