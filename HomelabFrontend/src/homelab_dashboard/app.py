"""FastAPI app: rutas del dashboard.

La API JSON (`/api/v1/...`, con autenticación propia) es la única superficie
de servidor. El SPA de `frontend/dist` se monta en `/` con fallback: cualquier
ruta que no empiece por `/api` ni sea un archivo estático sirve `index.html` y
el enrutador de React decide qué pantalla mostrar. La UI Jinja heredada
(single-user, sin autenticación) se retiró junto con esta migración; su
reemplazo funcional vive en las pantallas de la SPA. El `JobManager` y la
fábrica de sesiones de base viven una sola vez por proceso, en `app.state`.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .api import api_router
from .api.errors import registrar_manejadores
from .db import create_db_engine, make_session_factory
from .jobs import JobManager
from .market_regime.dispatcher import RegimeDispatcher
from .market_regime.service import execute_run
from .migrate import upgrade_to_head
from .registry import RegistryError, load_registry
from .runner import JobRunner
from .scheduler import Scheduler
from .settings import Settings, load_settings

BASE_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Arranca y para el scheduler junto con el servidor.

    Al apagar no se matan los procesos en vuelo: terminan por su cuenta y, si
    el dashboard cae antes, `reconciliar_huerfanos` los cierra al arrancar.
    """
    if app.state.scheduler is not None:
        app.state.scheduler.start()
    try:
        yield
    finally:
        if app.state.scheduler is not None:
            app.state.scheduler.shutdown()


def _refrescar_apps_del_runner(app: FastAPI) -> None:
    """Carga `apps.yaml` en el runner.

    Se tolera un registro ausente o roto: el panel debe poder arrancar para
    que un admin entre a arreglarlo, en vez de quedarse sin servidor.
    """
    try:
        definiciones = load_registry(app.state.apps_file)
    except (RegistryError, OSError) as exc:
        logging.getLogger(__name__).warning("No se pudo cargar apps.yaml: %s", exc)
        definiciones = []
    app.state.runner.set_apps({d.name: d for d in definiciones})


def create_app(
    apps_file: str | Path | None = None,
    db_path: str | Path | None = None,
    logs_dir: str | Path | None = None,
    settings: Settings | None = None,
    *,
    run_migrations: bool = True,
) -> FastAPI:
    app = FastAPI(title="HomelabDashboard", lifespan=_lifespan)

    if settings is None:
        overrides = {}
        if apps_file is not None:
            overrides["apps_file"] = Path(apps_file)
        if db_path is not None:
            overrides["db_path"] = Path(db_path)
        if logs_dir is not None:
            overrides["logs_dir"] = Path(logs_dir)
        settings = load_settings(**overrides)

    settings.ensure_directories()
    if run_migrations:
        upgrade_to_head(settings)

    engine = create_db_engine(settings.db_path)

    app.state.settings = settings
    app.state.db_engine = engine
    app.state.session_factory = make_session_factory(engine)
    app.state.apps_file = str(settings.apps_file)
    app.state.job_manager = JobManager(
        db_path=str(settings.db_path), logs_dir=str(settings.logs_dir)
    )
    app.state.runner = JobRunner(settings, app.state.session_factory)
    _refrescar_apps_del_runner(app)
    app.state.runner.reconciliar_huerfanos()
    app.state.regime_dispatcher = (
        RegimeDispatcher(
            settings,
            app.state.session_factory,
            execute=lambda run_id, attempt: execute_run(
                app.state.session_factory,
                settings,
                run_id,
                attempt=attempt,
            ),
        )
        if settings.scheduler_enabled
        else None
    )
    app.state.scheduler = (
        Scheduler(
            settings,
            app.state.session_factory,
            app.state.runner,
            regime_dispatcher=app.state.regime_dispatcher,
        )
        if settings.scheduler_enabled
        else None
    )

    registrar_manejadores(app)
    app.include_router(api_router)

    _montar_spa(app, settings.frontend_dist)

    return app


def _montar_spa(app: FastAPI, dist_dir: Path) -> None:
    """Sirve el build de Vite, con fallback a `index.html` para el router de React.

    Si el `dist/` no existe todavía (por ejemplo en desarrollo, sirviendo con
    Vite aparte en :5173), el panel sigue funcionando como API pura: no es un
    error, solo faltan los archivos estáticos.
    """
    index_html = dist_dir / "index.html"
    if not index_html.is_file():
        logging.getLogger(__name__).warning(
            "No se encontró %s: la API sirve sin frontend. Corre `npm run build` en frontend/.",
            index_html,
        )
        return

    assets_dir = dist_dir / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="spa-assets")

    # Archivos sueltos servidos por Vite desde `public/` (favicon, íconos):
    # cualquiera que exista en la raíz de `dist/` además de `index.html`.
    archivos_raiz = {p.name for p in dist_dir.iterdir() if p.is_file() and p.name != "index.html"}

    @app.get("/{ruta_completa:path}", include_in_schema=False)
    async def _spa_fallback(request: Request, ruta_completa: str):
        if ruta_completa.startswith("api/"):
            return JSONResponse(
                {"error": {"code": "not_found", "message": "No encontrado."}},
                status_code=404,
            )

        primer_segmento = ruta_completa.split("/", 1)[0]
        if primer_segmento in archivos_raiz:
            return FileResponse(dist_dir / primer_segmento)

        return FileResponse(index_html)
