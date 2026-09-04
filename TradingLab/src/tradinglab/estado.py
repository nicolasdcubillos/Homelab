"""La base de datos que TradingLab publica y el dashboard lee.

Es el lado visible del contrato: las dos tablas que `AdaptadorTradingLab`
consulta (`HomelabFrontend/docs/trading.md`, §5). Todo lo que se escriba aquí
acaba en una pantalla, así que las columnas están pensadas para responder
preguntas de esa pantalla y no para el gusto interno de este proceso.

Dos decisiones que conviene no deshacer sin leer esto:

**El diario de SQLite se deja en el modo por defecto, sin WAL.** WAL sería más
concurrente, pero un lector que abre con `mode=ro` necesita poder *escribir* el
archivo `-shm` para acceder a una base en WAL. El dashboard abre justo así, y si
ambos procesos no comparten usuario y permisos, fallaría con un «unable to open
database file» dificilísimo de diagnosticar. Aquí se escribe un puñado de filas
por hora, de modo que la concurrencia no es el problema a optimizar y el
diario clásico elimina toda esa clase de fallo.

**Todas las marcas de tiempo son ISO-8601 en UTC con desfase explícito**
(`+00:00`, nunca `Z`). Dos razones: el dashboard ordena las operaciones con
`ORDER BY abierta_en DESC`, y en ese formato el orden alfabético coincide con el
cronológico; y `datetime.fromisoformat` no aceptó el sufijo `Z` hasta Python
3.11, mientras que el dashboard declara soportar 3.10.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

#: Valores admitidos en `operaciones.lado`. Son los mismos que emite el
#: adaptador de Freqtrade en el dashboard, ya traducidos: la interfaz recibe un
#: único vocabulario y no el del motor que tocó responder. El `CHECK` de la
#: tabla lo vuelve estructural, para que un error de este proceso se detenga
#: aquí y no llegue a la pantalla como una fila sin etiqueta.
COMPRA = "compra"
VENTA = "venta"

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS estado_motor (
    -- Una sola fila, y el CHECK lo hace imposible de violar. El dashboard lee
    -- con ORDER BY ... LIMIT 1, así que toleraría varias; pero un historial de
    -- latidos no le sirve a nadie y crecería sin límite.
    id                  INTEGER PRIMARY KEY CHECK (id = 1),
    latido_en           TEXT    NOT NULL,
    detalle             TEXT    NOT NULL DEFAULT '',
    posiciones_abiertas INTEGER NOT NULL DEFAULT 0,
    version             TEXT
);

CREATE TABLE IF NOT EXISTS operaciones (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    instrumento    TEXT    NOT NULL,
    lado           TEXT    NOT NULL CHECK (lado IN ('compra', 'venta')),
    cantidad       REAL    NOT NULL,
    precio_entrada REAL    NOT NULL,
    precio_salida  REAL,
    -- Neto: los costos ya están descontados. La pantalla lo afirma de forma
    -- explícita ("Ya están descontados del resultado"), así que restarlos aquí
    -- es parte del contrato y no una comodidad.
    pnl_absoluto   REAL,
    pnl_pct        REAL,
    costos         REAL    NOT NULL DEFAULT 0,
    abierta_en     TEXT    NOT NULL,
    cerrada_en     TEXT,
    -- Desde aquí, columnas que el dashboard no lee pero sin las cuales no se
    -- puede operar ni auditar lo ocurrido.
    orden_entrada  TEXT,
    orden_salida   TEXT,
    motivo_salida  TEXT,
    -- Tasa representativa del mercado el día de la apertura. Hoy no se usa,
    -- pero operar a diario configura habitualidad ante la DIAN y entonces hará
    -- falta el histórico en pesos. Reconstruirla después sale mucho más caro
    -- que anotarla al vuelo (ver docs/trading.md §7).
    trm            REAL
);

CREATE INDEX IF NOT EXISTS ix_operaciones_abiertas
    ON operaciones (cerrada_en) WHERE cerrada_en IS NULL;

CREATE INDEX IF NOT EXISTS ix_operaciones_abierta_en
    ON operaciones (abierta_en DESC);
"""


def ahora_iso() -> str:
    """Marca de tiempo en el único formato que esta base admite."""
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class Apertura:
    """Una posición que se acaba de abrir."""

    instrumento: str
    lado: str
    cantidad: float
    precio_entrada: float
    costos: float = 0.0
    orden_entrada: str | None = None
    trm: float | None = None


@dataclass(frozen=True)
class PosicionAbierta:
    """Una posición viva, tal como hace falta para decidir si cerrarla."""

    id: int
    instrumento: str
    lado: str
    cantidad: float
    precio_entrada: float
    costos: float
    abierta_en: str

    def pnl_bruto(self, precio: float) -> float:
        """Resultado sin descontar costos, al precio que se le pase."""
        signo = 1.0 if self.lado == COMPRA else -1.0
        return (precio - self.precio_entrada) * self.cantidad * signo

    def variacion_pct(self, precio: float) -> float:
        """Movimiento del precio a favor, en porcentaje.

        Se calcula sobre el precio de entrada y no sobre el resultado neto,
        porque es contra esto contra lo que se comparan el stop loss y el take
        profit, que son umbrales de precio.
        """
        if not self.precio_entrada:
            return 0.0
        signo = 1.0 if self.lado == COMPRA else -1.0
        return (precio - self.precio_entrada) / self.precio_entrada * 100.0 * signo


class AlmacenEstado:
    """Dueño del archivo SQLite que TradingLab publica."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self._conexion: sqlite3.Connection | None = None

    # ------------------------------------------------------------ ciclo de vida

    def abrir(self) -> None:
        if self._conexion is not None:
            return
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conexion = sqlite3.connect(self.db_path, timeout=10.0)
        conexion.row_factory = sqlite3.Row
        conexion.executescript(_ESQUEMA)
        conexion.commit()
        self._conexion = conexion

    def cerrar(self) -> None:
        if self._conexion is not None:
            self._conexion.close()
            self._conexion = None

    def __enter__(self) -> AlmacenEstado:
        self.abrir()
        return self

    def __exit__(self, *_: object) -> None:
        self.cerrar()

    @property
    def conexion(self) -> sqlite3.Connection:
        if self._conexion is None:
            raise RuntimeError("AlmacenEstado usado sin abrir()")
        return self._conexion

    # ------------------------------------------------------------------- latido

    def latir(
        self,
        *,
        detalle: str,
        posiciones_abiertas: int = 0,
        version: str | None = None,
        momento: str | None = None,
    ) -> None:
        """Deja constancia de que el proceso sigue vivo.

        Es lo único que el dashboard usa para distinguir «en pausa» de «caído»,
        así que se escribe en cada vuelta del bucle pase lo que pase — incluso,
        y sobre todo, cuando el ciclo terminó en error: un motor que falla y lo
        cuenta es mucho más útil que uno que desaparece en silencio.
        """
        self.conexion.execute(
            "INSERT INTO estado_motor (id, latido_en, detalle, posiciones_abiertas, version) "
            "VALUES (1, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET "
            "latido_en = excluded.latido_en, detalle = excluded.detalle, "
            "posiciones_abiertas = excluded.posiciones_abiertas, version = excluded.version",
            (momento or ahora_iso(), detalle, int(posiciones_abiertas), version),
        )
        self.conexion.commit()

    def ultimo_latido(self) -> sqlite3.Row | None:
        return self.conexion.execute(
            "SELECT latido_en, detalle, posiciones_abiertas, version FROM estado_motor WHERE id = 1"
        ).fetchone()

    # -------------------------------------------------------------- operaciones

    def registrar_apertura(self, apertura: Apertura, *, momento: str | None = None) -> int:
        if apertura.lado not in (COMPRA, VENTA):
            raise ValueError(f"lado inválido: {apertura.lado!r}")
        cursor = self.conexion.execute(
            "INSERT INTO operaciones "
            "(instrumento, lado, cantidad, precio_entrada, costos, abierta_en, "
            "orden_entrada, trm) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                apertura.instrumento,
                apertura.lado,
                float(apertura.cantidad),
                float(apertura.precio_entrada),
                float(apertura.costos),
                momento or ahora_iso(),
                apertura.orden_entrada,
                apertura.trm,
            ),
        )
        self.conexion.commit()
        return int(cursor.lastrowid or 0)

    def registrar_cierre(
        self,
        operacion_id: int,
        *,
        precio_salida: float,
        costos_salida: float = 0.0,
        motivo: str = "",
        orden_salida: str | None = None,
        momento: str | None = None,
    ) -> None:
        """Cierra una posición y calcula su resultado neto.

        El PnL se calcula aquí y no en quien llama, para que exista un solo
        sitio donde se decide qué significa «ganancia» — con los costos ya
        restados y el porcentaje medido contra el capital que la operación
        realmente inmovilizó.
        """
        fila = self.conexion.execute(
            "SELECT lado, cantidad, precio_entrada, costos FROM operaciones WHERE id = ?",
            (operacion_id,),
        ).fetchone()
        if fila is None:
            raise ValueError(f"no existe la operación {operacion_id}")

        signo = 1.0 if fila["lado"] == COMPRA else -1.0
        cantidad = float(fila["cantidad"])
        entrada = float(fila["precio_entrada"])
        costos = float(fila["costos"] or 0.0) + float(costos_salida)
        bruto = (float(precio_salida) - entrada) * cantidad * signo
        neto = bruto - costos
        expuesto = abs(entrada * cantidad)
        pct = (neto / expuesto * 100.0) if expuesto else 0.0

        self.conexion.execute(
            "UPDATE operaciones SET precio_salida = ?, pnl_absoluto = ?, pnl_pct = ?, "
            "costos = ?, cerrada_en = ?, orden_salida = ?, motivo_salida = ? "
            "WHERE id = ?",
            (
                float(precio_salida),
                neto,
                pct,
                costos,
                momento or ahora_iso(),
                orden_salida,
                motivo,
                operacion_id,
            ),
        )
        self.conexion.commit()

    def abiertas(self) -> list[PosicionAbierta]:
        filas = self.conexion.execute(
            "SELECT id, instrumento, lado, cantidad, precio_entrada, costos, abierta_en "
            "FROM operaciones WHERE cerrada_en IS NULL ORDER BY abierta_en"
        ).fetchall()
        return [
            PosicionAbierta(
                id=int(fila["id"]),
                instrumento=fila["instrumento"],
                lado=fila["lado"],
                cantidad=float(fila["cantidad"]),
                precio_entrada=float(fila["precio_entrada"]),
                costos=float(fila["costos"] or 0.0),
                abierta_en=fila["abierta_en"],
            )
            for fila in filas
        ]

    def instrumentos_abiertos(self) -> set[str]:
        return {posicion.instrumento for posicion in self.abiertas()}

    def pnl_del_dia(self, dia: str | None = None) -> float:
        """Resultado neto de lo cerrado hoy, en dinero.

        Alimenta el freno de pérdida diaria. Cuenta solo lo **cerrado**: una
        posición abierta que va perdiendo todavía puede darse la vuelta, y
        frenar por pérdidas no realizadas convertiría cualquier vaivén
        intradía en una parada del bot.
        """
        prefijo = dia or datetime.now(UTC).date().isoformat()
        fila = self.conexion.execute(
            "SELECT COALESCE(SUM(pnl_absoluto), 0) AS pnl FROM operaciones "
            "WHERE cerrada_en IS NOT NULL AND substr(cerrada_en, 1, 10) = ?",
            (prefijo,),
        ).fetchone()
        return float(fila["pnl"] or 0.0)

    def ultimas(self, limite: int = 20) -> list[sqlite3.Row]:
        return self.conexion.execute(
            "SELECT * FROM operaciones ORDER BY abierta_en DESC LIMIT ?", (limite,)
        ).fetchall()
