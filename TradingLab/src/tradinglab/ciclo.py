"""Un ciclo de evaluación: riesgo, órdenes y contabilidad.

Aquí se junta todo lo que los demás módulos mantienen separado. La estrategia
opina sobre la dirección del mercado; este módulo decide si esa opinión se puede
permitir, cuánto se arriesga, y deja constancia de lo ocurrido.

La separación importa porque las reglas de riesgo son las que no se negocian.
Una estrategia puede ser mala y perder dinero simulado sin que pase nada; pero
si el freno de pérdida diaria no funciona, el bot puede perderlo todo en una
sesión mientras nadie mira. Por eso el riesgo vive fuera de la estrategia y se
aplica siempre, sea cual sea la que esté configurada.

Orden de las comprobaciones, que no es casual:

1. **Salidas primero.** Un stop loss se atiende antes que cualquier idea nueva:
   liberar una posición perdedora puede ser justo lo que deja sitio para otra.
2. **Luego el freno diario.** Frena entradas, no salidas. Un freno que impidiera
   cerrar dejaría atrapadas precisamente las posiciones que van mal.
3. **Y al final las entradas**, con lo que quede de cupo.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from dataclasses import dataclass, field

from .config import ConfigCompartida
from .corredor import Corredor, Ejecucion, ErrorDeCorredor
from .estado import COMPRA, AlmacenEstado, Apertura
from .estrategia import Estrategia

log = logging.getLogger("tradinglab.ciclo")

#: Motivos de cierre. Van a `operaciones.motivo_salida` y son lo que permite,
#: meses después, saber si el bot salió porque lo decidió o porque lo echaron.
POR_STOP_LOSS = "stop loss"
POR_TAKE_PROFIT = "take profit"
POR_SENAL = "señal de la estrategia"
POR_RETIRADA = "el ticker salió de la configuración"


@dataclass(frozen=True)
class Resultado:
    """Lo que pasó en una vuelta, listo para el latido y para el log."""

    abiertas: int
    aperturas: int
    cierres: int
    detalle: str
    frenado: bool = False
    incidencias: tuple[str, ...] = ()


@dataclass
class Ciclo:
    """Ejecuta una evaluación completa sobre todos los instrumentos."""

    config: ConfigCompartida
    estrategia: Estrategia
    corredor: Corredor
    almacen: AlmacenEstado
    #: Aviso arrastrado desde la resolución de la estrategia (por ejemplo, que
    #: el nombre configurado no existe). Se cuela en el detalle del latido para
    #: que el problema se vea en el panel y no solo en el log de la VM.
    aviso: str = ""
    #: Tasa representativa del día, si se pudo obtener. Se anota en cada
    #: apertura; ver `trm.py` y docs/trading.md §7.
    trm: float | None = None
    comprobar_permiso: Callable[[], None] | None = None
    incidencias: list[str] = field(default_factory=list, init=False)
    _cerrados: set[str] = field(default_factory=set, init=False)

    # ------------------------------------------------------------------ público

    def ejecutar(self) -> Resultado:
        self.incidencias = []
        self._cerrados = set()
        aperturas = 0
        cierres = 0
        if not self.config.habilitado:
            return Resultado(len(self.almacen.abiertas()), 0, 0, "En pausa", frenado=True)
        if not self.corredor.mercado_abierto():
            return Resultado(len(self.almacen.abiertas()), 0, 0, "Mercado cerrado", frenado=True)

        cierres = self._revisar_salidas()

        frenado, motivo_freno = self._freno_diario()
        if not frenado and not self.incidencias:
            aperturas = self._buscar_entradas()

        abiertas = len(self.almacen.abiertas())
        return Resultado(
            abiertas=abiertas,
            aperturas=aperturas,
            cierres=cierres,
            detalle=self._detalle(abiertas, aperturas, cierres, motivo_freno),
            frenado=frenado,
            incidencias=tuple(self.incidencias),
        )

    # ------------------------------------------------------------------ salidas

    def _revisar_salidas(self) -> int:
        cerradas = 0
        configurados = set(self.config.instrumentos)

        for posicion in self.almacen.abiertas():
            if posicion.lado != COMPRA:
                self._incidencia(
                    f"{posicion.instrumento}: posición corta no soportada; requiere conciliación"
                )
                continue
            precio = self._precio(posicion.instrumento)
            if precio is None:
                continue

            variacion = posicion.variacion_pct(precio)
            motivo = ""

            if variacion <= -abs(self.config.stop_loss_pct):
                motivo = POR_STOP_LOSS
            elif variacion >= abs(self.config.take_profit_pct):
                motivo = POR_TAKE_PROFIT
            elif posicion.instrumento not in configurados:
                # Quitar un ticker de la lista es una orden de salida implícita.
                # Dejar la posición viva sin vigilarla sería lo peor de ambos
                # mundos: expuesta, y fuera del alcance de la estrategia.
                motivo = POR_RETIRADA
            else:
                senal = self._evaluar(posicion.instrumento, con_posicion=True)
                if senal is not None and senal.quiere_salir:
                    motivo = f"{POR_SENAL}: {senal.motivo}"

            if not motivo:
                continue

            try:
                self._comprobar_permiso()
                ejecucion = self.corredor.vender(posicion.instrumento, posicion.cantidad)
            except ErrorDeCorredor as exc:
                self._incidencia(f"no se pudo cerrar {posicion.instrumento}: {exc}")
                continue

            self._validar_ejecucion(ejecucion, posicion.instrumento, posicion.cantidad)
            self.almacen.registrar_cierre(
                posicion.id,
                precio_salida=ejecucion.precio,
                costos_salida=ejecucion.costos,
                motivo=motivo,
                orden_salida=ejecucion.identificador,
            )
            cerradas += 1
            self._cerrados.add(posicion.instrumento)
            log.info(
                "cerrada %s x%s a %s (%s)",
                posicion.instrumento,
                posicion.cantidad,
                ejecucion.precio,
                motivo,
            )
        return cerradas

    # -------------------------------------------------------------------- freno

    def _freno_diario(self) -> tuple[bool, str]:
        """¿Se agotó la pérdida permitida para hoy?

        El día se cuenta en UTC, igual que las marcas de tiempo de la base. Con
        el mercado estadounidense eso agrupa una sesión completa —abre y cierra
        dentro del mismo día UTC—, que es justo lo que se quiere frenar.
        """
        limite = abs(self.config.capital_simulado * self.config.max_perdida_diaria_pct / 100.0)
        if limite <= 0:
            return False, ""
        perdida_hoy = self.almacen.pnl_del_dia()
        if perdida_hoy > -limite:
            return False, ""
        return True, (
            f"freno diario activo: {perdida_hoy:,.2f} perdidos hoy, "
            f"tope {limite:,.2f}. No se abren posiciones nuevas."
        )

    # ----------------------------------------------------------------- entradas

    def _buscar_entradas(self) -> int:
        abiertas = self.almacen.abiertas()
        cupo = self.config.max_posiciones_abiertas - len(abiertas)
        if cupo <= 0:
            return 0
        if not self.corredor.mercado_abierto():
            return 0

        ya_dentro = {posicion.instrumento for posicion in abiertas}
        asignado = self._capital_por_posicion()
        comprometido = sum(p.cantidad * p.precio_entrada + p.costos for p in abiertas)
        presupuesto = max(0.0, self.config.capital_simulado - comprometido)
        efectivo_restante = math.inf
        nuevas = 0

        for instrumento in self.config.instrumentos:
            if cupo <= 0:
                break
            if instrumento in ya_dentro or instrumento in self._cerrados:
                continue

            senal = self._evaluar(instrumento, con_posicion=False)
            if senal is None or not senal.quiere_entrar:
                continue

            precio = self._precio(instrumento)
            if not precio or precio <= 0:
                continue

            # Acciones enteras. Alpaca admite fraccionarias, pero solo en
            # algunos tickers y con reglas propias; redondear hacia abajo es
            # aburrido, funciona siempre y hace la contabilidad exacta.
            try:
                efectivo = self.corredor.efectivo()
                if not math.isfinite(efectivo) or efectivo < 0:
                    raise ErrorDeCorredor("efectivo inválido")
                costo_unitario = self.corredor.costo_compra(instrumento, 1)
                if not math.isfinite(costo_unitario) or costo_unitario < 0:
                    raise ErrorDeCorredor("costo de compra inválido")
            except ErrorDeCorredor as exc:
                self._incidencia(f"no se pudo conocer el efectivo: {exc}")
                break
            efectivo_restante = min(efectivo_restante, efectivo)
            disponible = min(asignado, presupuesto, efectivo_restante)
            cantidad = float(int(disponible // (precio + costo_unitario)))
            if cantidad > 0 and (
                cantidad * precio + self.corredor.costo_compra(instrumento, cantidad) > disponible
            ):
                cantidad -= 1
            if cantidad < 1:
                self._incidencia(
                    f"{instrumento} cuesta {precio:,.2f} y solo hay {disponible:,.2f} "
                    "por posición: no alcanza para una acción."
                )
                continue

            try:
                self._comprobar_permiso()
                ejecucion = self.corredor.comprar(instrumento, cantidad)
            except ErrorDeCorredor as exc:
                self._incidencia(f"no se pudo abrir {instrumento}: {exc}")
                continue

            self._validar_ejecucion(ejecucion, instrumento, cantidad)
            self.almacen.registrar_apertura(
                Apertura(
                    instrumento=instrumento,
                    lado=COMPRA,
                    cantidad=ejecucion.cantidad,
                    precio_entrada=ejecucion.precio,
                    costos=ejecucion.costos,
                    orden_entrada=ejecucion.identificador,
                    trm=self.trm,
                )
            )
            nuevas += 1
            cupo -= 1
            ya_dentro.add(instrumento)
            presupuesto -= ejecucion.cantidad * ejecucion.precio + ejecucion.costos
            efectivo_restante -= ejecucion.cantidad * ejecucion.precio + ejecucion.costos
            log.info(
                "abierta %s x%s a %s (%s)",
                instrumento,
                ejecucion.cantidad,
                ejecucion.precio,
                senal.motivo,
            )
        return nuevas

    def _capital_por_posicion(self) -> float:
        posiciones = max(1, self.config.max_posiciones_abiertas)
        return self.config.capital_simulado / posiciones

    # ------------------------------------------------------------------ helpers

    def _evaluar(self, instrumento: str, *, con_posicion: bool):
        try:
            cierres = self.corredor.cierres(
                instrumento, self.estrategia.velas_necesarias, self.config.timeframe
            )
            if any(not math.isfinite(precio) or precio <= 0 for precio in cierres):
                raise ErrorDeCorredor("el histórico contiene precios inválidos")
        except ErrorDeCorredor as exc:
            self._incidencia(f"sin datos de {instrumento}: {exc}")
            return None
        return self.estrategia.evaluar(cierres, con_posicion=con_posicion)

    def _precio(self, instrumento: str) -> float | None:
        try:
            precio = self.corredor.precio(instrumento)
            if precio is None or not math.isfinite(precio) or precio <= 0:
                raise ErrorDeCorredor("precio ausente o inválido")
            return precio
        except ErrorDeCorredor as exc:
            self._incidencia(f"sin precio de {instrumento}: {exc}")
            return None

    def _comprobar_permiso(self) -> None:
        if self.comprobar_permiso is not None:
            self.comprobar_permiso()

    @staticmethod
    def _validar_ejecucion(ejecucion: Ejecucion, instrumento: str, cantidad: float) -> None:
        if (
            ejecucion.instrumento != instrumento
            or ejecucion.cantidad != cantidad
            or not math.isfinite(ejecucion.precio)
            or ejecucion.precio <= 0
            or not math.isfinite(ejecucion.costos)
            or ejecucion.costos < 0
        ):
            raise ValueError("Ejecución no conciliada: no se registra como una orden completa.")

    def _incidencia(self, texto: str) -> None:
        log.warning("%s", texto)
        if texto not in self.incidencias:
            self.incidencias.append(texto)

    def _detalle(self, abiertas: int, aperturas: int, cierres: int, motivo_freno: str) -> str:
        """Una línea para el panel.

        Cabe en el ancho de un celular y responde lo que se pregunta al mirar:
        qué estrategia corre, cuánto tiene abierto y qué acaba de hacer. Los
        problemas van primero, porque son la razón por la que alguien abre esta
        pantalla.
        """
        partes: list[str] = []
        if motivo_freno:
            partes.append(motivo_freno)
        if self.aviso:
            partes.append(self.aviso)
        if self.incidencias:
            partes.append(self.incidencias[0])

        movimiento = []
        if aperturas:
            movimiento.append(f"{aperturas} abierta(s)")
        if cierres:
            movimiento.append(f"{cierres} cerrada(s)")

        base = f"{self.estrategia.etiqueta} · {abiertas} posición(es)"
        if movimiento:
            base += " · " + ", ".join(movimiento)
        partes.append(base)
        return " | ".join(partes)
