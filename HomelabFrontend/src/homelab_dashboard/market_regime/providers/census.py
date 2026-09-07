"""Tier medio explicitamente inactivo hasta verificar el contrato de series MRTS/M3."""

from .base import CollectionResult


def collect() -> CollectionResult:
    return CollectionResult(
        "census",
        "NO_CONFIGURADO",
        "MRTS/M3 no configurados: faltan parser y metadata verificados; cero solicitudes.",
    )
