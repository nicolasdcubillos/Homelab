"""Primitivas de seguridad: hashing de contraseñas y generación de tokens.

Este módulo no toca la base de datos ni FastAPI a propósito: es la capa más
baja y la más fácil de auditar. Todo lo que produce un valor secreto vive aquí.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

# Parámetros de argon2id. Son los de la RFC 9106 para el perfil de "segunda
# recomendación" (memoria moderada), apropiados para una VM pequeña: 64 MiB y
# 3 pasadas tardan del orden de 50-100 ms, suficiente para frenar fuerza bruta
# sin que un login se sienta lento.
_HASHER = PasswordHasher(
    time_cost=3,
    memory_cost=64 * 1024,  # KiB
    parallelism=2,
    hash_len=32,
    salt_len=16,
)

LONGITUD_MINIMA_PASSWORD = 10
LONGITUD_MAXIMA_PASSWORD = 1024

# Bytes de entropía de los tokens de sesión y CSRF. 32 bytes = 256 bits.
_BYTES_TOKEN = 32


class PasswordDebil(ValueError):
    """La contraseña no cumple la política mínima."""


def validar_password(password: str) -> None:
    """Valida la política de contraseñas. Lanza `PasswordDebil` con un mensaje
    en español apto para mostrarse directamente en la UI."""
    if not isinstance(password, str):
        raise PasswordDebil("La contraseña debe ser texto.")
    if len(password) < LONGITUD_MINIMA_PASSWORD:
        raise PasswordDebil(
            f"La contraseña debe tener al menos {LONGITUD_MINIMA_PASSWORD} caracteres."
        )
    # El tope evita un DoS: argon2 hashea la entrada completa.
    if len(password) > LONGITUD_MAXIMA_PASSWORD:
        raise PasswordDebil(
            f"La contraseña no puede superar los {LONGITUD_MAXIMA_PASSWORD} caracteres."
        )
    if password.strip() != password:
        raise PasswordDebil("La contraseña no puede empezar ni terminar con espacios.")
    if not re.search(r"[A-Za-z]", password):
        raise PasswordDebil("La contraseña debe incluir al menos una letra.")
    if not re.search(r"[0-9]", password):
        raise PasswordDebil("La contraseña debe incluir al menos un número.")


def hash_password(password: str) -> str:
    """Devuelve el hash argon2id de la contraseña, ya validada."""
    validar_password(password)
    return _HASHER.hash(password)


def verificar_password(hash_almacenado: str | None, password: str) -> bool:
    """Verifica una contraseña contra su hash.

    Devuelve False en vez de lanzar ante hashes inválidos o vacíos para que el
    endpoint de login trate igual "usuario inexistente" y "contraseña mala".
    """
    if not hash_almacenado:
        # Un usuario con la contraseña borrada (reset forzado) no puede entrar
        # con contraseña; igual gastamos tiempo para no revelarlo por latencia.
        _quemar_tiempo(password)
        return False
    try:
        _HASHER.verify(hash_almacenado, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
    return True


def necesita_rehash(hash_almacenado: str) -> bool:
    """True si el hash se generó con parámetros más débiles que los actuales."""
    try:
        return _HASHER.check_needs_rehash(hash_almacenado)
    except InvalidHashError:
        return True


# Hash de una contraseña arbitraria, calculado una sola vez, para gastar el
# mismo tiempo cuando el email no existe. Evita el oráculo de enumeración por
# diferencia de latencia entre "no existe" y "contraseña incorrecta".
_HASH_SEÑUELO = _HASHER.hash("contraseña-señuelo-que-nunca-coincide-0")


def _quemar_tiempo(password: str) -> None:
    try:
        _HASHER.verify(_HASH_SEÑUELO, password)
    except Exception:  # noqa: BLE001 - siempre falla; solo queremos el costo
        pass


def quemar_tiempo_de_verificacion(password: str = "") -> None:
    """Gasta el tiempo de un verify sin tener un usuario. Úsalo en login cuando
    el email no existe, para que la latencia no revele qué correos están dados
    de alta."""
    _quemar_tiempo(password)


def generar_token() -> str:
    """Token opaco para cookies de sesión y CSRF (URL-safe, 256 bits)."""
    return secrets.token_urlsafe(_BYTES_TOKEN)


def hash_token(token: str) -> str:
    """Hash del token de sesión tal como se guarda en la base.

    Se usa SHA-256 y no argon2 a propósito: el token ya es aleatorio de 256
    bits, así que no hay nada que "adivinar" y un hash lento se pagaría en cada
    petición. Lo que se busca es que un volcado de la base no permita
    suplantar sesiones vivas.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def tokens_iguales(a: str | None, b: str | None) -> bool:
    """Comparación en tiempo constante para tokens (CSRF, sesión)."""
    if not a or not b:
        return False
    return hmac.compare_digest(a, b)


def normalizar_email(email: str) -> str:
    """Normaliza el correo para que sirva de clave única.

    Solo se pasa a minúsculas y se recortan espacios. No se tocan los puntos ni
    los `+` de Gmail: dos correos que el servidor de correo considera distintos
    deben poder ser dos cuentas distintas.
    """
    return email.strip().lower()
