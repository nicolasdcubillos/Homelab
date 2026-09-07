"""Tests del módulo de trading: contrato de los motores y API compartida.

Los motores reales nunca se tocan aquí. `trading.py` expone el transporte HTTP
y el adaptador como puntos de inyección, igual que `watchers.py` hace con el
"entrypoint falso", así que la suite corre sin Freqtrade instalado y sin abrir
un solo socket.
"""

from __future__ import annotations

import datetime as dt
import importlib
import sqlite3
from pathlib import Path

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

    # Y cada uno acepta lo suyo. LUMIBOT exige además una estrategia de su
    # catálogo: `CONFIG_VALIDA` trae un nombre libre, que solo vale en Freqtrade.
    assert trading.validar_config(
        trading.LUMIBOT,
        {
            **CONFIG_VALIDA,
            "instrumentos": ["AAPL", "SPY"],
            "timeframe": "1d",
            "estrategia": "cruce_medias",
        },
    )["instrumentos"] == ["AAPL", "SPY"]


@pytest.mark.parametrize("clave", ["dry_run", "api_key", "api_secret", "trading_mode", "mode"])
def test_rechaza_claves_que_llevarian_a_dinero_real(clave):
    """La configuración compartida no permite seleccionar ejecución real."""
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


def test_un_motor_con_catalogo_rechaza_lo_que_no_esta_en_el():
    """Aceptar un nombre desconocido haría que el bot operase con otra cosa."""
    valida = {**CONFIG_VALIDA, "instrumentos": ["AAPL"]}
    with pytest.raises(trading.ErrorDeConfig) as exc:
        trading.validar_config(trading.LUMIBOT, {**valida, "estrategia": "no_existe"})
    assert "estrategia" in exc.value.campos
    # El mensaje tiene que decir cuáles sí valen: se lee en un celular, sin docs.
    assert "cruce_medias" in exc.value.campos["estrategia"]


def test_un_motor_con_catalogo_acepta_los_suyos_y_el_vacio():
    valida = {**CONFIG_VALIDA, "instrumentos": ["AAPL"]}
    for nombre in ("", *(e.nombre for e in trading.LUMIBOT.estrategias)):
        limpia = trading.validar_config(trading.LUMIBOT, {**valida, "estrategia": nombre})
        assert limpia["estrategia"] == nombre


def test_un_motor_sin_catalogo_sigue_aceptando_texto_libre():
    """Las estrategias de Freqtrade son archivos en la VM: no se pueden listar."""
    assert not trading.FREQTRADE.estrategias
    limpia = trading.validar_config(trading.FREQTRADE, {**CONFIG_VALIDA, "estrategia": "MiClase"})
    assert limpia["estrategia"] == "MiClase"


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
    """El borrador fuerza PAPER, pero generarlo no prueba que se haya aplicado."""
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
        "status": [{
            "pair": "BTC/USDT", "amount": 0.01, "open_rate": 40000,
            "open_date": "2024-01-03T00:00:00", "close_date": None,
        }],
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
    assert estado.posiciones_abiertas is None


def test_freqtrade_no_arranca_sin_aplicacion_verificada():
    adaptador = _freqtrade()
    with pytest.raises(trading.ErrorDeMotor):
        adaptador.encender()
    adaptador.apagar()
    assert ("POST", "start") not in adaptador.transporte.llamadas
    assert ("POST", "stop") in adaptador.transporte.llamadas


def test_operaciones_traduce_el_formato_de_freqtrade():
    adaptador = _freqtrade(
        {
            "status": [],
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
                "starting_balance": 10_000.0,
            }
        }
    )
    datos = adaptador.rendimiento(10_000.0)
    assert datos.capital_actual == pytest.approx(10_250.0)
    assert datos.pnl_pct == pytest.approx(2.5)
    assert datos.win_rate == pytest.approx(0.75)


def test_rendimiento_vacio_no_divide_por_cero():
    assert trading.Rendimiento.vacio(1000.0).win_rate is None


@pytest.mark.parametrize("campo,valor", [
    ("capital_simulado", True), ("stop_loss_pct", False),
    ("max_posiciones_abiertas", True), ("max_posiciones_abiertas", 1.8),
    ("max_posiciones_abiertas", float("inf")), ("capital_simulado", float("nan")),
    ("instrumentos", [None]), ("instrumentos", [123]), ("estrategia", None),
    ("campo_desconocido", {"dry_run": False}),
])
def test_validacion_no_convierte_datos_invalidos(campo, valor):
    with pytest.raises(trading.ErrorDeConfig) as exc:
        trading.validar_config(trading.FREQTRADE, {**CONFIG_VALIDA, campo: valor})
    assert campo in exc.value.campos


@pytest.mark.parametrize("dry_run", [False, None, 0, 1, "true", "false"])
def test_freqtrade_exige_confirmacion_paper_literal(dry_run):
    adaptador = _freqtrade({"show_config": {"state": "running", "dry_run": dry_run}})
    assert adaptador.estado().estado == "bloqueado"
    for accion in (adaptador.apagar, adaptador.operaciones, lambda: adaptador.rendimiento(10000)):
        with pytest.raises(trading.ErrorDeMotor):
            accion()
    assert not any(metodo == "POST" for metodo, _ in adaptador.transporte.llamadas)


@pytest.mark.parametrize("respuesta", [[], None, {}, {"state": "running"}])
def test_freqtrade_respuesta_incompleta_no_es_paper(respuesta):
    assert _freqtrade({"show_config": respuesta}).estado().modo == "desconocido"


def test_freqtrade_estado_nuevo_no_se_confunde_con_pausa():
    estado = _freqtrade({"show_config": {"state": "reload_config", "dry_run": True}}).estado()
    assert estado.estado == "desconocido"
    assert not estado.corriendo


def test_operaciones_freqtrade_incluyen_abiertas():
    operaciones = _freqtrade({"trades": {"trades": []}}).operaciones()
    assert len(operaciones) == 1
    assert operaciones[0].abierta


@pytest.mark.parametrize("respuesta", [{}, [], {"trades": [None]}])
def test_operaciones_freqtrade_malformadas_no_son_lista_vacia(respuesta):
    with pytest.raises(trading.ErrorDeMotor):
        _freqtrade({"trades": respuesta}).operaciones()


def test_rendimiento_freqtrade_no_inventa_capital_aplicado():
    with pytest.raises(trading.ErrorDeMotor):
        _freqtrade({"profit": {"closed_trade_count": 0}}).rendimiento(50000)


@pytest.fixture()
def fuente_tradinglab(monkeypatch):
    """Importa el productor REAL del monorepo, no otro catálogo hardcodeado."""
    raiz = Path(__file__).resolve().parents[2] / "TradingLab" / "src"
    monkeypatch.syspath_prepend(str(raiz))
    modulos = {
        nombre: importlib.import_module(f"tradinglab.{nombre}")
        for nombre in ("config", "estrategia", "estado")
    }
    assert all(Path(modulo.__file__).is_relative_to(raiz) for modulo in modulos.values())
    return modulos


def test_catalogo_contra_fuente_real_tradinglab(fuente_tradinglab):
    config = fuente_tradinglab["config"]
    estrategia = fuente_tradinglab["estrategia"]
    assert trading.LUMIBOT.bot_name == config.BOT_NAME
    assert trading.TRADING_MODE_PAPER == config.MODO_PAPER
    assert trading.LUMIBOT.max_instrumentos == config.MAX_INSTRUMENTOS
    assert trading.LUMIBOT.timeframes == tuple(config.SEGUNDOS_POR_TIMEFRAME)
    assert trading.CONFIG_POR_DEFECTO == config.VALORES_POR_DEFECTO
    assert {e.nombre: e.etiqueta for e in trading.LUMIBOT.estrategias} == {
        nombre: spec.etiqueta for nombre, spec in estrategia.DISPONIBLES.items()
    }
    for nombre in ("", *estrategia.DISPONIBLES):
        limpia = trading.validar_config(trading.LUMIBOT, {
            **trading.CONFIG_POR_DEFECTO, "instrumentos": ["AAPL"], "estrategia": nombre,
        })
        assert estrategia.construir(limpia["estrategia"])[0] is not None


@pytest.fixture()
def almacen_tradinglab(fuente_tradinglab, tmp_path):
    with fuente_tradinglab["estado"].AlmacenEstado(tmp_path / "estado # paper.sqlite") as almacen:
        almacen.vincular("simulado")
        almacen.restaurar_simulacion(10000)
        yield almacen


@pytest.mark.parametrize("habilitado,observado,corriendo", [
    (True, "pausado", False), (False, "operando", True),
    (True, "error", False), (True, "bloqueado", False),
    (True, "desconocido", False), (True, "esperando", False),
])
def test_latido_no_confunde_intencion_con_observacion(
    almacen_tradinglab, habilitado, observado, corriendo
):
    almacen_tradinglab.latir(
        detalle="Detalle que nunca debe ocultarse", estado=observado, modo="simulado",
        config_version=3, posiciones_abiertas=2,
    )
    estado = trading.AdaptadorTradingLab(
        almacen_tradinglab.db_path, habilitado=habilitado
    ).estado()
    assert estado.alcanzable
    assert estado.corriendo is corriendo
    assert estado.config_version == 3
    assert "Detalle que nunca debe ocultarse" in estado.detalle


@pytest.mark.parametrize("marca", [
    "", "ayer", "2026-01-01T00:00:00", "2999-01-01T00:00:00+00:00",
    "2000-01-01T00:00:00+00:00",
])
def test_latido_ilegible_o_viejo_falla_cerrado(marca):
    assert not trading._latido_fresco(marca, 3)


def test_latido_obsoleto_no_publica_posiciones_vigentes(almacen_tradinglab):
    almacen_tradinglab.latir(
        detalle="Último ciclo", estado="operando", modo="simulado", config_version=3,
        posiciones_abiertas=7,
        momento=(trading.utcnow() - dt.timedelta(minutes=4)).isoformat(),
    )
    estado = trading.AdaptadorTradingLab(almacen_tradinglab.db_path, habilitado=True).estado()
    assert not estado.alcanzable and not estado.corriendo
    assert estado.estado == "stale"
    assert estado.posiciones_abiertas is None
    assert "Último ciclo" in estado.detalle


def test_estado_legacy_no_infiere_ejecucion(tmp_path):
    ruta = tmp_path / "legacy.sqlite"
    with sqlite3.connect(ruta) as conexion:
        conexion.execute(
            "CREATE TABLE estado_motor (latido_en TEXT, detalle TEXT, "
            "posiciones_abiertas INTEGER, version TEXT)"
        )
        conexion.execute(
            "INSERT INTO estado_motor VALUES (?, 'Error de configuración', 0, 'anterior')",
            (trading.utcnow().isoformat(),),
        )
    estado = trading.AdaptadorTradingLab(ruta, habilitado=True).estado()
    assert estado.alcanzable and not estado.corriendo
    assert estado.estado == "desconocido"
    assert estado.config_version is None
    assert "Error de configuración" in estado.detalle


@pytest.mark.parametrize("observado", [
    "pausado", "operando", "error", "bloqueado", "detenido", "esperando",
])
def test_alpaca_preserva_observacion_sin_confirmar_ejecucion(almacen_tradinglab, observado):
    almacen_tradinglab.latir(
        detalle="Detalle del productor", estado=observado, modo="alpaca_paper",
        version="tradinglab prueba", config_version=8, posiciones_abiertas=3,
    )
    estado = trading.AdaptadorTradingLab(almacen_tradinglab.db_path, habilitado=True).estado()
    assert estado.estado == observado
    assert estado.alcanzable is (observado != "detenido")
    assert estado.modo == "paper"
    assert not estado.corriendo
    assert estado.config_version == 8
    assert estado.version == "tradinglab prueba"
    assert estado.posiciones_abiertas == 3
    assert estado.latido_en
    assert "Detalle del productor" in estado.detalle
    assert "Alpaca Paper está bloqueado preventivamente" in estado.detalle


def test_adaptador_lee_operaciones_reales_y_capital_durable(
    almacen_tradinglab, fuente_tradinglab
):
    apertura = fuente_tradinglab["estado"].Apertura(
        instrumento="AAPL", lado="compra", cantidad=2, precio_entrada=100, costos=1,
    )
    identificador = almacen_tradinglab.registrar_apertura(apertura)
    almacen_tradinglab.registrar_cierre(identificador, precio_salida=110, costos_salida=1)
    adaptador = trading.AdaptadorTradingLab(almacen_tradinglab.db_path)
    assert adaptador.operaciones()[0].pnl_absoluto == pytest.approx(18)
    resultado = adaptador.rendimiento(999999)
    assert resultado.capital_inicial == 10000
    assert resultado.capital_actual == 10018
    assert resultado.costos_simulados == 2


def test_estado_sqlite_corrupto_no_tumba_dashboard(tmp_path):
    ruta = tmp_path / "corrupta.sqlite"
    ruta.write_text("no es SQLite", encoding="utf-8")
    assert not trading.AdaptadorTradingLab(ruta).estado().alcanzable


def test_supervisor_detenido_no_se_considera_vivo(almacen_tradinglab):
    almacen_tradinglab.latir(detalle="Detenido", estado="detenido", modo="simulado")
    estado = trading.AdaptadorTradingLab(almacen_tradinglab.db_path, habilitado=True).estado()
    assert estado.estado == "detenido"
    assert not estado.alcanzable and not estado.corriendo


def test_presupuesto_configurable_no_se_confunde_con_capital_inicial(almacen_tradinglab):
    nueva = trading.validar_config(trading.LUMIBOT, {
        **CONFIG_VALIDA, "instrumentos": ["AAPL"], "estrategia": "cruce_medias",
        "capital_simulado": 20000,
    })
    assert nueva["capital_simulado"] == 20000
    adaptador = trading.AdaptadorTradingLab(almacen_tradinglab.db_path)
    assert adaptador.rendimiento(nueva["capital_simulado"]).capital_inicial == 10000
