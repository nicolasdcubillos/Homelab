"""FastAPI app: rutas del dashboard.

La app recarga `apps.yaml` en cada request de listado/detalle para reflejar
cambios sin necesidad de reiniciar el proceso. El `JobManager` (subprocess +
SQLite) sí vive una sola vez por proceso, en `app.state`.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import config_editor
from .jobs import JobAlreadyRunningError, JobManager
from .registry import AppDefinition, RegistryError, load_registry

BASE_DIR = Path(__file__).resolve().parent


def create_app(
    apps_file: str | Path | None = None,
    db_path: str | Path | None = None,
    logs_dir: str | Path | None = None,
) -> FastAPI:
    app = FastAPI(title="HomelabDashboard")

    apps_file = apps_file or os.environ.get("DASHBOARD_APPS_FILE", "apps.yaml")
    db_path = db_path or os.environ.get("DASHBOARD_DB_FILE", "dashboard.db")
    logs_dir = logs_dir or os.environ.get("DASHBOARD_LOGS_DIR", "logs")

    app.state.apps_file = apps_file
    app.state.job_manager = JobManager(db_path=db_path, logs_dir=logs_dir)

    templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

    def _job_manager(request: Request) -> JobManager:
        return request.app.state.job_manager

    def _load_apps(request: Request) -> list[AppDefinition]:
        try:
            return load_registry(request.app.state.apps_file)
        except RegistryError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    def _get_app_or_404(request: Request, name: str) -> AppDefinition:
        for a in _load_apps(request):
            if a.name == name:
                return a
        raise HTTPException(status_code=404, detail=f"App '{name}' no encontrada en el registro")

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        jm = _job_manager(request)
        apps = _load_apps(request)
        cards = []
        for a in apps:
            last_run = jm.last_run(a.name) if a.is_installed else None
            cards.append(
                {
                    "app": a,
                    "installed": a.is_installed,
                    "running": jm.is_running(a.name) if a.is_installed else False,
                    "last_run": last_run,
                }
            )
        return templates.TemplateResponse(
            request, "index.html", {"cards": cards}
        )

    @app.get("/apps/{name}", response_class=HTMLResponse)
    def app_detail(request: Request, name: str):
        jm = _job_manager(request)
        a = _get_app_or_404(request, name)

        config_contents = {}
        if a.is_installed:
            for cf in a.config_files:
                try:
                    config_contents[cf.path] = config_editor.read_config(a, cf)
                except ValueError as exc:
                    config_contents[cf.path] = f"# ERROR leyendo archivo: {exc}"

        history = jm.history(a.name) if a.is_installed else []
        running = jm.is_running(a.name) if a.is_installed else False

        return templates.TemplateResponse(
            request,
            "app_detail.html",
            {
                "app": a,
                "installed": a.is_installed,
                "running": running,
                "config_contents": config_contents,
                "history": history,
            },
        )

    @app.post("/apps/{name}/config")
    def save_config(
        request: Request,
        name: str,
        rel_path: str = Form(...),
        content: str = Form(...),
    ):
        a = _get_app_or_404(request, name)
        if not a.is_installed:
            raise HTTPException(status_code=400, detail="La app no está instalada")
        cf = a.config_file_by_path(rel_path)
        if cf is None:
            raise HTTPException(status_code=400, detail="Archivo de configuración no reconocido")
        try:
            config_editor.write_config(a, cf, content)
        except config_editor.ConfigEditorError as exc:
            return RedirectResponse(
                url=f"/apps/{name}?error={_url_quote(str(exc))}", status_code=303
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return RedirectResponse(url=f"/apps/{name}?saved={_url_quote(rel_path)}", status_code=303)

    @app.post("/apps/{name}/commands/{command_key}")
    def run_command(request: Request, name: str, command_key: str):
        jm = _job_manager(request)
        a = _get_app_or_404(request, name)
        if not a.is_installed:
            raise HTTPException(status_code=400, detail="La app no está instalada")
        command = a.command_by_key(command_key)
        if command is None:
            raise HTTPException(status_code=400, detail="Comando no reconocido")
        try:
            record = jm.start_job(a, command)
        except JobAlreadyRunningError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return JSONResponse({"ok": True, "run_id": record.id})

    @app.get("/apps/{name}/status")
    def status(request: Request, name: str):
        jm = _job_manager(request)
        a = _get_app_or_404(request, name)
        last_run = jm.last_run(a.name) if a.is_installed else None
        running = jm.is_running(a.name) if a.is_installed else False
        return JSONResponse(
            {
                "installed": a.is_installed,
                "running": running,
                "last_run": _record_to_dict(last_run) if last_run else None,
            }
        )

    @app.get("/apps/{name}/log", response_class=PlainTextResponse)
    def log_tail(request: Request, name: str, run_id: int | None = None, lines: int = 200):
        jm = _job_manager(request)
        a = _get_app_or_404(request, name)
        record = jm.get_run(run_id) if run_id else jm.last_run(a.name)
        if record is None:
            return PlainTextResponse("(no hay ejecuciones todavía)")
        return PlainTextResponse(jm.tail_log(record.log_path, lines=lines))

    return app


def _record_to_dict(record) -> dict:
    return {
        "id": record.id,
        "command_label": record.command_label,
        "started_at": record.started_at,
        "finished_at": record.finished_at,
        "duration_seconds": record.duration_seconds,
        "status": record.status,
        "return_code": record.return_code,
    }


def _url_quote(s: str) -> str:
    from urllib.parse import quote

    return quote(s, safe="")
