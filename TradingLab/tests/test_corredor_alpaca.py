"""Contrato Alpaca sin SDK instalado, credenciales ni conexiones."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tradinglab.corredor import ErrorDeCorredor
from tradinglab.corredor_alpaca import AlpacaBloqueado, CorredorLumibot, MotorAlpaca


@pytest.mark.parametrize("estado", ["partial_fill", "fill_partial", "new", "closed", "filled"])
@pytest.mark.parametrize("lado", ["comprar", "vender"])
def test_ningun_estado_autoriza_envio_sin_conciliacion(estado, lado):
    sdk = Mock()
    sdk.submit_order.return_value = SimpleNamespace(
        status=estado,
        avg_fill_price=100.0,
        quantity=10,
        filled_quantity=2,
    )
    corredor = CorredorLumibot(sdk)
    for _ in range(2):
        with pytest.raises(AlpacaBloqueado, match="conciliación durable"):
            getattr(corredor, lado)("AAPL", 10)
    sdk.create_order.assert_not_called()
    sdk.submit_order.assert_not_called()


def test_motor_no_inicia_sesion_ni_reutiliza_broker_cerrado(monkeypatch):
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET", raising=False)
    tarea = Mock()
    motor = MotorAlpaca.desde_entorno()
    for _ in range(2):
        with pytest.raises(AlpacaBloqueado):
            motor.ejecutar(tarea)
        motor.cerrar()
    tarea.assert_not_called()
    assert not hasattr(motor, "_broker")


@pytest.mark.parametrize("valor", [None, float("nan"), float("inf"), -1, "ilegible"])
def test_efectivo_desconocido_no_se_sustituye_por_patrimonio(valor):
    sdk = Mock()
    sdk.get_cash.return_value = valor
    sdk.get_portfolio_value.return_value = 100_000
    with pytest.raises(ErrorDeCorredor, match="efectivo"):
        CorredorLumibot(sdk).efectivo()
    sdk.get_portfolio_value.assert_not_called()


def test_error_sdk_se_propaga_y_no_es_cero():
    sdk = Mock()
    sdk.get_cash.side_effect = TimeoutError("sin respuesta")
    with pytest.raises(TimeoutError):
        CorredorLumibot(sdk).efectivo()


def test_cero_efectivo_es_un_dato_valido():
    sdk = Mock()
    sdk.get_cash.return_value = 0
    assert CorredorLumibot(sdk).efectivo() == 0


def test_marco_invalido_no_cae_a_diario():
    sdk = Mock()
    with pytest.raises(ErrorDeCorredor, match="timeframe"):
        CorredorLumibot(sdk).cierres("AAPL", 60, "incorrecto")
    sdk.get_historical_prices.assert_not_called()


@pytest.mark.parametrize("precio", [None, 0, -1, float("nan"), float("inf")])
def test_no_se_inventan_precios(precio):
    sdk = Mock()
    sdk.get_last_price.return_value = precio
    with pytest.raises(ErrorDeCorredor):
        CorredorLumibot(sdk).precio("AAPL")
