"""Dependencias compartidas de la API: base de datos, sesión, CSRF y roles.

El principio que gobierna todo este módulo: **el `user_id` se deriva siempre de
la cookie de sesión, nunca de la URL ni del cuerpo de la petición.** Las rutas
de `/me/...` no reciben identificadores de usuario, y las de `/admin/...` los
reciben pero exigen rol admin.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request, Response
from sqlalchemy.orm import Session

from .. import auth
from ..models import ROLE_ADMIN, USER_ACTIVE, USER_SUSPENDED, AuthSession, User
from ..security import tokens_iguales
from ..settings import Settings
from .errors import ApiError, no_autenticado, prohibido

COOKIE_SESION = "hld_session"
COOKIE_CSRF = "hld_csrf"
HEADER_CSRF = "X-CSRF-Token"

METODOS_MUTANTES = {"POST", "PUT", "PATCH", "DELETE"}


# --------------------------------------------------------------------------
# Infraestructura
# --------------------------------------------------------------------------


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_db(request: Request) -> Iterator[Session]:
    """Sesión de base por petición, con commit al terminar bien.

    Se hace commit aquí y no en cada ruta para que una ruta que lance a mitad
    no deje escrituras parciales.
    """
    factory = request.app.state.session_factory
    db = factory()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


SettingsDep = Annotated[Settings, Depends(get_settings)]
DbDep = Annotated[Session, Depends(get_db)]


# --------------------------------------------------------------------------
# Cookies
# --------------------------------------------------------------------------


def fijar_cookies_de_sesion(
    response: Response, settings: Settings, sesion: auth.SesionCreada
) -> None:
    """Escribe la cookie de sesión (httpOnly) y la de CSRF (legible por JS)."""
    max_age = settings.session_ttl_hours * 3600
    response.set_cookie(
        COOKIE_SESION,
        sesion.token,
        max_age=max_age,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        path="/",
    )
    # Deliberadamente NO httpOnly: la SPA tiene que leerla para reenviarla en
    # la cabecera. No es un secreto de autenticación por sí sola; solo prueba
    # que la petición la originó nuestro propio frontend.
    response.set_cookie(
        COOKIE_CSRF,
        sesion.csrf_token,
        max_age=max_age,
        httponly=False,
        secure=settings.secure_cookies,
        samesite="lax",
        path="/",
    )


def borrar_cookies_de_sesion(response: Response, settings: Settings) -> None:
    for nombre in (COOKIE_SESION, COOKIE_CSRF):
        response.delete_cookie(
            nombre,
            path="/",
            httponly=(nombre == COOKIE_SESION),
            secure=settings.secure_cookies,
            samesite="lax",
        )


def ip_del_cliente(request: Request) -> str:
    """IP real del cliente, confiando en `X-Forwarded-For` de Caddy.

    El dashboard escucha solo en 127.0.0.1 detrás de Caddy, así que la
    cabecera solo puede venir del proxy. Si algún día se expusiera
    directamente, esto habría que revisarlo.
    """
    reenviada = request.headers.get("x-forwarded-for", "")
    if reenviada:
        return reenviada.split(",")[0].strip()[:64]
    return (request.client.host if request.client else "")[:64]


# --------------------------------------------------------------------------
# Sesión y usuario
# --------------------------------------------------------------------------


def sesion_opcional(request: Request, db: DbDep) -> tuple[AuthSession, User] | None:
    """Resuelve la sesión sin exigirla. Cachea en `request.state`."""
    if hasattr(request.state, "contexto_auth"):
        return request.state.contexto_auth
    token = request.cookies.get(COOKIE_SESION)
    contexto = auth.resolver_sesion(db, token)
    request.state.contexto_auth = contexto
    return contexto


SesionOpcionalDep = Annotated[tuple[AuthSession, User] | None, Depends(sesion_opcional)]


def contexto_requerido(contexto: SesionOpcionalDep) -> tuple[AuthSession, User]:
    if contexto is None:
        raise no_autenticado()
    return contexto


ContextoDep = Annotated[tuple[AuthSession, User], Depends(contexto_requerido)]


def verificar_csrf(request: Request, contexto: ContextoDep) -> None:
    """Exige el token CSRF en métodos mutantes de sesiones autenticadas.

    La cookie es `SameSite=Lax`, así que un POST desde otro sitio ni siquiera
    la enviaría. Esta comprobación es la segunda capa: cubre el caso de un
    navegador antiguo sin soporte de SameSite y el de una petición del mismo
    sitio originada por contenido inyectado.
    """
    if request.method not in METODOS_MUTANTES:
        return
    sesion, _usuario = contexto
    enviado = request.headers.get(HEADER_CSRF, "")
    if not tokens_iguales(enviado, sesion.csrf_token):
        raise ApiError(
            403,
            "csrf_invalido",
            "La sesión expiró o la petición no es válida. Recarga la página.",
        )


def usuario_autenticado(contexto: ContextoDep, _csrf: None = Depends(verificar_csrf)) -> User:
    """Usuario con sesión válida. No comprueba estado ni contraseña pendiente."""
    _sesion, usuario = contexto
    return usuario


UsuarioDep = Annotated[User, Depends(usuario_autenticado)]


def usuario_configurable(usuario: UsuarioDep) -> User:
    """Usuario que puede editar su propia configuración.

    Un usuario `pending` entra aquí a propósito: puede dejar todo listo
    mientras espera la aprobación del administrador. Lo que no puede es
    *ejecutar* nada, que es lo que exige `usuario_operativo`.
    """
    if usuario.must_change_password:
        raise prohibido(
            "Debes cambiar tu contraseña antes de continuar.",
            code="password_change_required",
        )
    if usuario.status == USER_SUSPENDED:
        raise prohibido(
            "Tu cuenta está suspendida. Contacta al administrador.",
            code="cuenta_suspendida",
        )
    return usuario


ConfiguradorDep = Annotated[User, Depends(usuario_configurable)]


def usuario_operativo(usuario: UsuarioDep) -> User:
    """Usuario que puede lanzar y programar ejecuciones."""
    if usuario.must_change_password:
        raise prohibido(
            "Debes cambiar tu contraseña antes de continuar.",
            code="password_change_required",
        )
    if usuario.status != USER_ACTIVE:
        raise prohibido(
            "Tu cuenta todavía no está activa. Un administrador debe aprobarla.",
            code="cuenta_no_activa",
        )
    return usuario


UsuarioOperativoDep = Annotated[User, Depends(usuario_operativo)]


def usuario_admin(usuario: UsuarioDep) -> User:
    """Exige rol admin. Devuelve 404 y no 403 a propósito.

    Un usuario normal no debe poder deducir siquiera que existe una sección de
    administración: para él, esas rutas simplemente no existen.
    """
    if usuario.must_change_password:
        raise prohibido(
            "Debes cambiar tu contraseña antes de continuar.",
            code="password_change_required",
        )
    if usuario.role != ROLE_ADMIN or usuario.status != USER_ACTIVE:
        raise ApiError(404, "no_encontrado", "No se encontró el recurso.")
    return usuario


AdminDep = Annotated[User, Depends(usuario_admin)]
