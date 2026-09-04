"""TradingLab: el motor de acciones y ETFs del homelab.

Lee la configuración que los usuarios autorizados guardan desde el dashboard,
opera contra Alpaca Paper y publica su estado en una base SQLite que el
dashboard lee en solo lectura. Nunca al revés: TradingLab no escribe en la base
del dashboard ni el dashboard escribe en la de TradingLab.

Opera **siempre** con dinero simulado. No hay ruta de código que toque una
cuenta real, y la tabla de configuración del dashboard tiene un `CHECK` que solo
admite `'paper'`.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
