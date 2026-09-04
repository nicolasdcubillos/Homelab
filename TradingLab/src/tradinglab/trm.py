"""La TRM del día, para poder leer las ganancias en pesos.

El motor opera en dólares porque las acciones cotizan en dólares, pero quien mira
el panel piensa en pesos. Anotar la tasa **del día de la apertura** en cada
operación permite reconstruir después cuánto valía en pesos aquello, sin
reescribir el histórico cada vez que el dólar se mueve.

Reglas de esta pieza
--------------------
1. **Nunca lanza.** Una operación no se puede caer porque datos.gov.co esté
   lento. Si no hay tasa, la columna queda nula y el dashboard lo muestra vacío.
2. **Solo biblioteca estándar.** Añadir una dependencia HTTP para una llamada al
   día sería desproporcionado, y el paquete se instala en una VM pequeña.
3. **Una consulta por día, como mucho.** La TRM cambia una vez al día; pedirla en
   cada vuelta del supervisor sería mil llamadas diarias para el mismo número.

Fuente: dataset `32sa-8pi3` del portal de datos abiertos de Colombia (la TRM que
publica la Superintendencia Financiera).
"""

from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

log = logging.getLogger("tradinglab.trm")

URL_BASE = "https://www.datos.gov.co/resource/32sa-8pi3.json"

#: Corto a propósito. Si el portal no responde en este tiempo, la respuesta
#: correcta es seguir operando sin tasa, no esperar.
TIMEOUT_SEG = 8.0


@dataclass
class ProveedorTRM:
    """Obtiene la TRM vigente y la recuerda hasta que cambie el día."""

    timeout_seg: float = TIMEOUT_SEG
    _cache: tuple[date, float] | None = field(default=None, init=False, repr=False)
    #: Se recuerda también el fracaso, para no reintentar en cada latido cuando
    #: la VM no tiene salida a internet.
    _fallo_del_dia: date | None = field(default=None, init=False, repr=False)

    def obtener(self, hoy: date | None = None) -> float | None:
        dia = hoy or datetime.now(UTC).date()

        if self._cache is not None and self._cache[0] == dia:
            return self._cache[1]
        if self._fallo_del_dia == dia:
            return None

        valor = self._consultar_vigente(dia)
        if valor is None:
            # La publicación del día puede tardar. Antes de rendirse se pide la
            # última tasa conocida: para convertir a pesos, la de ayer es
            # muchísimo mejor aproximación que ninguna.
            valor = self._consultar_ultima()

        if valor is None:
            self._fallo_del_dia = dia
            return None

        self._cache = (dia, valor)
        self._fallo_del_dia = None
        return valor

    # ------------------------------------------------------------------ interno

    def _consultar_vigente(self, dia: date) -> float | None:
        # La tasa de un viernes rige hasta el domingo, así que la consulta
        # correcta no es «la del día» sino «la que cubre el día».
        marca = f"{dia.isoformat()}T00:00:00.000"
        filtro = f"vigenciadesde <= '{marca}' AND vigenciahasta >= '{marca}'"
        return self._pedir({"$limit": "1", "$where": filtro})

    def _consultar_ultima(self) -> float | None:
        return self._pedir({"$limit": "1", "$order": "vigenciadesde DESC"})

    def _pedir(self, parametros: dict[str, str]) -> float | None:
        url = f"{URL_BASE}?{urllib.parse.urlencode(parametros)}"
        try:
            peticion = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(peticion, timeout=self.timeout_seg) as respuesta:
                crudo = respuesta.read()
        except Exception as exc:
            log.info("no se pudo consultar la TRM: %s", exc)
            return None

        try:
            filas = json.loads(crudo)
        except (ValueError, TypeError):
            log.info("la respuesta de la TRM no era JSON")
            return None

        if not isinstance(filas, list) or not filas:
            return None
        return _a_float(filas[0].get("valor"))


def _a_float(valor: object) -> float | None:
    """El portal devuelve el valor como cadena, no como número."""
    if valor is None:
        return None
    try:
        numero = float(str(valor).replace(",", ""))
    except (TypeError, ValueError):
        return None
    # Una TRM de cero o negativa es un dato corrupto, y dividir por ella daría
    # cifras absurdas en el panel.
    return numero if numero > 0 else None
