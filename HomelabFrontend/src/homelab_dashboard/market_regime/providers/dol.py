"""No convierte el comunicado semanal de claims en una API inexistente."""

from .base import CollectionResult


def collect() -> CollectionResult:
    return CollectionResult(
        "dol",
        "NO_CONFIGURADO",
        "Claims no configurado: falta parser publico verificado; cero solicitudes.",
    )
