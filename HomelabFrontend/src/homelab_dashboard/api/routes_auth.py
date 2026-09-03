"""Rutas de autenticación: `/api/v1/auth/*`."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

from .. import auth
from ..models import ROLE_ADMIN, ROLE_USER, USER_ACTIVE, USER_PENDING
from . import schemas
from .deps import (
    COOKIE_CSRF,
    ContextoDep,
    DbDep,
    SesionOpcionalDep,
    SettingsDep,
    UsuarioDep,
    borrar_cookies_de_sesion,
    fijar_cookies_de_sesion,
    ip_del_cliente,
    verificar_csrf,
)
from .errors import ApiError, conflicto, no_autenticado, solicitud_invalida

router = APIRouter(prefix="/auth", tags=["auth"])


def _a_salida(usuario) -> schemas.UsuarioOut:
    return schemas.UsuarioOut.model_validate(usuario)


def _traducir(exc: auth.ErrorDeAuth) -> ApiError:
    """Mapea los errores del servicio de auth a códigos HTTP."""
    if isinstance(exc, auth.EmailYaRegistrado):
        return conflicto(exc.mensaje, code=exc.codigo)
    if isinstance(exc, auth.CuentaBloqueada):
        return ApiError(429, exc.codigo, exc.mensaje)
    if isinstance(exc, auth.CuentaSuspendida):
        return ApiError(403, exc.codigo, exc.mensaje)
    if isinstance(exc, auth.CredencialesInvalidas):
        return ApiError(401, exc.codigo, exc.mensaje)
    return solicitud_invalida(exc.mensaje, code=exc.codigo)


@router.post("/register", response_model=schemas.RegistroOut, status_code=201)
def registrar(datos: schemas.RegistroIn, db: DbDep, settings: SettingsDep):
    """Alta abierta. El usuario nace `pending` y no puede ejecutar nada hasta
    que un administrador lo active.

    Excepción: si la instalación está vacía, el primer registro se convierte en
    admin activo. Evita que una instalación recién desplegada quede sin nadie
    que pueda aprobar a nadie.
    """
    primera_cuenta = not auth.hay_algun_usuario(db)
    try:
        usuario = auth.crear_usuario(
            db,
            email=datos.email,
            password=datos.password,
            role=ROLE_ADMIN if primera_cuenta else ROLE_USER,
            status=USER_ACTIVE if primera_cuenta else USER_PENDING,
            timezone=datos.timezone or settings.default_timezone,
        )
    except auth.ErrorDeAuth as exc:
        raise _traducir(exc) from exc

    mensaje = (
        "Cuenta creada como administrador. Ya puedes iniciar sesión."
        if primera_cuenta
        else "Cuenta creada. Un administrador debe aprobarla antes de que puedas usarla."
    )
    return schemas.RegistroOut(user=_a_salida(usuario), mensaje=mensaje)


@router.post("/login", response_model=schemas.SesionOut)
def login(
    datos: schemas.LoginIn,
    request: Request,
    response: Response,
    db: DbDep,
    settings: SettingsDep,
):
    try:
        sesion = auth.autenticar(
            db,
            settings,
            email=datos.email,
            password=datos.password,
            ip=ip_del_cliente(request),
            user_agent=request.headers.get("user-agent"),
        )
    except auth.ErrorDeAuth as exc:
        # El commit del intento fallido ya ocurrió dentro de `autenticar`: el
        # contador de bloqueo tiene que sobrevivir al rollback de `get_db`.
        raise _traducir(exc) from exc

    fijar_cookies_de_sesion(response, settings, sesion)
    return schemas.SesionOut(user=_a_salida(sesion.user), csrf_token=sesion.csrf_token)


@router.post("/logout", response_model=schemas.OkOut)
def logout(
    request: Request,
    response: Response,
    db: DbDep,
    settings: SettingsDep,
    contexto: SesionOpcionalDep,
):
    """Cierra la sesión actual. Es idempotente: sin sesión también responde OK
    y limpia las cookies, para que la SPA pueda 'salir' de un estado roto."""
    if contexto is not None:
        sesion, _usuario = contexto
        # El CSRF solo se exige si hay sesión que proteger.
        verificar_csrf(request, contexto)
        auth.cerrar_sesion(db, sesion)
    borrar_cookies_de_sesion(response, settings)
    return schemas.OkOut(mensaje="Sesión cerrada.")


@router.get("/me", response_model=schemas.SesionOut)
def yo(contexto: ContextoDep):
    """Usuario en sesión. Es la primera llamada de la SPA al arrancar."""
    sesion, usuario = contexto
    return schemas.SesionOut(user=_a_salida(usuario), csrf_token=sesion.csrf_token)


@router.get("/csrf", response_model=schemas.CsrfOut)
def csrf(contexto: SesionOpcionalDep, response: Response, settings: SettingsDep):
    """Devuelve el token CSRF de la sesión actual y reafirma la cookie.

    Existe para que la SPA se recupere si el usuario borró solo la cookie
    legible, sin obligarlo a volver a entrar.
    """
    if contexto is None:
        raise no_autenticado()
    sesion, _usuario = contexto
    response.set_cookie(
        COOKIE_CSRF,
        sesion.csrf_token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=False,
        secure=settings.secure_cookies,
        samesite="lax",
        path="/",
    )
    return schemas.CsrfOut(csrf_token=sesion.csrf_token)


@router.post("/password", response_model=schemas.OkOut)
def cambiar_password(
    datos: schemas.CambioPasswordIn,
    db: DbDep,
    contexto: ContextoDep,
    usuario: UsuarioDep,
):
    """Cambio de contraseña propio.

    Si el usuario venía de un reset forzado por un admin, no se le pide la
    contraseña anterior (no la conoce). En cualquier otro caso sí.
    """
    sesion, _ = contexto
    exigir_actual = not usuario.must_change_password
    try:
        auth.cambiar_password(
            db,
            usuario=usuario,
            password_actual=datos.password_actual,
            password_nueva=datos.password_nueva,
            exigir_actual=exigir_actual,
        )
    except auth.ErrorDeAuth as exc:
        raise _traducir(exc) from exc

    # Cambiar la contraseña expulsa al resto de dispositivos, pero no a este.
    auth.revocar_sesiones_de(db, usuario.id, excepto=sesion.id)
    return schemas.OkOut(mensaje="Contraseña actualizada.")


@router.put("/profile", response_model=schemas.UsuarioOut)
def actualizar_perfil(datos: schemas.PerfilIn, usuario: UsuarioDep):
    """Ajustes de la propia cuenta que no son credenciales."""
    usuario.timezone = datos.timezone
    return _a_salida(usuario)
