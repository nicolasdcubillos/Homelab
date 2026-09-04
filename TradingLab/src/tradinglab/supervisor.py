"""El bucle de supervisión: leer la intención, obedecerla y dejar constancia.

Este es el proceso que corre bajo `systemd`. Su trabajo no es operar, sino
mantener sincronizado lo que el dashboard pide con lo que de verdad está
pasando, y contar la verdad sobre esa diferencia.

La decisión de diseño que sostiene todo lo demás
------------------------------------------------
**El latido y el ciclo de trading van por separado.** El bot late cada minuto,
pase lo que pase; evalúa el mercado cada `timeframe`, que puede ser un día
entero.

Mezclarlos sería el error obvio y estaría mal por dos motivos. El dashboard da
por caído a un motor que lleva más de 90 minutos sin latir, así que un bot
configurado en velas diarias aparecería como muerto 22 horas de cada 24. Y en
sentido contrario, un latido que solo ocurre al evaluar responde a la pregunta
equivocada: lo que el panel quiere saber es si el proceso está vivo, no cuándo
miró los precios por última vez.

Como efecto secundario deseable, apagar el bot desde el celular surte efecto en
menos de un minuto aunque su marco temporal sea diario.

Lo que no hace
--------------
No decide nada sobre el mercado (eso es `estrategia`) ni sobre el riesgo (eso es
`ciclo`). Y no expone ningún puerto: si hiciera falta ordenarle algo, el canal ya
existe y es la configuración compartida.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from . import __version__
from .ciclo import Ciclo, Resultado
from .config import ConfigCompartida, ErrorDeConfig, LectorDashboard
from .corredor import Corredor, Motor
from .estado import AlmacenEstado
from .estrategia import construir

log = logging.getLogger("tradinglab.supervisor")

#: Cada cuánto se late. Holgado frente a los 90 minutos de tolerancia del
#: dashboard: da margen para que fallen varias vueltas seguidas antes de que el
#: panel declare el motor caído, y aun así detecta el interruptor en menos de un
#: minuto.
LATIDO_SEG = 60


@dataclass
class Supervisor:
    """Mantiene el proceso alineado con lo que el dashboard declaró."""

    lector: LectorDashboard
    almacen: AlmacenEstado
    #: Se construye a demanda, no al arrancar: mientras el bot está en pausa no
    #: hay ninguna razón para tener abierta una sesión contra el corredor, y en
    #: una VM compartida esa sesión cuesta memoria.
    fabrica_motor: Callable[[ConfigCompartida], Motor]
    intervalo_latido_seg: int = LATIDO_SEG
    #: Inyectables para poder probar el bucle sin esperar en tiempo real.
    reloj: Callable[[], float] = field(default_factory=lambda: _reloj_por_defecto)
    dormir: Callable[[float], None] = field(default_factory=lambda: _dormir_por_defecto)

    _motor: Motor | None = field(default=None, init=False, repr=False)
    _proxima_evaluacion: float = field(default=0.0, init=False)
    _version_vista: int | None = field(default=None, init=False)
    _ultimo: Resultado | None = field(default=None, init=False)
    _detener: bool = field(default=False, init=False)

    # ------------------------------------------------------------------ público

    def parar(self) -> None:
        """Pide una salida ordenada. Seguro de llamar desde un manejador de señal."""
        self._detener = True

    def correr(self, vueltas: int | None = None) -> int:
        """Bucle principal. `vueltas` acota la ejecución en tests y en `--una-vez`."""
        dadas = 0
        while not self._detener:
            self.tick()
            dadas += 1
            if vueltas is not None and dadas >= vueltas:
                break
            if self._detener:
                break
            self.dormir(self.intervalo_latido_seg)
        self._soltar_motor()
        return dadas

    def tick(self) -> None:
        """Una vuelta: siempre termina dejando un latido escrito."""
        try:
            config = self.lector.leer()
        except ErrorDeConfig as exc:
            # Sin configuración no se sabe siquiera si debería estar operando.
            # Lo único responsable es quedarse quieto y decirlo en el panel,
            # que es donde alguien lo va a ver.
            log.error("no se pudo leer la configuración: %s", exc)
            self._latir(f"No se pudo leer la configuración: {exc}")
            return

        self._detectar_cambio(config)

        if not config.habilitado:
            self._soltar_motor()
            self._latir("En pausa")
            return

        if not config.operable:
            self._latir("Encendido, pero sin tickers configurados. Añade al menos uno.")
            return

        ahora = self.reloj()
        if ahora < self._proxima_evaluacion:
            self._latir(self._detalle_en_espera(ahora))
            return

        if self._evaluar(config):
            self._proxima_evaluacion = self.reloj() + config.segundos_entre_evaluaciones

    # ------------------------------------------------------------------ interno

    def _evaluar(self, config: ConfigCompartida) -> bool:
        """Corre un ciclo. Devuelve si toca esperar un `timeframe` completo.

        Un `False` significa «reintenta en la vuelta siguiente». Importa que la
        decisión suba hasta aquí: si `tick` reprogramara siempre, con velas
        diarias un fallo de conexión de treinta segundos costaría un día entero
        sin operar.
        """
        estrategia, aviso = construir(config.estrategia)
        try:
            motor = self._obtener_motor(config)
        except Exception as exc:
            log.exception("no se pudo preparar el motor")
            self._latir(f"No se pudo conectar con el corredor: {exc}")
            # Un fallo de conexión suele ser pasajero.
            return False

        trm = self._trm()

        def tarea(corredor: Corredor) -> Resultado:
            # El ciclo se construye aquí dentro, no fuera: con Lumibot el
            # corredor solo existe mientras dura la sesión que el motor abre, y
            # guardarse una referencia más allá de esta llamada sería quedarse
            # con un objeto cuyo contexto ya se cerró.
            return Ciclo(
                config=config,
                estrategia=estrategia,
                corredor=corredor,
                almacen=self.almacen,
                aviso=aviso,
                trm=trm,
            ).ejecutar()

        try:
            resultado = motor.ejecutar(tarea)
        except Exception as exc:
            log.exception("el ciclo de trading falló")
            self._latir(f"El ciclo falló: {exc}")
            # La sesión pudo quedar en mal estado; la siguiente vuelta abre otra.
            self._soltar_motor()
            return False

        if resultado is None:
            # El motor no llegó a darle el turno a la tarea. Con Alpaca esto
            # significa, casi siempre, que la bolsa está cerrada: no es un error
            # y no debe ensuciar el panel como si lo fuera. Tampoco consume el
            # turno, o al abrir el mercado habría que esperar otro timeframe.
            self._latir(self._detalle_sin_turno())
            return False

        self._ultimo = resultado
        self._latir(resultado.detalle, resultado.abiertas)
        return True

    def _detectar_cambio(self, config: ConfigCompartida) -> None:
        if self._version_vista == config.version:
            return
        if self._version_vista is not None:
            log.info(
                "configuración nueva (v%s -> v%s) por %s; se reevalúa en la vuelta actual",
                self._version_vista,
                config.version,
                config.actualizada_por or "alguien",
            )
            # Quien acaba de guardar espera ver el efecto, no esperar al
            # siguiente marco temporal.
            self._proxima_evaluacion = 0.0
        self._version_vista = config.version

    def _obtener_motor(self, config: ConfigCompartida) -> Motor:
        if self._motor is None:
            self._motor = self.fabrica_motor(config)
        return self._motor

    def _soltar_motor(self) -> None:
        if self._motor is None:
            return
        try:
            self._motor.cerrar()
        except Exception:
            log.warning("el motor no cerró limpiamente", exc_info=True)
        finally:
            self._motor = None

    def _trm(self) -> float | None:
        """Punto de enganche para la TRM del día (ver `trm.py`)."""
        return None

    def _latir(self, detalle: str, abiertas: int | None = None) -> None:
        if abiertas is None:
            try:
                abiertas = len(self.almacen.abiertas())
            except Exception:
                abiertas = 0
        try:
            self.almacen.latir(
                detalle=detalle,
                posiciones_abiertas=abiertas,
                version=f"tradinglab {__version__}",
            )
        except Exception:
            log.exception("no se pudo escribir el latido")

    def _detalle_en_espera(self, ahora: float) -> str:
        faltan = max(0, int(self._proxima_evaluacion - ahora))
        previo = self._ultimo.detalle if self._ultimo else "Operando"
        return f"{previo} · próxima revisión en {_legible(faltan)}"

    def _detalle_sin_turno(self) -> str:
        previo = self._ultimo.detalle if self._ultimo else "Sin operaciones todavía"
        return f"{previo} · mercado cerrado"


@dataclass
class SupervisorConTRM(Supervisor):
    """Supervisor que además anota la tasa del día en cada apertura.

    Va aparte para que la TRM sea opcional de verdad: el bucle funciona
    completo sin ella, y quien no necesite el histórico en pesos no arrastra la
    dependencia de red.
    """

    proveedor_trm: Callable[[], float | None] | None = None

    def _trm(self) -> float | None:
        if self.proveedor_trm is None:
            return None
        try:
            return self.proveedor_trm()
        except Exception:
            log.warning("no se pudo obtener la TRM del día", exc_info=True)
            return None


def _legible(segundos: int) -> str:
    if segundos < 60:
        return f"{segundos} s"
    if segundos < 3_600:
        return f"{segundos // 60} min"
    horas = segundos / 3_600
    return f"{horas:.1f} h"


def _reloj_por_defecto() -> float:
    import time

    return time.monotonic()


def _dormir_por_defecto(segundos: float) -> None:
    import time

    time.sleep(segundos)
