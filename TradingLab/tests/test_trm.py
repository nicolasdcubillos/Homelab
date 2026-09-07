"""La TRM del día.

Nada de esto puede lanzar ni bloquear: una operación no se cae porque el portal
de datos abiertos esté lento. Los tests no salen a la red.
"""

from __future__ import annotations

from datetime import date

import pytest

from tradinglab.trm import ProveedorTRM, _a_float


@pytest.mark.parametrize(
    ("crudo", "esperado"),
    [
        ("3141.36", 3141.36),
        ("4,123.45", 4123.45),  # el portal a veces separa los miles
        (3141.36, 3141.36),
        (None, None),
        ("", None),
        ("no es un número", None),
        ("0", None),  # dividir por cero daría cifras absurdas en el panel
        ("-5", None),
    ],
)
def test_conversion_del_valor_publicado(crudo: object, esperado: float | None) -> None:
    resultado = _a_float(crudo)
    if esperado is None:
        assert resultado is None
    else:
        assert resultado == pytest.approx(esperado)


def test_se_consulta_una_sola_vez_al_dia(monkeypatch: pytest.MonkeyPatch) -> None:
    """La TRM cambia una vez al día; el supervisor late una vez por minuto.

    Sin caché serían más de mil llamadas diarias para el mismo número.
    """
    llamadas: list[dict] = []
    proveedor = ProveedorTRM()

    def falso(parametros: dict) -> float:
        llamadas.append(parametros)
        return 4000.0

    monkeypatch.setattr(proveedor, "_pedir", falso)
    hoy = date(2026, 9, 4)

    assert proveedor.obtener(hoy) == pytest.approx(4000.0)
    assert proveedor.obtener(hoy) == pytest.approx(4000.0)
    assert len(llamadas) == 1


def test_el_cambio_de_dia_vuelve_a_consultar(monkeypatch: pytest.MonkeyPatch) -> None:
    proveedor = ProveedorTRM()
    valores = iter([4000.0, 4100.0])
    monkeypatch.setattr(proveedor, "_pedir", lambda _p: next(valores))

    assert proveedor.obtener(date(2026, 9, 4)) == pytest.approx(4000.0)
    assert proveedor.obtener(date(2026, 9, 5)) == pytest.approx(4100.0)


def test_la_consulta_cubre_los_fines_de_semana(monkeypatch: pytest.MonkeyPatch) -> None:
    """La tasa de un viernes rige hasta el domingo.

    Por eso la consulta no es «la del día» sino «la que cubre el día»: pedir por
    fecha exacta devolvería vacío cada sábado.
    """
    parametros: list[dict] = []
    proveedor = ProveedorTRM()
    monkeypatch.setattr(proveedor, "_pedir", lambda p: (parametros.append(p), 4000.0)[1])

    proveedor.obtener(date(2026, 8, 30))  # domingo

    filtro = parametros[0]["$where"]
    assert "vigenciadesde <= '2026-08-30T00:00:00.000'" in filtro
    assert "vigenciahasta >= '2026-08-30T00:00:00.000'" in filtro


def test_si_no_hay_tasa_del_dia_se_usa_la_ultima(monkeypatch: pytest.MonkeyPatch) -> None:
    """La publicación puede tardar; la de ayer aproxima muchísimo mejor que nada."""
    proveedor = ProveedorTRM()
    respuestas = {"$where": None, "$order": 3900.0}

    def falso(parametros: dict) -> float | None:
        if "$where" in parametros:
            return respuestas["$where"]
        return respuestas["$order"]

    monkeypatch.setattr(proveedor, "_pedir", falso)

    assert proveedor.obtener(date(2026, 9, 4)) == pytest.approx(3900.0)


def test_sin_red_devuelve_none_y_no_reintenta_en_el_mismo_dia(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """En una VM sin salida a internet, reintentar en cada latido sería un timeout por minuto."""
    intentos: list[dict] = []
    proveedor = ProveedorTRM()

    def falso(parametros: dict) -> None:
        intentos.append(parametros)
        return None

    monkeypatch.setattr(proveedor, "_pedir", falso)
    hoy = date(2026, 9, 4)

    assert proveedor.obtener(hoy) is None
    assert proveedor.obtener(hoy) is None
    # Dos consultas en el primer intento (la del día y la última conocida), y
    # ninguna en el segundo.
    assert len(intentos) == 2


def test_una_respuesta_ilegible_no_revienta(monkeypatch: pytest.MonkeyPatch) -> None:
    class RespuestaFalsa:
        def read(self) -> bytes:
            return b"<html>mantenimiento</html>"

        def __enter__(self):
            return self

        def __exit__(self, *_: object) -> None:
            return None

    monkeypatch.setattr("urllib.request.urlopen", lambda *_a, **_k: RespuestaFalsa())

    assert ProveedorTRM().obtener(date(2026, 9, 4)) is None


def test_un_fallo_de_red_no_revienta(monkeypatch: pytest.MonkeyPatch) -> None:
    def explotar(*_a: object, **_k: object) -> None:
        raise OSError("la red no existe")

    monkeypatch.setattr("urllib.request.urlopen", explotar)

    assert ProveedorTRM().obtener(date(2026, 9, 4)) is None
