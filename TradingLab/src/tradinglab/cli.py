"""Interfaz de línea de comandos.

    tradinglab correr                 bucle de supervisión (lo que corre en systemd)
    tradinglab correr --simulado      igual, pero contra precios inventados
    tradinglab correr --una-vez       una sola vuelta y salir
    tradinglab estado                 último latido y posiciones abiertas
    tradinglab operaciones            las últimas operaciones registradas
    tradinglab doctor                 comprueba el entorno sin enviar órdenes

Variables de entorno
--------------------
``TRADINGLAB_DASHBOARD_DB``  base del dashboard, de donde se lee la configuración
``TRADINGLAB_DB``            base propia; debe coincidir con ``DASHBOARD_TRADINGLAB_DB``
``ALPACA_API_KEY``           credenciales de Alpaca Paper, solo para el motor real
``ALPACA_API_SECRET``

Las credenciales van en el ``Environment=`` de la unidad de systemd y nunca en la
base de datos: la configuración compartida la puede editar cualquier usuario
autorizado desde el celular.
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
from pathlib import Path

from . import __version__
from .config import BOT_NAME, ErrorDeConfig, LectorDashboard
from .corredor import MotorSimulado
from .estado import AlmacenEstado
from .estrategia import DISPONIBLES
from .supervisor import SupervisorConTRM
from .trm import ProveedorTRM

log = logging.getLogger("tradinglab")

DB_DASHBOARD_POR_DEFECTO = "data/dashboard.db"
DB_PROPIA_POR_DEFECTO = "data/tradinglab.db"


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------


def _configurar_log(verboso: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verboso else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    # Lumibot es habladísimo en INFO y taparía por completo nuestros mensajes.
    for ruidoso in ("lumibot", "alpaca", "urllib3", "httpx", "matplotlib"):
        logging.getLogger(ruidoso).setLevel(logging.WARNING)


def _ruta_dashboard(args: argparse.Namespace) -> Path:
    ruta = (
        args.db_dashboard or os.environ.get("TRADINGLAB_DASHBOARD_DB") or DB_DASHBOARD_POR_DEFECTO
    )
    return Path(ruta).expanduser()


def _ruta_propia(args: argparse.Namespace) -> Path:
    ruta = args.db or os.environ.get("TRADINGLAB_DB") or DB_PROPIA_POR_DEFECTO
    return Path(ruta).expanduser()


def _fabrica(args: argparse.Namespace, almacen: AlmacenEstado):
    """Decide qué motor se usa: el simulado o Lumibot sobre Alpaca."""
    if args.simulado:

        def simulado(config):
            return MotorSimulado(almacen=almacen, capital_inicial=config.capital_simulado)

        return simulado

    def alpaca(config):
        # Import perezoso: el resto del CLI —y todos los tests— funcionan sin
        # tener Lumibot instalado, que son varios cientos de megabytes.
        from .corredor_alpaca import MotorAlpaca

        return MotorAlpaca.desde_entorno(
            timeframe=config.timeframe,
            directorio_logs=Path(args.logs).expanduser(),
        )

    return alpaca


# ---------------------------------------------------------------------------
# Comandos
# ---------------------------------------------------------------------------


def cmd_correr(args: argparse.Namespace) -> int:
    if args.simulado and not args.db:
        raise ErrorDeConfig("--simulado exige --db con una ruta demo separada de producción.")
    lector = LectorDashboard(_ruta_dashboard(args))
    almacen = AlmacenEstado(_ruta_propia(args))
    modo = "simulado" if args.simulado else "alpaca_paper"

    with almacen:
        almacen.vincular(modo)
        supervisor = SupervisorConTRM(
            lector=lector,
            almacen=almacen,
            fabrica_motor=_fabrica(args, almacen),
            proveedor_trm=ProveedorTRM().obtener if args.simulado and not args.sin_trm else None,
            modo=modo,
        )

        def parar(numero, _marco):
            log.info("señal %s recibida; cerrando ordenadamente", numero)
            supervisor.parar()

        # SIGTERM interrumpe la espera entre vueltas sin liquidar posiciones.
        for numero in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(numero, parar)
            except (ValueError, OSError):  # pragma: no cover - hilo o plataforma
                log.debug("no se pudo instalar el manejador de %s", numero)

        log.info("TradingLab %s arrancando (motor %s)", __version__, modo)
        vueltas = 1 if args.una_vez else args.vueltas
        dadas = supervisor.correr(vueltas=vueltas)
        log.info("terminado tras %d vuelta(s)", dadas)
    return 0


def cmd_estado(args: argparse.Namespace) -> int:
    ruta = _ruta_propia(args)
    if not ruta.exists():
        print(f"Todavía no hay base en {ruta}. ¿Ha corrido alguna vez el bot?")
        return 1

    with AlmacenEstado(ruta) as almacen:
        latido = almacen.ultimo_latido()
        if latido is None:
            print("Sin latidos registrados.")
            return 1
        print(f"Último latido : {latido['latido_en']}")
        print(f"Versión       : {latido['version'] or '—'}")
        print(f"Detalle       : {latido['detalle']}")
        print(f"Estado        : {latido['estado'] or 'desconocido'}")
        print(f"Origen        : {latido['modo'] or 'desconocido'}")
        print(f"Abiertas      : {latido['posiciones_abiertas']}")

        abiertas = almacen.abiertas()
        if abiertas:
            print("\nPosiciones abiertas:")
            for posicion in abiertas:
                print(
                    f"  {posicion.instrumento:<8} x{posicion.cantidad:<8g} "
                    f"entrada {posicion.precio_entrada:>10,.2f}   desde {posicion.abierta_en}"
                )
        print(f"\nResultado cerrado hoy: {almacen.pnl_del_dia():,.2f}")
    return 0


def cmd_operaciones(args: argparse.Namespace) -> int:
    ruta = _ruta_propia(args)
    if not ruta.exists():
        print(f"Todavía no hay base en {ruta}.")
        return 1

    with AlmacenEstado(ruta) as almacen:
        filas = almacen.ultimas(args.limite)
        if not filas:
            print("Sin operaciones registradas.")
            return 0
        cabecera = (
            f"{'INSTRUMENTO':<12}{'LADO':<8}{'CANT':>8}{'ENTRADA':>12}"
            f"{'SALIDA':>12}{'PNL':>12}  ABIERTA"
        )
        print(cabecera)
        print("-" * len(cabecera))
        for fila in filas:
            salida = fila["precio_salida"]
            pnl = fila["pnl_absoluto"]
            print(
                f"{fila['instrumento']:<12}{fila['lado']:<8}{fila['cantidad']:>8g}"
                f"{fila['precio_entrada']:>12,.2f}"
                f"{(f'{salida:,.2f}' if salida is not None else '—'):>12}"
                f"{(f'{pnl:,.2f}' if pnl is not None else '—'):>12}"
                f"  {fila['abierta_en']}"
            )
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    """Diagnóstico local: no prueba conexión, cuenta, horario ni permisos Alpaca."""
    problemas = 0
    print("Diagnóstico local. No comprueba conexión, cuenta ni horario de Alpaca.")

    ruta_dashboard = _ruta_dashboard(args)
    print(f"Base del dashboard : {ruta_dashboard}")
    try:
        config = LectorDashboard(ruta_dashboard).leer()
    except ErrorDeConfig as exc:
        print(f"  ✗ {exc}")
        problemas += 1
    else:
        if config.version == 0:
            print(f"  ⚠ no hay fila para «{BOT_NAME}»; se creará al abrir la pantalla de trading")
        else:
            estado = "encendido" if config.habilitado else "en pausa"
            print(f"  ✓ configuración v{config.version}, {estado}")
            print(f"    estrategia {config.estrategia or '(sin definir)'} · {config.timeframe}")
            print(f"    instrumentos: {', '.join(config.instrumentos) or '(ninguno)'}")
            if config.habilitado and not config.instrumentos:
                print("  ⚠ encendido sin tickers: no va a operar")

    ruta_propia = _ruta_propia(args)
    print(f"\nBase propia        : {ruta_propia}")
    try:
        with AlmacenEstado(ruta_propia) as almacen:
            latido = almacen.ultimo_latido()
        print(f"  ✓ escribible · último latido: {latido['latido_en'] if latido else 'ninguno'}")
    except Exception as exc:
        print(f"  ✗ no se pudo abrir: {exc}")
        problemas += 1

    print(f"\nEstrategias        : {', '.join(sorted(DISPONIBLES))}")

    print("\nMotor de Alpaca")
    from .corredor_alpaca import BLOQUEO_ALPACA, disponible

    if not disponible():
        print("  lumibot no está instalado; no hace falta para el supervisor pausado.")
    else:
        print("  Paquete lumibot presente; no importado ni validado.")
    print(f"  ✗ {BLOQUEO_ALPACA}")
    problemas += 1

    print()
    print(f"{problemas} bloqueo(s). El supervisor puede permanecer en pausa sin credenciales.")
    return 1


# ---------------------------------------------------------------------------
# Entrada
# ---------------------------------------------------------------------------


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tradinglab",
        description="Motor de trading simulado de acciones y ETFs del homelab.",
    )
    parser.add_argument("--version", action="version", version=f"tradinglab {__version__}")
    parser.add_argument("-v", "--verboso", action="store_true", help="log en DEBUG")
    parser.add_argument("--db", help="ruta de la base propia (TRADINGLAB_DB)")
    parser.add_argument(
        "--db-dashboard", help="ruta de la base del dashboard (TRADINGLAB_DASHBOARD_DB)"
    )

    sub = parser.add_subparsers(dest="comando", required=True)

    correr = sub.add_parser("correr", help="bucle de supervisión")
    correr.add_argument(
        "--simulado",
        action="store_true",
        help="opera contra precios inventados, sin Alpaca ni credenciales",
    )
    correr.add_argument("--una-vez", action="store_true", help="una sola vuelta y salir")
    correr.add_argument(
        "--vueltas", type=int, default=None, help="número máximo de vueltas (por defecto, sin tope)"
    )
    correr.add_argument("--sin-trm", action="store_true", help="no consultar la TRM")
    correr.add_argument("--logs", default="logs", help="directorio para los logs de Lumibot")
    correr.set_defaults(func=cmd_correr)

    estado = sub.add_parser("estado", help="último latido y posiciones abiertas")
    estado.set_defaults(func=cmd_estado)

    operaciones = sub.add_parser("operaciones", help="últimas operaciones registradas")
    operaciones.add_argument("--limite", type=int, default=20)
    operaciones.set_defaults(func=cmd_operaciones)

    doctor = sub.add_parser("doctor", help="comprueba el entorno sin operar")
    doctor.set_defaults(func=cmd_doctor)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = construir_parser().parse_args(argv)
    _configurar_log(args.verboso)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        return 130
    except (ErrorDeConfig, ValueError) as exc:
        log.error("%s", exc)
        return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
