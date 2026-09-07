"""Las decisiones puras: indicadores y estrategias.

Sin base de datos, sin red y sin corredor. Si algo de esto falla, falla la
aritmética, no la integración.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tradinglab.estrategia import (
    DISPONIBLES,
    POR_DEFECTO,
    CruceDeMedias,
    ReversionRSI,
    construir,
    media_simple,
    rsi,
)

# ---------------------------------------------------------------------------
# Indicadores
# ---------------------------------------------------------------------------


def test_media_simple() -> None:
    assert media_simple([1, 2, 3, 4], 2) == pytest.approx(3.5)
    assert media_simple([1, 2, 3, 4], 4) == pytest.approx(2.5)


def test_media_simple_sin_datos_suficientes_no_inventa() -> None:
    """Devolver `None` y no una media parcial.

    Una media de 50 calculada sobre 10 velas no es una media de 50: es otro
    indicador con el mismo nombre, y la estrategia decidiría con él sin saberlo.
    """
    assert media_simple([1, 2], 5) is None
    assert media_simple([1, 2], 0) is None


def test_rsi_en_una_subida_perfecta_es_cien() -> None:
    """Sin una sola bajada no hay cociente que calcular."""
    assert rsi(list(range(1, 40)), 14) == pytest.approx(100.0)


def test_rsi_en_una_bajada_perfecta_es_cero() -> None:
    assert rsi(list(range(40, 1, -1)), 14) == pytest.approx(0.0)


def test_rsi_en_un_mercado_equilibrado_ronda_cincuenta() -> None:
    dientes = [100 + (1 if indice % 2 else -1) for indice in range(40)]
    valor = rsi(dientes, 14)
    assert valor is not None
    assert 40 < valor < 60


def test_rsi_sin_datos_suficientes() -> None:
    assert rsi([1, 2, 3], 14) is None
    assert rsi(list(range(20)), 0) is None


# ---------------------------------------------------------------------------
# Cruce de medias
# ---------------------------------------------------------------------------


def _serie_con_cruce_alcista() -> list[float]:
    """Precios planos que despegan al final: la rápida cruza a la lenta hacia arriba."""
    planos = [100.0] * 55
    return [*planos, 130.0]


def _serie_con_cruce_bajista() -> list[float]:
    planos = [100.0] * 55
    return [*planos, 40.0]


def test_el_cruce_alcista_manda_entrar() -> None:
    estrategia = CruceDeMedias(ventana_rapida=3, ventana_lenta=10)
    serie = [100.0] * 12 + [140.0]

    senal = estrategia.evaluar(serie, con_posicion=False)

    assert senal.quiere_entrar
    assert "cruzó por encima" in senal.motivo


def test_el_cruce_bajista_manda_salir_solo_si_hay_posicion() -> None:
    estrategia = CruceDeMedias(ventana_rapida=3, ventana_lenta=10)
    serie = [100.0] * 12 + [40.0]

    assert estrategia.evaluar(serie, con_posicion=True).quiere_salir
    # Sin posición, un cruce bajista no es una orden de nada: TradingLab no
    # abre cortos.
    assert not estrategia.evaluar(serie, con_posicion=False).quiere_entrar


def test_una_tendencia_ya_establecida_no_vuelve_a_disparar() -> None:
    """La razón de ser de mirar la vela anterior.

    Sin comparar con el paso previo, un mercado que lleva semanas alcista
    emitiría una orden de compra en cada ciclo y el bot compraría lo mismo una y
    otra vez.
    """
    estrategia = CruceDeMedias(ventana_rapida=3, ventana_lenta=10)
    subida_sostenida = [100.0 + indice * 5 for indice in range(30)]

    senal = estrategia.evaluar(subida_sostenida, con_posicion=False)

    assert not senal.quiere_entrar


def test_sin_historia_suficiente_se_abstiene() -> None:
    estrategia = CruceDeMedias()

    assert estrategia.velas_necesarias == 51
    assert not estrategia.evaluar([100.0] * 10, con_posicion=False).quiere_entrar


def test_ventanas_incoherentes_no_se_construyen() -> None:
    with pytest.raises(ValueError, match="ventana rápida"):
        CruceDeMedias(ventana_rapida=50, ventana_lenta=20)


def test_series_de_ejemplo_del_cruce() -> None:
    estrategia = CruceDeMedias()

    assert estrategia.evaluar(_serie_con_cruce_alcista(), con_posicion=False).quiere_entrar
    assert estrategia.evaluar(_serie_con_cruce_bajista(), con_posicion=True).quiere_salir


# ---------------------------------------------------------------------------
# Reversión a la media
# ---------------------------------------------------------------------------


def test_la_sobreventa_manda_entrar() -> None:
    estrategia = ReversionRSI()
    cayendo = [100.0 - indice for indice in range(20)]

    senal = estrategia.evaluar(cayendo, con_posicion=False)

    assert senal.quiere_entrar
    assert "sobreventa" in senal.motivo


def test_la_sobrecompra_manda_salir() -> None:
    estrategia = ReversionRSI()
    subiendo = [100.0 + indice for indice in range(20)]

    assert estrategia.evaluar(subiendo, con_posicion=True).quiere_salir
    # Estando fuera, la sobrecompra no es una invitación a entrar.
    assert not estrategia.evaluar(subiendo, con_posicion=False).quiere_entrar


def test_umbrales_incoherentes_no_se_construyen() -> None:
    with pytest.raises(ValueError, match="umbrales"):
        ReversionRSI(umbral_compra=80.0, umbral_venta=30.0)


# ---------------------------------------------------------------------------
# Resolución de nombres
# ---------------------------------------------------------------------------


def test_el_nombre_vacio_da_la_estrategia_por_defecto_sin_avisos() -> None:
    estrategia, aviso = construir("")

    assert estrategia.nombre == POR_DEFECTO
    assert aviso == ""


def test_un_nombre_desconocido_no_opera_otra_estrategia() -> None:
    with pytest.raises(ValueError, match="no existe"):
        construir("cruze_de_meidas")


@pytest.mark.parametrize("nombre", sorted(DISPONIBLES))
def test_todas_las_disponibles_se_resuelven(nombre: str) -> None:
    estrategia, aviso = construir(nombre)

    assert estrategia.nombre == nombre
    assert aviso == ""


def test_los_identificadores_son_tecleables_en_el_celular() -> None:
    """El campo del dashboard se valida como identificador y se escribe a mano.

    Minúsculas y guion bajo evitan que una mayúscula perdida deje el bot
    operando con la estrategia por defecto sin que nadie entienda por qué.
    """
    for nombre, estrategia in DISPONIBLES.items():
        assert nombre.islower()
        assert nombre.replace("_", "").isalnum()
        assert estrategia.etiqueta and estrategia.etiqueta != nombre


def test_el_catalogo_coincide_con_el_que_ofrece_el_dashboard() -> None:
    """Lee la declaración real sin instalar las dependencias del dashboard."""
    ruta = (
        Path(__file__).resolve().parents[2]
        / "HomelabFrontend"
        / "src"
        / "homelab_dashboard"
        / "trading.py"
    )
    arbol = ast.parse(ruta.read_text(encoding="utf-8"))
    declaracion = next(
        nodo.value
        for nodo in arbol.body
        if isinstance(nodo, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "_ESTRATEGIAS_LUMIBOT" for t in nodo.targets)
    )
    assert isinstance(declaracion, ast.Tuple)
    publicado = {}
    for entrada in declaracion.elts:
        assert isinstance(entrada, ast.Call)
        campos = {
            campo.arg: ast.literal_eval(campo.value)
            for campo in entrada.keywords
            if campo.arg in {"nombre", "etiqueta"}
        }
        publicado[campos["nombre"]] = campos["etiqueta"]
    assert {nombre: estrategia.etiqueta for nombre, estrategia in DISPONIBLES.items()} == publicado
