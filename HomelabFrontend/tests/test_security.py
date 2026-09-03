"""Tests de las primitivas de seguridad (hashing y tokens)."""

from __future__ import annotations

import pytest

from homelab_dashboard.security import (
    PasswordDebil,
    generar_token,
    hash_password,
    hash_token,
    normalizar_email,
    tokens_iguales,
    validar_password,
    verificar_password,
)


@pytest.mark.parametrize(
    "password",
    [
        "corta1",  # menos de 10
        "sinnumeros",  # sin dígitos
        "1234567890",  # sin letras
        " Contrasena123",  # espacio al inicio
        "Contrasena123 ",  # espacio al final
    ],
)
def test_passwords_rechazadas(password):
    with pytest.raises(PasswordDebil):
        validar_password(password)


def test_password_valida_pasa():
    validar_password("Contrasena123")


def test_password_larguisima_se_rechaza():
    """Sin tope, argon2 hashearía megabytes y sería un vector de DoS."""
    with pytest.raises(PasswordDebil):
        validar_password("a1" * 1000)


def test_hash_es_argon2id_y_verifica():
    h = hash_password("Contrasena123")
    assert h.startswith("$argon2id$")
    assert verificar_password(h, "Contrasena123")
    assert not verificar_password(h, "Contrasena124")


def test_hashes_de_la_misma_password_son_distintos():
    """Si dos hashes iguales delatan contraseñas iguales, falta la sal."""
    assert hash_password("Contrasena123") != hash_password("Contrasena123")


def test_verificar_con_hash_vacio_o_corrupto_no_lanza():
    assert not verificar_password(None, "loquesea")
    assert not verificar_password("", "loquesea")
    assert not verificar_password("no-es-un-hash", "loquesea")


def test_tokens_son_unicos_y_largos():
    tokens = {generar_token() for _ in range(200)}
    assert len(tokens) == 200
    assert all(len(t) >= 40 for t in tokens)


def test_hash_token_es_estable_y_no_reversible():
    token = generar_token()
    assert hash_token(token) == hash_token(token)
    assert token not in hash_token(token)
    assert len(hash_token(token)) == 64


def test_tokens_iguales_maneja_vacios():
    assert not tokens_iguales(None, "x")
    assert not tokens_iguales("x", None)
    assert not tokens_iguales("", "")
    assert tokens_iguales("abc", "abc")


def test_normalizar_email_baja_a_minusculas_y_recorta():
    assert normalizar_email("  Nico@Ejemplo.COM ") == "nico@ejemplo.com"


def test_normalizar_email_conserva_puntos_y_mas():
    """Dos direcciones que el servidor de correo distingue deben poder ser
    dos cuentas distintas; no se aplican reglas de Gmail."""
    assert normalizar_email("a.b+tag@gmail.com") == "a.b+tag@gmail.com"
