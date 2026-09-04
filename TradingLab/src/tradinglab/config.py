"""Lectura de la configuración compartida que publica el dashboard.

TradingLab es el lado **declarativo** del contrato descrito en
`HomelabFrontend/docs/trading.md`: nadie le ordena arrancar ni parar. El
dashboard escribe `enabled` y `config_json` en su propia base de datos, y este
módulo los lee en cada ciclo. La consecuencia práctica es que apagar el bot
desde el celular funciona aunque este proceso esté a mitad de una decisión: no
hay orden que se pueda perder, solo un valor que se vuelve a leer.

La base del dashboard se abre en **solo lectura** (`mode=ro`), que es la misma
regla que el dashboard aplica a la nuestra, mirada desde el otro lado. Ninguna
de las dos aplicaciones escribe en la base de la otra; cada una publica lo suyo
y lee lo ajeno.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger("tradinglab.config")

#: Nombre de este motor en `trading_bot_config`. Lo fija el dashboard en
#: `homelab_dashboard.models.BOT_LUMIBOT`; si cambiara allí, hay que cambiarlo
#: aquí y en ningún otro sitio.
BOT_NAME = "lumibot"

#: Único modo admitido. El dashboard ya lo garantiza con un `CHECK` en la
#: columna, y aquí se vuelve a comprobar. No es una repetición ociosa: son dos
#: procesos distintos, y esta es *nuestra* copia de la invariante. Si algún día
#: la base dijera otra cosa, TradingLab se niega a operar en vez de confiar.
MODO_PAPER = "paper"

#: Tope de instrumentos, replicado de `MotorSpec.max_instrumentos` para el
#: motor `lumibot`. El dashboard ya lo valida al guardar; esto solo protege
#: contra una fila escrita a mano en la base.
MAX_INSTRUMENTOS = 25

#: Cuánto dura una vela según el marco temporal. Solo se usa para decidir cada
#: cuánto reevaluar; el latido va por su cuenta (ver `supervisor`).
SEGUNDOS_POR_TIMEFRAME: dict[str, int] = {
    "5m": 300,
    "15m": 900,
    "30m": 1_800,
    "1h": 3_600,
    "1d": 86_400,
}

VALORES_POR_DEFECTO: dict[str, Any] = {
    "instrumentos": [],
    "estrategia": "",
    "timeframe": "1h",
    "capital_simulado": 10_000.0,
    "max_posiciones_abiertas": 3,
    "stop_loss_pct": 5.0,
    "take_profit_pct": 10.0,
    "max_perdida_diaria_pct": 5.0,
}


class ErrorDeConfig(RuntimeError):
    """La configuración compartida no se pudo leer o no es utilizable.

    Se distingue de «el bot está apagado»: estar apagado es un estado normal y
    esperado, mientras que esto significa que no sabemos siquiera si debería
    estar encendido.
    """


@dataclass(frozen=True)
class ConfigCompartida:
    """Lo que el dashboard publica para este motor, ya normalizado.

    Es inmutable a propósito: cada ciclo lee una foto nueva en vez de mutar la
    anterior, así que nunca queda media configuración aplicada.
    """

    habilitado: bool
    #: Versión de la fila. Sirve para detectar que alguien cambió algo y
    #: rehacer el estado derivado. `0` significa «el dashboard todavía no ha
    #: creado la fila», que no es un error.
    version: int
    instrumentos: tuple[str, ...]
    estrategia: str
    timeframe: str
    capital_simulado: float
    max_posiciones_abiertas: int
    stop_loss_pct: float
    take_profit_pct: float
    max_perdida_diaria_pct: float
    #: Quién la dejó así. Solo para la bitácora: cuando el bot cambia de
    #: comportamiento de un ciclo a otro, el log dice a raíz de qué edición.
    actualizada_por: str = ""
    actualizada_en: str = ""

    @classmethod
    def ausente(cls) -> ConfigCompartida:
        """Configuración de un motor que el dashboard aún no ha inicializado.

        El dashboard crea la fila la primera vez que alguien abre la pantalla de
        trading, no en la migración. Antes de eso lo correcto es quedarse en
        pausa, no fallar: el proceso puede llevar días instalado y correcto sin
        que nadie haya entrado todavía.
        """
        return cls(
            habilitado=False,
            version=0,
            instrumentos=(),
            estrategia="",
            timeframe=str(VALORES_POR_DEFECTO["timeframe"]),
            capital_simulado=float(VALORES_POR_DEFECTO["capital_simulado"]),
            max_posiciones_abiertas=int(VALORES_POR_DEFECTO["max_posiciones_abiertas"]),
            stop_loss_pct=float(VALORES_POR_DEFECTO["stop_loss_pct"]),
            take_profit_pct=float(VALORES_POR_DEFECTO["take_profit_pct"]),
            max_perdida_diaria_pct=float(VALORES_POR_DEFECTO["max_perdida_diaria_pct"]),
        )

    @property
    def operable(self) -> bool:
        """¿Hay con qué operar?

        Estar habilitado sin instrumentos es una configuración a medio hacer,
        muy común justo después de conceder el acceso. Se trata como pausa
        explicable y no como error.
        """
        return self.habilitado and bool(self.instrumentos)

    @property
    def segundos_entre_evaluaciones(self) -> int:
        return SEGUNDOS_POR_TIMEFRAME.get(self.timeframe, 3_600)


def _texto(fila: sqlite3.Row, clave: str) -> str:
    valor = fila[clave]
    return "" if valor is None else str(valor)


def _numero(datos: dict[str, Any], clave: str, conversor: Any) -> Any:
    """Lee un número de la configuración cayendo al valor por defecto.

    El dashboard ya valida los rangos al guardar, así que aquí no se revalidan:
    lo único que se cubre es una fila escrita a mano o corrupta, donde preferimos
    arrancar con el valor conservador antes que morir en el arranque.
    """
    try:
        return conversor(datos.get(clave, VALORES_POR_DEFECTO[clave]))
    except (TypeError, ValueError):
        log.warning(
            "«%s» ilegible en la configuración compartida (%r); se usa el valor por defecto %r",
            clave,
            datos.get(clave),
            VALORES_POR_DEFECTO[clave],
        )
        return conversor(VALORES_POR_DEFECTO[clave])


def _instrumentos(datos: dict[str, Any]) -> tuple[str, ...]:
    crudos = datos.get("instrumentos") or []
    if not isinstance(crudos, list):
        log.warning("«instrumentos» no es una lista (%r); se ignora", crudos)
        return ()
    limpios: list[str] = []
    for bruto in crudos:
        texto = str(bruto).strip().upper()
        if texto and texto not in limpios:
            limpios.append(texto)
    if len(limpios) > MAX_INSTRUMENTOS:
        log.warning(
            "la configuración trae %d tickers y el tope es %d; se recortan los sobrantes",
            len(limpios),
            MAX_INSTRUMENTOS,
        )
        limpios = limpios[:MAX_INSTRUMENTOS]
    return tuple(limpios)


class LectorDashboard:
    """Acceso de solo lectura a la configuración que publica el dashboard.

    La conexión no se guarda entre lecturas, y es a propósito: SQLite entrega
    una instantánea al abrir, así que una conexión viva podría seguir
    devolviendo la configuración vieja después de que alguien pulse el
    interruptor — justo el fallo que este módulo existe para evitar. Abrir
    cuesta microsegundos y esto ocurre una vez por minuto.
    """

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def leer(self) -> ConfigCompartida:
        """Devuelve la foto actual, o lanza `ErrorDeConfig` si no se puede leer."""
        if not self.db_path.exists():
            raise ErrorDeConfig(
                f"No existe la base del dashboard en {self.db_path}. "
                "Revisa TRADINGLAB_DASHBOARD_DB."
            )
        try:
            conexion = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True, timeout=5.0)
        except sqlite3.Error as exc:
            raise ErrorDeConfig(f"No se pudo abrir la base del dashboard: {exc}") from exc

        try:
            conexion.row_factory = sqlite3.Row
            fila = conexion.execute(
                "SELECT enabled, mode, config_json, version, updated_by_email, updated_at "
                "FROM trading_bot_config WHERE bot_name = ?",
                (BOT_NAME,),
            ).fetchone()
        except sqlite3.Error as exc:
            raise ErrorDeConfig(
                f"No se pudo leer «trading_bot_config»: {exc}. "
                "¿Están aplicadas las migraciones del dashboard?"
            ) from exc
        finally:
            conexion.close()

        if fila is None:
            return ConfigCompartida.ausente()

        modo = _texto(fila, "mode")
        if modo != MODO_PAPER:
            # La barrera del esquema, vista desde este lado: aunque alguien
            # lograra escribir otro modo saltándose el CHECK del dashboard,
            # este proceso no va a ser el que lo ejecute.
            raise ErrorDeConfig(
                f"El modo declarado es «{modo}» y solo se admite «{MODO_PAPER}». "
                "TradingLab no opera fuera de simulación."
            )

        crudo = fila["config_json"]
        try:
            datos = json.loads(crudo) if isinstance(crudo, str | bytes) else (crudo or {})
        except (TypeError, ValueError) as exc:
            raise ErrorDeConfig(f"«config_json» no es JSON válido: {exc}") from exc
        if not isinstance(datos, dict):
            raise ErrorDeConfig(f"«config_json» debería ser un objeto y es {type(datos).__name__}.")

        return ConfigCompartida(
            habilitado=bool(fila["enabled"]),
            version=int(fila["version"] or 0),
            instrumentos=_instrumentos(datos),
            estrategia=str(datos.get("estrategia") or "").strip(),
            timeframe=str(datos.get("timeframe") or VALORES_POR_DEFECTO["timeframe"]),
            capital_simulado=_numero(datos, "capital_simulado", float),
            max_posiciones_abiertas=_numero(datos, "max_posiciones_abiertas", int),
            stop_loss_pct=_numero(datos, "stop_loss_pct", float),
            take_profit_pct=_numero(datos, "take_profit_pct", float),
            max_perdida_diaria_pct=_numero(datos, "max_perdida_diaria_pct", float),
            actualizada_por=_texto(fila, "updated_by_email"),
            actualizada_en=_texto(fila, "updated_at"),
        )
