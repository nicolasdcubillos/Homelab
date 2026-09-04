"""Utilidades compartidas por los tests.

Ningún test de este paquete importa Lumibot. El motor real vive detrás del
protocolo `Motor` justo para eso: lo que se puede probar aquí se prueba de
verdad, y lo que necesita credenciales se valida en la VM con
`tradinglab doctor`.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tradinglab.config import BOT_NAME, LectorDashboard
from tradinglab.estado import AlmacenEstado

#: Réplica del esquema que crea la migración `de02a901e6ae` del dashboard, sin
#: la clave foránea a `users` (aquí no existe esa tabla). Se copia en vez de
#: importarse porque son dos aplicaciones distintas y este es el contrato entre
#: ellas: si el dashboard cambiara el esquema, estos tests tienen que romperse.
ESQUEMA_DASHBOARD = """
CREATE TABLE trading_bot_config (
    bot_name            VARCHAR(32)  NOT NULL,
    enabled             BOOLEAN      NOT NULL,
    mode                VARCHAR(16)  NOT NULL DEFAULT 'paper',
    config_json         JSON         NOT NULL,
    version             INTEGER      NOT NULL DEFAULT 1,
    updated_by_user_id  VARCHAR(32),
    updated_by_email    VARCHAR(320) NOT NULL,
    updated_at          DATETIME     NOT NULL,
    created_at          DATETIME     NOT NULL,
    CONSTRAINT pk_trading_bot_config PRIMARY KEY (bot_name),
    CONSTRAINT ck_bot_name_valido CHECK (bot_name IN ('freqtrade', 'lumibot')),
    CONSTRAINT ck_mode_valido CHECK (mode IN ('paper')),
    CONSTRAINT ck_version_positiva CHECK (version > 0)
);
"""

CONFIG_BASE = {
    "instrumentos": ["AAPL", "MSFT"],
    "estrategia": "cruce_medias",
    "timeframe": "1h",
    "capital_simulado": 10_000.0,
    "max_posiciones_abiertas": 3,
    "stop_loss_pct": 5.0,
    "take_profit_pct": 10.0,
    "max_perdida_diaria_pct": 5.0,
}


def escribir_config(
    ruta: Path,
    *,
    habilitado: bool = True,
    version: int = 1,
    modo: str = "paper",
    datos: dict | None = None,
    bot: str = BOT_NAME,
    crudo: str | None = None,
    con_checks: bool = True,
) -> Path:
    """Crea (o actualiza) la base del dashboard con una fila para el motor.

    `con_checks=False` crea la tabla sin sus restricciones, que es la única
    forma de simular una fila corrupta —modo distinto de `paper`, JSON inválido—
    y comprobar que TradingLab se defiende por su cuenta en vez de confiar en
    que el otro proceso ya la validó.
    """
    nueva = not ruta.exists()
    conexion = sqlite3.connect(ruta)
    try:
        if nueva:
            esquema = ESQUEMA_DASHBOARD
            if not con_checks:
                esquema = "\n".join(
                    linea for linea in esquema.splitlines() if "CONSTRAINT ck_" not in linea
                ).replace("PRIMARY KEY (bot_name),", "PRIMARY KEY (bot_name)")
            conexion.executescript(esquema)
        contenido = crudo if crudo is not None else json.dumps(datos or CONFIG_BASE)
        conexion.execute(
            "INSERT INTO trading_bot_config "
            "(bot_name, enabled, mode, config_json, version, updated_by_email, "
            "updated_at, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(bot_name) DO UPDATE SET "
            "enabled = excluded.enabled, mode = excluded.mode, "
            "config_json = excluded.config_json, version = excluded.version",
            (
                bot,
                int(habilitado),
                modo,
                contenido,
                version,
                "nico@example.com",
                "2026-01-01 00:00:00",
                "2026-01-01 00:00:00",
            ),
        )
        conexion.commit()
    finally:
        conexion.close()
    return ruta


@pytest.fixture
def db_dashboard(tmp_path: Path) -> Path:
    return tmp_path / "dashboard.db"


@pytest.fixture
def lector(db_dashboard: Path) -> LectorDashboard:
    escribir_config(db_dashboard)
    return LectorDashboard(db_dashboard)


@pytest.fixture
def almacen(tmp_path: Path):
    with AlmacenEstado(tmp_path / "tradinglab.db") as instancia:
        yield instancia
