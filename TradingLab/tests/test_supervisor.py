"""El bucle de supervisión.

Lo que se prueba aquí es la promesa que el módulo le hace al panel: **siempre
queda un latido escrito**, pase lo que pase, y el interruptor del dashboard se
obedece en la vuelta siguiente aunque el marco temporal sea diario.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from conftest import CONFIG_BASE, escribir_config
from tradinglab.config import ErrorDeConfig, LectorDashboard
from tradinglab.corredor import Corredor, CorredorSimulado, MotorSimulado
from tradinglab.estado import AlmacenEstado
from tradinglab.supervisor import Supervisor, SupervisorConTRM

# ---------------------------------------------------------------------------
# Dobles
# ---------------------------------------------------------------------------


@dataclass
class Reloj:
    """Tiempo controlado por el test: el bucle no espera de verdad."""

    ahora: float = 0.0
    dormidas: list[float] = field(default_factory=list)

    def __call__(self) -> float:
        return self.ahora

    def dormir(self, segundos: float) -> None:
        self.dormidas.append(segundos)
        self.ahora += segundos


@dataclass
class MotorEspia:
    """Cuenta cuántas veces se le pidió ejecutar y si lo cerraron."""

    corredor: CorredorSimulado = field(default_factory=CorredorSimulado)
    ejecuciones: int = 0
    cerrado: bool = False
    devolver_nada: bool = False
    explotar: bool = False

    def ejecutar(self, tarea):
        self.ejecuciones += 1
        if self.explotar:
            raise RuntimeError("el corredor se cayó")
        if self.devolver_nada:
            return None
        return tarea(self.corredor)

    def cerrar(self) -> None:
        self.cerrado = True


@dataclass
class LectorRoto:
    mensaje: str = "la base se fue"

    def leer(self):
        raise ErrorDeConfig(self.mensaje)


def _supervisor(lector, almacen, motor=None, reloj=None, **extra):
    reloj = reloj or Reloj()
    return Supervisor(
        lector=lector,
        almacen=almacen,
        fabrica_motor=lambda _config: motor or MotorSimulado(),
        reloj=reloj,
        dormir=reloj.dormir,
        **extra,
    )


# ---------------------------------------------------------------------------
# El latido, que es la promesa principal
# ---------------------------------------------------------------------------


def test_en_pausa_late_igual(db_dashboard: Path, almacen: AlmacenEstado) -> None:
    """Estar apagado es un estado normal, no una avería.

    Si el latido solo se escribiera al operar, el dashboard daría por caído a un
    bot que simplemente está en pausa.
    """
    escribir_config(db_dashboard, habilitado=False)
    supervisor = _supervisor(LectorDashboard(db_dashboard), almacen)

    supervisor.tick()

    latido = almacen.ultimo_latido()
    assert latido is not None
    assert latido["detalle"] == "En pausa"


def test_un_error_de_configuracion_se_cuenta_en_el_panel(almacen: AlmacenEstado) -> None:
    """Un motor que falla y lo cuenta es mucho más útil que uno que desaparece."""
    supervisor = _supervisor(LectorRoto(), almacen)

    supervisor.tick()

    latido = almacen.ultimo_latido()
    assert latido is not None
    assert "No se pudo leer la configuración" in latido["detalle"]
    assert "la base se fue" in latido["detalle"]


def test_encendido_sin_tickers_lo_dice_con_todas_las_letras(
    db_dashboard: Path, almacen: AlmacenEstado
) -> None:
    escribir_config(db_dashboard, datos={**CONFIG_BASE, "instrumentos": []})
    supervisor = _supervisor(LectorDashboard(db_dashboard), almacen)

    supervisor.tick()

    latido = almacen.ultimo_latido()
    assert latido is not None
    assert "sin tickers" in latido["detalle"]


def test_el_latido_lleva_la_version_del_paquete(db_dashboard: Path, almacen: AlmacenEstado) -> None:
    escribir_config(db_dashboard, habilitado=False)

    _supervisor(LectorDashboard(db_dashboard), almacen).tick()

    latido = almacen.ultimo_latido()
    assert latido is not None
    assert latido["version"].startswith("tradinglab ")


def test_un_ciclo_que_explota_deja_constancia_y_suelta_el_motor(
    db_dashboard: Path, almacen: AlmacenEstado
) -> None:
    escribir_config(db_dashboard)
    motor = MotorEspia(explotar=True)
    supervisor = _supervisor(LectorDashboard(db_dashboard), almacen, motor=motor)

    supervisor.tick()

    latido = almacen.ultimo_latido()
    assert latido is not None
    assert "El ciclo falló" in latido["detalle"]
    # La sesión pudo quedar en mal estado; la siguiente vuelta abre otra.
    assert motor.cerrado is True


# ---------------------------------------------------------------------------
# El interruptor
# ---------------------------------------------------------------------------


def test_pausar_suelta_el_motor(db_dashboard: Path, almacen: AlmacenEstado) -> None:
    """Mientras el bot está apagado no hay razón para mantener la sesión abierta.

    En una VM compartida con otras tres aplicaciones, esa sesión cuesta memoria.
    """
    escribir_config(db_dashboard, habilitado=True, version=1)
    motor = MotorEspia()
    supervisor = _supervisor(LectorDashboard(db_dashboard), almacen, motor=motor)
    supervisor.tick()
    assert motor.ejecuciones == 1

    escribir_config(db_dashboard, habilitado=False, version=2)
    supervisor.tick()

    assert motor.cerrado is True
    assert almacen.ultimo_latido()["detalle"] == "En pausa"


def test_guardar_la_configuracion_fuerza_una_reevaluacion(
    db_dashboard: Path, almacen: AlmacenEstado
) -> None:
    """Quien acaba de guardar espera ver el efecto, no esperar al siguiente marco.

    Con `timeframe` diario, sin esto habría que esperar 24 horas para comprobar
    si el cambio hizo algo.
    """
    escribir_config(db_dashboard, version=1, datos={**CONFIG_BASE, "timeframe": "1d"})
    motor = MotorEspia()
    reloj = Reloj()
    supervisor = _supervisor(LectorDashboard(db_dashboard), almacen, motor=motor, reloj=reloj)

    supervisor.tick()
    assert motor.ejecuciones == 1

    # Un minuto después, sin cambios, no toca reevaluar.
    reloj.ahora += 60
    supervisor.tick()
    assert motor.ejecuciones == 1

    escribir_config(db_dashboard, version=2, datos={**CONFIG_BASE, "timeframe": "1d"})
    reloj.ahora += 60
    supervisor.tick()

    assert motor.ejecuciones == 2


def test_entre_evaluaciones_se_sigue_latiendo(db_dashboard: Path, almacen: AlmacenEstado) -> None:
    """La decisión de diseño que sostiene el módulo entero.

    El dashboard da por caído a un motor que lleva más de 90 minutos sin latir.
    Si el latido y la evaluación fueran lo mismo, un bot en velas diarias
    aparecería como muerto 22 horas de cada 24.
    """
    escribir_config(db_dashboard, datos={**CONFIG_BASE, "timeframe": "1d"})
    motor = MotorEspia()
    reloj = Reloj()
    supervisor = _supervisor(LectorDashboard(db_dashboard), almacen, motor=motor, reloj=reloj)

    supervisor.tick()
    primer_latido = almacen.ultimo_latido()["latido_en"]

    reloj.ahora += 3_600
    supervisor.tick()

    assert motor.ejecuciones == 1  # todavía no toca evaluar
    latido = almacen.ultimo_latido()
    assert latido["latido_en"] >= primer_latido
    assert "próxima revisión en" in latido["detalle"]


# ---------------------------------------------------------------------------
# Mercado cerrado
# ---------------------------------------------------------------------------


def test_un_motor_sin_turno_no_es_un_error(db_dashboard: Path, almacen: AlmacenEstado) -> None:
    """Con Lumibot, `None` significa casi siempre que la bolsa está cerrada.

    Tratarlo como fallo llenaría el panel de rojo cada noche y cada fin de
    semana.
    """
    escribir_config(db_dashboard)
    motor = MotorEspia(devolver_nada=True)
    supervisor = _supervisor(LectorDashboard(db_dashboard), almacen, motor=motor)

    supervisor.tick()

    latido = almacen.ultimo_latido()
    assert "mercado cerrado" in latido["detalle"]
    assert "falló" not in latido["detalle"]


def test_el_mercado_cerrado_no_consume_el_turno(db_dashboard: Path, almacen: AlmacenEstado) -> None:
    """Si contara como evaluación, al abrir la bolsa habría que esperar otro marco.

    Con velas diarias, una vuelta nocturna gastaría el turno del día siguiente y
    el bot no miraría el mercado hasta 24 horas después de la apertura.
    """
    escribir_config(db_dashboard, datos={**CONFIG_BASE, "timeframe": "1d"})
    motor = MotorEspia(devolver_nada=True)
    reloj = Reloj()
    supervisor = _supervisor(LectorDashboard(db_dashboard), almacen, motor=motor, reloj=reloj)

    supervisor.tick()
    reloj.ahora += 60
    supervisor.tick()

    assert motor.ejecuciones == 2


# ---------------------------------------------------------------------------
# El bucle
# ---------------------------------------------------------------------------


def test_correr_respeta_el_numero_de_vueltas(db_dashboard: Path, almacen: AlmacenEstado) -> None:
    escribir_config(db_dashboard, habilitado=False)
    reloj = Reloj()
    supervisor = _supervisor(LectorDashboard(db_dashboard), almacen, reloj=reloj)

    dadas = supervisor.correr(vueltas=3)

    assert dadas == 3
    # Dos siestas, no tres: tras la última vuelta se sale sin esperar.
    assert reloj.dormidas == [60, 60]


def test_parar_corta_el_bucle(db_dashboard: Path, almacen: AlmacenEstado) -> None:
    """`parar()` tiene que ser seguro desde un manejador de señal.

    Es lo que hace que `systemctl stop` no deje el proceso a medias.
    """
    escribir_config(db_dashboard, habilitado=False)
    supervisor = _supervisor(LectorDashboard(db_dashboard), almacen)
    supervisor.parar()

    assert supervisor.correr(vueltas=10) == 0


def test_al_terminar_se_suelta_el_motor(db_dashboard: Path, almacen: AlmacenEstado) -> None:
    escribir_config(db_dashboard)
    motor = MotorEspia()
    supervisor = _supervisor(LectorDashboard(db_dashboard), almacen, motor=motor)

    supervisor.correr(vueltas=1)

    assert motor.cerrado is True


def test_un_motor_que_no_se_deja_construir_reintenta_pronto(
    db_dashboard: Path, almacen: AlmacenEstado
) -> None:
    """Un fallo de conexión suele ser pasajero: no se espera un timeframe entero."""
    escribir_config(db_dashboard, datos={**CONFIG_BASE, "timeframe": "1d"})

    def fabrica_rota(_config) -> Corredor:
        raise RuntimeError("sin credenciales")

    reloj = Reloj()
    supervisor = Supervisor(
        lector=LectorDashboard(db_dashboard),
        almacen=almacen,
        fabrica_motor=fabrica_rota,
        reloj=reloj,
        dormir=reloj.dormir,
    )

    supervisor.tick()
    latido = almacen.ultimo_latido()
    assert "No se pudo conectar con el corredor" in latido["detalle"]

    # Sin el reintento, con velas diarias el siguiente intento sería mañana.
    reloj.ahora += 60
    supervisor.tick()
    assert "No se pudo conectar con el corredor" in almacen.ultimo_latido()["detalle"]


# ---------------------------------------------------------------------------
# TRM
# ---------------------------------------------------------------------------


def test_la_trm_llega_hasta_la_operacion(db_dashboard: Path, almacen: AlmacenEstado) -> None:
    escribir_config(db_dashboard, datos={**CONFIG_BASE, "instrumentos": ["AAPL"]})
    reloj = Reloj()
    supervisor = SupervisorConTRM(
        lector=LectorDashboard(db_dashboard),
        almacen=almacen,
        fabrica_motor=lambda _config: MotorSimulado(),
        reloj=reloj,
        dormir=reloj.dormir,
        proveedor_trm=lambda: 4200.0,
    )

    supervisor.tick()

    assert supervisor._trm() == pytest.approx(4200.0)


def test_una_trm_que_falla_no_bloquea_nada(db_dashboard: Path, almacen: AlmacenEstado) -> None:
    escribir_config(db_dashboard)

    def proveedor_roto() -> float:
        raise RuntimeError("datos.gov.co no responde")

    reloj = Reloj()
    supervisor = SupervisorConTRM(
        lector=LectorDashboard(db_dashboard),
        almacen=almacen,
        fabrica_motor=lambda _config: MotorSimulado(),
        reloj=reloj,
        dormir=reloj.dormir,
        proveedor_trm=proveedor_roto,
    )

    supervisor.tick()

    assert supervisor._trm() is None
    latido = almacen.ultimo_latido()
    assert latido is not None
    assert "falló" not in latido["detalle"]
