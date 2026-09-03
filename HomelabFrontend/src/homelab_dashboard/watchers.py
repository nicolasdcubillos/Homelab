"""Todo lo que el dashboard sabe de los watchers administrados.

Este módulo concentra el conocimiento del contrato de PortfolioWatcher y
StockWatcher: qué YAML esperan, con qué claves, qué variables de entorno leen
y qué argumentos hay que pasarles. Está aislado a propósito para que, cuando
esos repos cambien, haya un solo archivo que tocar — y para que
`docs/watchers-contract.md` tenga un referente exacto en el código.

Contratos verificados leyendo el código de cada repo (no asumidos):

**StockWatcher** (`src/stockwatcher/config.py`)
- `load_config(watches_path, stores_path)` lee un mapa con `defaults`,
  `watches[]`, `stores[]`, `discovery`, `notify_options`, `runtime`, `state`.
- `watches` **no puede estar vacío**: lanza `ConfigError`.
- Cada watch admite `name`, `match[]` (obligatorio, no vacío), `exclude[]`,
  `variants[]` (o `sizes`), `gender`, `colors[]`, `max_price`, `currency`,
  `countries[]`, `notify[]`, `stores[]`, `queries[]`, `enabled`.
- Las claves de `state` se validan contra un dataclass que **rechaza claves
  desconocidas**.
- `--watches`, `--stores`, `--state-path` y `--state-backend` son flags
  *globales*: van antes del subcomando.
- `--notify-to` (repetible, `[canal:]destino`) tiene precedencia sobre
  `WHATSAPP_TO`/`EMAIL_TO` y sobre `watches[].notify`, y sí distingue destino
  por canal (`--notify-to whatsapp:+57... --notify-to email:...`). Lo usamos
  como mecanismo principal por invocación (ver `construir_argumentos`).
- La tabla de tiendas descubiertas ya no se escribe en el estado por usuario;
  hay un registro compartido de solo lectura (`discovery/registry.py`) que no
  tocamos porque seguimos con el descubrimiento desactivado por defecto.

**PortfolioWatcher** (`src/portfoliowatcher/config.py`, `notifier.py`, `cli.py`)
- `load_config(path)` lee `analysis_interval_days`, `risk_profile`,
  `holdings[]`, `closed_positions[]`, y ahora también `notifiers`/`state_path`
  como base (el entorno los sigue pudiendo sobreescribir).
- `holdings` **no puede estar vacío**: ya no lanza una excepción sin
  controlar, pero seguimos evitando la corrida con el `readiness` del
  scheduler.
- Notificadores registrados: `console`, `whatsapp`, `email` (ACS, mismo
  contrato de claves que StockWatcher) y `telegram` (ya implementado, no es
  un stub).
- `--notify-to` (flag global) tiene precedencia sobre `WHATSAPP_TO`/
  `EMAIL_TO`, pero se aplica **igual a todos los notificadores activos**
  (`options = {"to": notify_to}` para cada uno) — no distingue destino por
  canal. Por eso solo lo usamos cuando el usuario tiene un único canal activo
  con destino (ver `construir_argumentos`); con dos canales activos y
  destinos distintos (un teléfono y un correo) seguimos con las variables de
  entorno, que sí son por canal.
- `PORTFOLIOWATCHER_INTERVAL_OVERRIDE` ya se lee de verdad en
  `apply_env_overrides`. Seguimos escribiendo `analysis_interval_days`
  directo en el YAML generado (ver nota en `generar_portfolio_yaml`) porque
  ya resuelve el caso sin depender del entorno.
"""

from __future__ import annotations

from dataclasses import dataclass

import yaml

from .models import (
    CHANNEL_EMAIL,
    CHANNEL_WHATSAPP,
    GENDER_UNISEX,
    PortfolioClosedPosition,
    PortfolioHolding,
    PortfolioProfile,
    StockWatch,
)

APP_STOCKWATCHER = "stockwatcher"
APP_PORTFOLIOWATCHER = "portfoliowatcher"


@dataclass(frozen=True)
class WatcherSpec:
    """Descripción declarativa de un watcher administrado."""

    app_name: str
    display_name: str
    config_filename: str
    state_filename: str
    #: Canales de notificación que el watcher sabe entregar de verdad.
    canales_soportados: tuple[str, ...]
    #: Qué debe tener configurado el usuario para que una corrida no aborte.
    requisito: str
    #: Dónde acepta cada CLI su `--dry-run`. Los dos watchers difieren: en
    #: StockWatcher es una opción del subcomando `run`, y en PortfolioWatcher
    #: es global. Ponerla en el sitio equivocado hace que argparse aborte.
    dry_run_flag: str = "--dry-run"
    dry_run_global: bool = False


STOCKWATCHER = WatcherSpec(
    app_name=APP_STOCKWATCHER,
    display_name="StockWatcher",
    config_filename="watches.yaml",
    state_filename="stockwatcher.db",
    canales_soportados=(CHANNEL_WHATSAPP, CHANNEL_EMAIL),
    requisito="al menos un producto vigilado activo",
    dry_run_global=False,
)

PORTFOLIOWATCHER = WatcherSpec(
    app_name=APP_PORTFOLIOWATCHER,
    display_name="PortfolioWatcher",
    # Hallazgo 1 del contrato (resuelto en el commit 8bfa9fd): PortfolioWatcher
    # ahora tiene un `EmailNotifier` sobre ACS registrado como "email", así que
    # la UI ya puede ofrecer ambos canales para esta app.
    config_filename="portfolio.yaml",
    state_filename="portfoliowatcher.db",
    canales_soportados=(CHANNEL_WHATSAPP, CHANNEL_EMAIL),
    requisito="al menos una posición en el portafolio",
    dry_run_global=True,
)

WATCHERS: dict[str, WatcherSpec] = {
    STOCKWATCHER.app_name: STOCKWATCHER,
    PORTFOLIOWATCHER.app_name: PORTFOLIOWATCHER,
}


def spec_de(app_name: str) -> WatcherSpec | None:
    return WATCHERS.get(app_name)


def es_watcher_conocido(app_name: str) -> bool:
    return app_name in WATCHERS


# ---------------------------------------------------------------------------
# Serialización a YAML
# ---------------------------------------------------------------------------


_CABECERA = (
    "# Archivo generado automáticamente por HomelabDashboard.\n"
    "# No lo edites a mano: se reescribe en cada ejecución a partir de la\n"
    "# configuración del usuario en el panel.\n"
)


def _volcar(datos: dict) -> str:
    cuerpo = yaml.safe_dump(
        datos,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )
    return _CABECERA + cuerpo


def generar_watches_yaml(
    watches: list[StockWatch],
    *,
    state_path: str,
    canales_activos: set[str],
) -> str:
    """Genera el `watches.yaml` de un usuario.

    No se emite el bloque `defaults`: StockWatcher lo fusiona con cada watch
    (`{**defaults, **raw}`), así que escribir cada campo explícitamente evita
    depender de esa semántica y hace el archivo autoexplicativo.

    `canales_activos` filtra los canales que el usuario apagó para esta app,
    de modo que apagar WhatsApp en el panel realmente silencie el envío.
    """
    lista = []
    for watch in watches:
        if not watch.enabled:
            continue
        notify = [c for c in watch.notify_channels if c in canales_activos]
        entrada: dict = {
            "name": watch.name,
            "match": list(watch.match_terms),
            "enabled": True,
            "gender": watch.gender or GENDER_UNISEX,
            "currency": watch.currency or "USD",
            "countries": list(watch.countries) or ["US"],
            "notify": notify,
        }
        if watch.exclude_terms:
            entrada["exclude"] = list(watch.exclude_terms)
        if watch.variants:
            entrada["variants"] = list(watch.variants)
        if watch.colors:
            entrada["colors"] = list(watch.colors)
        if watch.max_price:
            # Se emite como texto: StockWatcher lo pasa por `Decimal(str(v))`,
            # y un float de YAML podría introducir error de redondeo en dinero.
            entrada["max_price"] = str(watch.max_price)
        lista.append(entrada)

    return _volcar(
        {
            "watches": lista,
            # Estado por usuario: sin esto, el primero en correr marcaría los
            # hallazgos como vistos y el resto no recibiría nada.
            "state": {"backend": "sqlite", "path": state_path},
        }
    )


def generar_portfolio_yaml(
    perfil: PortfolioProfile | None,
    holdings: list[PortfolioHolding],
    cerradas: list[PortfolioClosedPosition],
) -> str:
    """Genera el `portfolio.yaml` de un usuario.

    `analysis_interval_days` se escribe directo en el YAML, que `load_config`
    lee sin depender del entorno. El hallazgo 3 del contrato (el no-op de
    `--interval-days`) quedó resuelto en el commit `8bfa9fd`:
    `PORTFOLIOWATCHER_INTERVAL_OVERRIDE` ya se lee de verdad en
    `apply_env_overrides`. No migramos a esa variable porque el YAML ya
    resuelve el caso sin ninguna dependencia del entorno del subprocess, que
    es justo lo que queremos minimizar (§1 del contrato).

    Ni `state_path` ni `notifiers` se emiten aquí aunque `load_config` ya los
    lee del YAML desde el commit `8bfa9fd` (hallazgo 4 resuelto): seguimos
    inyectándolos por `env=` en `construir_entorno` porque son valores que
    dependen del workspace de ejecución (ruta absoluta por usuario), no del
    contenido versionable de la config, y mantenerlos fuera del YAML evita
    que `config-preview` filtre esas rutas.
    """
    datos: dict = {
        "analysis_interval_days": perfil.analysis_interval_days if perfil else 7,
        "risk_profile": {
            "horizon": perfil.horizon if perfil else "long_term",
            "tolerance": perfil.tolerance if perfil else "moderate",
            "notes": perfil.notes if perfil else "",
        },
        "holdings": [
            {
                "ticker": h.ticker,
                "quantity": h.quantity,
                "avg_cost": h.avg_cost,
                "sector_hint": h.sector_hint or "unknown",
            }
            for h in holdings
        ],
    }
    if cerradas:
        datos["closed_positions"] = [
            {"ticker": c.ticker, "note": c.note or ""} for c in cerradas
        ]
    return _volcar(datos)


# ---------------------------------------------------------------------------
# Entorno de ejecución
# ---------------------------------------------------------------------------

#: Variables que el dashboard *siempre* fija al lanzar un watcher, aunque el
#: usuario no tenga ese canal configurado. Fijarlas en vacío es deliberado: si
#: se dejaran sin definir, el `.env` del repo administrado aportaría el destino
#: del dueño de la máquina y un usuario recibiría las alertas de otro.
VARIABLES_DE_DESTINO = (
    "WHATSAPP_TO",
    "EMAIL_TO",
    "EMAIL_SUBJECT",
    "PORTFOLIOWATCHER_NOTIFIERS",
    "PORTFOLIOWATCHER_STATE_PATH",
    "PORTFOLIOWATCHER_CONFIG_PATH",
    "STOCKWATCHER_STATE_PATH",
    "STOCKWATCHER_STATE_BACKEND",
)


def construir_entorno(
    spec: WatcherSpec,
    *,
    destinos: dict[str, str],
    canales_activos: set[str],
    state_path: str,
    config_path: str,
) -> dict[str, str]:
    """Variables de entorno específicas del usuario para una corrida.

    Se devuelven **todas** las claves de `VARIABLES_DE_DESTINO`, vacías cuando
    no aplican. Esa exhaustividad es la defensa principal contra el cruce de
    notificaciones entre usuarios: el `.env` del repo administrado solo puede
    aportar un valor si la variable no está ya en el entorno del proceso
    (`python-dotenv` usa `override=False`), así que definirlas todas cierra
    esa puerta.
    """
    entorno = dict.fromkeys(VARIABLES_DE_DESTINO, "")

    whatsapp = destinos.get(CHANNEL_WHATSAPP, "")
    email = destinos.get(CHANNEL_EMAIL, "")

    if CHANNEL_WHATSAPP in canales_activos and CHANNEL_WHATSAPP in spec.canales_soportados:
        entorno["WHATSAPP_TO"] = whatsapp
    if CHANNEL_EMAIL in canales_activos and CHANNEL_EMAIL in spec.canales_soportados:
        entorno["EMAIL_TO"] = email
        entorno["EMAIL_SUBJECT"] = f"{spec.display_name}: novedades"

    if spec.app_name == APP_PORTFOLIOWATCHER:
        activos = [
            c
            for c in spec.canales_soportados
            if c in canales_activos and destinos.get(c)
        ]
        entorno["PORTFOLIOWATCHER_NOTIFIERS"] = ",".join(activos)
        entorno["PORTFOLIOWATCHER_STATE_PATH"] = state_path
        entorno["PORTFOLIOWATCHER_CONFIG_PATH"] = config_path
    elif spec.app_name == APP_STOCKWATCHER:
        entorno["STOCKWATCHER_STATE_PATH"] = state_path
        entorno["STOCKWATCHER_STATE_BACKEND"] = "sqlite"

    return entorno


def _canales_con_destino(
    spec: WatcherSpec, *, destinos: dict[str, str], canales_activos: set[str]
) -> list[tuple[str, str]]:
    """Pares `(canal, destino)` activos y soportados, en orden estable."""
    return [
        (canal, destinos[canal])
        for canal in spec.canales_soportados
        if canal in canales_activos and destinos.get(canal)
    ]


def construir_argumentos(
    spec: WatcherSpec,
    *,
    config_path: str,
    state_path: str,
    stores_path: str | None,
    destinos: dict[str, str] | None = None,
    canales_activos: set[str] | None = None,
) -> list[str]:
    """Argumentos que se anteponen a los del comando declarado en `apps.yaml`.

    Ambos CLIs usan un parser global de argparse, así que estos flags tienen
    que ir **antes** del subcomando (`run`, `daily`, ...).

    Migración del hallazgo 2 del contrato: ambos repos ya aceptan `--notify-to`
    con precedencia sobre las variables de entorno, así que preferimos pasar
    el destino explícito por invocación en vez de depender solo de la
    precedencia implícita de `load_dotenv`. Las variables de entorno de
    `construir_entorno` se conservan como segunda capa de defensa (nunca se
    dejan sin definir), pero `--notify-to` es ahora el mecanismo primario
    cuando el CLI lo permite expresar sin ambigüedad.
    """
    destinos = destinos or {}
    canales_activos = canales_activos or set()
    canales = _canales_con_destino(spec, destinos=destinos, canales_activos=canales_activos)

    if spec.app_name == APP_STOCKWATCHER:
        args = ["--watches", config_path, "--state-backend", "sqlite", "--state-path", state_path]
        if stores_path:
            args += ["--stores", stores_path]
        # StockWatcher soporta --notify-to repetible con prefijo de canal, así
        # que puede expresar un teléfono y un correo distintos en la misma
        # invocación sin ambigüedad.
        for canal, destino in canales:
            args += ["--notify-to", f"{canal}:{destino}"]
        return args
    if spec.app_name == APP_PORTFOLIOWATCHER:
        args = ["--config", config_path]
        # PortfolioWatcher aplica --notify-to por igual a todos los
        # notificadores activos (no distingue canal), así que solo es seguro
        # usarlo cuando hay un único canal activo con destino. Con dos
        # canales y destinos distintos (teléfono vs. correo), lo omitimos y
        # dejamos que las variables de entorno por canal hagan el trabajo.
        if len(canales) == 1:
            args += ["--notify-to", canales[0][1]]
        return args
    return []
