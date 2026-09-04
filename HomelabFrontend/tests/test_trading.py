"""Tests del módulo de trading: contrato de los motores y API compartida.

Los motores reales nunca se tocan aquí. `trading.py` expone el transporte HTTP
y el adaptador como puntos de inyección, igual que `watchers.py` hace con el
"entrypoint falso", así que la suite corre sin Freqtrade instalado y sin abrir
un solo socket.
"""

from __future__ import annotations

import pytest

from homelab_dashboard import trading
from homelab_dashboard.models import TRADING_MODES

CONFIG_VALIDA = {
    "instrumentos": ["BTC/USDT"],
    "estrategia": "MiEstrategia",
    "timeframe": "1h",
    "capital_simulado": 10000.0,
    "max_posiciones_abiertas": 3,
    "stop_loss_pct": 5.0,
    "take_profit_pct": 10.0,
    "max_perdida_diaria_pct": 8.0,
}


# ---------------------------------------------------------------------------
# Validación de configuración
# ---------------------------------------------------------------------------


def test_normaliza_instrumentos():
    """Mayúsculas y duplicados se resuelven antes de guardar."""
    limpia = trading.validar_config(
        trading.FREQTRADE, {**CONFIG_VALIDA, "instrumentos": ["btc/usdt", "BTC/USDT", "eth/usdt"]}
    )
    assert limpia["instrumentos"] == ["BTC/USDT", "ETH/USDT"]


def test_cada_motor_exige_su_propio_formato():
    """Un par de cripto no es un ticker de bolsa, y viceversa."""
    with pytest.raises(trading.ErrorDeConfig) as cripto:
        trading.validar_config(trading.FREQTRADE, {**CONFIG_VALIDA, "instrumentos": ["AAPL"]})
    assert "instrumentos" in cripto.value.campos

    with pytest.raises(trading.ErrorDeConfig) as acciones:
        trading.validar_config(
            trading.LUMIBOT, {**CONFIG_VALIDA, "instrumentos": ["BTC/USDT"], "timeframe": "1d"}
        )
    assert "instrumentos" in acciones.value.campos

    # Y cada uno acepta lo suyo.
    assert trading.validar_config(
        trading.LUMIBOT, {**CONFIG_VALIDA, "instrumentos": ["AAPL", "SPY"], "timeframe": "1d"}
    )["instrumentos"] == ["AAPL", "SPY"]


@pytest.mark.parametrize("clave", ["dry_run", "api_key", "api_secret", "trading_mode", "mode"])
def test_rechaza_claves_que_llevarian_a_dinero_real(clave):
    """Segunda capa de las tres que impiden operar con dinero real."""
    with pytest.raises(trading.ErrorDeConfig) as exc:
        trading.validar_config(trading.FREQTRADE, {**CONFIG_VALIDA, clave: False})
    assert clave in exc.value.campos


def test_stop_loss_no_puede_superar_el_freno_diario():
    """Si cada operación puede perder más que el tope del día, el tope no sirve."""
    with pytest.raises(trading.ErrorDeConfig) as exc:
        trading.validar_config(
            trading.FREQTRADE,
            {**CONFIG_VALIDA, "stop_loss_pct": 20.0, "max_perdida_diaria_pct": 5.0},
        )
    assert "max_perdida_diaria_pct" in exc.value.campos


def test_estrategia_no_admite_rutas():
    """El valor termina nombrando un archivo en la VM: nada de traversal."""
    with pytest.raises(trading.ErrorDeConfig) as exc:
        trading.validar_config(
            trading.FREQTRADE, {**CONFIG_VALIDA, "estrategia": "../../etc/passwd"}
        )
    assert "estrategia" in exc.value.campos


def test_tope_de_instrumentos():
    demasiados = [f"A{i}/USDT" for i in range(trading.FREQTRADE.max_instrumentos + 1)]
    with pytest.raises(trading.ErrorDeConfig) as exc:
        trading.validar_config(trading.FREQTRADE, {**CONFIG_VALIDA, "instrumentos": demasiados})
    assert "instrumentos" in exc.value.campos


def test_acumula_todos_los_errores_de_una_vez():
    """La UI debe poder pintar el formulario entero, no un error por intento."""
    with pytest.raises(trading.ErrorDeConfig) as exc:
        trading.validar_config(
            trading.FREQTRADE,
            {**CONFIG_VALIDA, "timeframe": "3s", "capital_simulado": 1, "estrategia": "9mala"},
        )
    assert set(exc.value.campos) >= {"timeframe", "capital_simulado", "estrategia"}


def test_config_freqtrade_fuerza_dry_run():
    """Tercera capa: aunque la config almacenada mintiera, el JSON no lo hace."""
    generada = trading.config_freqtrade(
        {**CONFIG_VALIDA, "dry_run": False}, estrategia_por_defecto="Defecto"
    )
    assert generada["dry_run"] is True
    assert generada["exchange"]["key"] == ""
    assert generada["exchange"]["secret"] == ""
    # El stop loss viaja negativo y en tanto por uno, como espera Freqtrade.
    assert generada["stoploss"] == pytest.approx(-0.05)


def test_solo_existe_el_modo_paper():
    """Si alguien añade un modo, este test le recuerda que hay que migrar."""
    assert TRADING_MODES == ("paper",)


# ---------------------------------------------------------------------------
# Adaptador de Freqtrade
# ---------------------------------------------------------------------------


class TransporteFalso:
    """Doble del transporte HTTP. Registra lo que se le pidió."""

    def __init__(self, respuestas: dict, *, falla: bool = False):
        self.respuestas = respuestas
        self.falla = falla
        self.llamadas: list[tuple[str, str]] = []

    def get(self, ruta, params=None):
        self.llamadas.append(("GET", ruta))
        if self.falla:
            raise trading.ErrorDeMotor("conexión rechazada")
        return self.respuestas[ruta]

    def post(self, ruta, cuerpo=None):
        self.llamadas.append(("POST", ruta))
        if self.falla:
            raise trading.ErrorDeMotor("conexión rechazada")
        return self.respuestas.get(ruta, {})


def _freqtrade(respuestas=None, **kw):
    base = {
        "show_config": {"state": "running", "dry_run": True, "version": "2024.1"},
        "status": [{"pair": "BTC/USDT"}],
    }
    return trading.AdaptadorFreqtrade(TransporteFalso({**base, **(respuestas or {})}, **kw))


def test_estado_freqtrade_corriendo():
    estado = _freqtrade().estado()
    assert estado.alcanzable and estado.corriendo
    assert estado.posiciones_abiertas == 1
    assert estado.version == "2024.1"


def test_estado_freqtrade_en_pausa():
    estado = _freqtrade({"show_config": {"state": "stopped", "dry_run": True}}).estado()
    assert estado.alcanzable and not estado.corriendo


def test_motor_caido_no_revienta():
    """Un motor apagado es información, no una excepción que tumbe la vista."""
    estado = _freqtrade(falla=True).estado()
    assert not estado.alcanzable and not estado.corriendo
    assert "no responde" in estado.detalle.lower()


def test_freqtrade_sin_dry_run_se_bloquea():
    """Si el motor dice que NO simula, se le trata como anomalía grave."""
    estado = _freqtrade({"show_config": {"state": "running", "dry_run": False}}).estado()
    assert not estado.corriendo
    assert estado.modo != trading.TRADING_MODE_PAPER
    assert "NO está en modo simulado" in estado.detalle


def test_status_caido_no_invalida_el_estado():
    """Que falle `/status` no debe borrar lo que ya dijo `/show_config`."""

    class TransporteParcial(TransporteFalso):
        def get(self, ruta, params=None):
            if ruta == "status":
                raise trading.ErrorDeMotor("timeout")
            return super().get(ruta, params)

    adaptador = trading.AdaptadorFreqtrade(
        TransporteParcial({"show_config": {"state": "running", "dry_run": True}})
    )
    estado = adaptador.estado()
    assert estado.alcanzable and estado.corriendo
    assert estado.posiciones_abiertas == 0


def test_encender_y_apagar_llaman_al_motor():
    adaptador = _freqtrade()
    adaptador.encender()
    adaptador.apagar()
    assert ("POST", "start") in adaptador.transporte.llamadas
    assert ("POST", "stop") in adaptador.transporte.llamadas


def test_operaciones_traduce_el_formato_de_freqtrade():
    adaptador = _freqtrade(
        {
            "trades": {
                "trades": [
                    {
                        "pair": "BTC/USDT",
                        "amount": 0.01,
                        "open_rate": 40000.0,
                        "close_rate": 44000.0,
                        "profit_abs": 40.0,
                        "profit_ratio": 0.1,
                        "open_date": "2024-01-01T00:00:00",
                        "close_date": "2024-01-02T00:00:00",
                    }
                ]
            }
        }
    )
    (op,) = adaptador.operaciones()
    assert op.instrumento == "BTC/USDT"
    assert op.lado == "compra"
    # El ratio de Freqtrade es tanto por uno; la UI habla en porcentaje.
    assert op.pnl_pct == pytest.approx(10.0)
    assert not op.abierta


def test_rendimiento_calcula_win_rate():
    adaptador = _freqtrade(
        {
            "profit": {
                "closed_trade_count": 4,
                "winning_trades": 3,
                "losing_trades": 1,
                "profit_closed_coin": 250.0,
            }
        }
    )
    datos = adaptador.rendimiento(10_000.0)
    assert datos.capital_actual == pytest.approx(10_250.0)
    assert datos.pnl_pct == pytest.approx(2.5)
    assert datos.win_rate == pytest.approx(0.75)


def test_rendimiento_vacio_no_divide_por_cero():
    assert trading.Rendimiento.vacio(1000.0).win_rate is None
