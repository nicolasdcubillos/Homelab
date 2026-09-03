"""Errores de la API con envoltura uniforme.

Todas las respuestas de error de `/api/v1` tienen la misma forma:

    {"error": {"code": "credenciales_invalidas", "message": "..."}}

El `code` es estable y lo consume la SPA para decidir a dónde redirigir (por
ejemplo `password_change_required`); el `message` está en español y es apto
para mostrarse tal cual al usuario.
"""

from __future__ import annotations

from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class ApiError(Exception):
    """Error de negocio que se traduce a una respuesta JSON uniforme."""

    def __init__(self, status_code: int, code: str, message: str, **extra) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.extra = extra

    def to_response(self) -> JSONResponse:
        cuerpo = {"error": {"code": self.code, "message": self.message, **self.extra}}
        return JSONResponse(cuerpo, status_code=self.status_code)


def no_autenticado(mensaje: str = "Necesitas iniciar sesión.") -> ApiError:
    return ApiError(status.HTTP_401_UNAUTHORIZED, "no_autenticado", mensaje)


def prohibido(mensaje: str, code: str = "prohibido") -> ApiError:
    return ApiError(status.HTTP_403_FORBIDDEN, code, mensaje)


def no_encontrado(mensaje: str = "No se encontró el recurso.") -> ApiError:
    return ApiError(status.HTTP_404_NOT_FOUND, "no_encontrado", mensaje)


def conflicto(mensaje: str, code: str = "conflicto") -> ApiError:
    return ApiError(status.HTTP_409_CONFLICT, code, mensaje)


def solicitud_invalida(mensaje: str, code: str = "solicitud_invalida") -> ApiError:
    return ApiError(status.HTTP_400_BAD_REQUEST, code, mensaje)


def error_de_validacion(
    campos: dict[str, str], mensaje: str = "Revisa los datos del formulario."
) -> ApiError:
    """Error de validación que no puede expresarse en el esquema.

    Sale con la misma forma que los de Pydantic (`fields` por campo) para que
    la SPA los pinte junto al input sin distinguir el origen.
    """
    return ApiError(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "validacion",
        mensaje,
        fields=campos,
    )


# Mensajes en español para los errores de validación más comunes de Pydantic,
# para no filtrar textos en inglés a una UI que es toda en español.
_TRADUCCIONES = {
    "missing": "Este campo es obligatorio.",
    "string_too_short": "El valor es demasiado corto.",
    "string_too_long": "El valor es demasiado largo.",
    "value_error": "El valor no es válido.",
    "int_parsing": "Debe ser un número entero.",
    "float_parsing": "Debe ser un número.",
    "bool_parsing": "Debe ser verdadero o falso.",
    "greater_than": "El valor es demasiado pequeño.",
    "greater_than_equal": "El valor es demasiado pequeño.",
    "less_than": "El valor es demasiado grande.",
    "less_than_equal": "El valor es demasiado grande.",
    "too_short": "Faltan elementos en la lista.",
    "too_long": "La lista tiene demasiados elementos.",
    "string_pattern_mismatch": "El formato no es válido.",
    "enum": "El valor no es una de las opciones permitidas.",
}


def _campo(loc: tuple) -> str:
    """Nombre del campo tal como lo espera react-hook-form (sin 'body')."""
    partes = [str(p) for p in loc if p not in ("body", "query", "path")]
    return ".".join(partes) or "_"


def registrar_manejadores(app) -> None:
    """Instala los manejadores de error en la app de FastAPI."""

    @app.exception_handler(ApiError)
    async def _api_error(_request: Request, exc: ApiError):
        return exc.to_response()

    @app.exception_handler(RequestValidationError)
    async def _validacion(request: Request, exc: RequestValidationError):
        if not request.url.path.startswith("/api/"):
            # La UI Jinja heredada conserva el comportamiento por defecto.
            return JSONResponse({"detail": exc.errors()}, status_code=422)
        campos: dict[str, str] = {}
        for error in exc.errors():
            nombre = _campo(error.get("loc", ()))
            mensaje = error.get("msg") or ""
            tipo = error.get("type", "")
            if tipo in _TRADUCCIONES:
                mensaje = _TRADUCCIONES[tipo]
            elif mensaje.startswith("Value error, "):
                # Los validadores propios ya escriben en español.
                mensaje = mensaje[len("Value error, ") :]
            campos.setdefault(nombre, mensaje)
        return JSONResponse(
            {
                "error": {
                    "code": "validacion",
                    "message": "Revisa los datos del formulario.",
                    "fields": campos,
                }
            },
            status_code=422,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        if not request.url.path.startswith("/api/"):
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        codigos = {
            400: "solicitud_invalida",
            401: "no_autenticado",
            403: "prohibido",
            404: "no_encontrado",
            405: "metodo_no_permitido",
            409: "conflicto",
            429: "demasiadas_peticiones",
        }
        return JSONResponse(
            {
                "error": {
                    "code": codigos.get(exc.status_code, "error"),
                    "message": str(exc.detail),
                }
            },
            status_code=exc.status_code,
            headers=getattr(exc, "headers", None),
        )
