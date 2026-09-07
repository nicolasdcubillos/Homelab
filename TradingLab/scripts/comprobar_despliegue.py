"""Comprueba vida del supervisor; un latido no prueba conectividad ni operativa."""

from __future__ import annotations

import argparse
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path


def comprobar(ruta: Path, desde: float, ahora: float) -> str:
    with sqlite3.connect(f"{ruta.resolve().as_uri()}?mode=ro", uri=True, timeout=2) as db:
        fila = db.execute(
            "SELECT latido_en, detalle FROM estado_motor ORDER BY latido_en DESC LIMIT 1"
        ).fetchone()
    if fila is None:
        raise ValueError("El supervisor no ha publicado ningun latido.")
    fecha = datetime.fromisoformat(fila[0])
    if fecha.tzinfo is None:
        raise ValueError("El latido no declara zona horaria.")
    marca = fecha.timestamp()
    if marca < desde or not 0 <= ahora - marca <= 120:
        raise ValueError("El latido no pertenece al arranque actual o esta desactualizado.")
    return str(fila[1])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--desde", required=True, type=float)
    parser.add_argument("--espera", type=float, default=90)
    args = parser.parse_args()
    limite = time.monotonic() + args.espera
    while True:
        try:
            detalle = comprobar(args.db, args.desde, datetime.now(timezone.utc).timestamp())
        except (sqlite3.Error, ValueError, TypeError) as exc:
            if time.monotonic() >= limite:
                print(f"No se pudo confirmar el arranque: {exc}", flush=True)
                return 1
            time.sleep(2)
        else:
            print(f"Supervisor vivo. Estado publicado: {detalle}", flush=True)
            print("Esto no confirma conexion con Alpaca ni autoriza enviar ordenes.", flush=True)
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
