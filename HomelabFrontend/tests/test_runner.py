"""Tests de la ejecución por usuario.

Se lanzan procesos de verdad contra un watcher falso: es la única forma de
comprobar el entorno inyectado, la cancelación y los locks sin simular justo
la parte que puede fallar. El script falso imprime lo que recibe, de modo que
el test puede afirmar sobre el entorno real del subproceso.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from homelab_dashboard.app import create_app
from homelab_dashboard.models import (
    CHANNEL_WHATSAPP,
    JOB_CANCELLED,
    JOB_ERROR,
    JOB_RUNNING,
    JOB_SUCCESS,
    AppChannelPref,
    JobRun,
    NotificationChannel,
    StockWatch,
    User,
)
from homelab_dashboard.runner import (
    DemasiadosJobs,
    JobRunner,
    NoEstaListo,
    YaEstaCorriendo,
)
from homelab_dashboard.security import hash_password


@pytest.fixture()
def app_watchers(settings, apps_watchers):
    return create_app(settings=replace(settings, apps_file=apps_watchers))


@pytest.fixture()
def runner(app_watchers) -> JobRunner:
    return app_watchers.state.runner


@pytest.fixture()
def sesion(app_watchers):
    with app_watchers.state.session_factory() as db:
        yield db


def _usuario_listo(db, email="ana@example.com", destino="+573001112233") -> User:
    usuario = User(
        email=email,
        password_hash=hash_password("Contrasena123"),
        role="user",
        status="active",
    )
    db.add(usuario)
    db.flush()
    db.add(
        StockWatch(
            user_id=usuario.id,
            name="Zapatillas",
            match_terms=["air max"],
            countries=["CO"],
            notify_channels=[CHANNEL_WHATSAPP],
        )
    )
    db.add(
        NotificationChannel(
            user_id=usuario.id, channel=CHANNEL_WHATSAPP, destination=destino
        )
    )
    db.add(
        AppChannelPref(
            user_id=usuario.id,
            app_name="stockwatcher",
            channel=CHANNEL_WHATSAPP,
            enabled=True,
        )
    )
    db.commit()
    return usuario


def _esperar(runner, user_id, app_name="stockwatcher", limite=15.0) -> None:
    fin = time.monotonic() + limite
    while time.monotonic() < fin:
        if not runner.esta_corriendo(user_id, app_name):
            return
        time.sleep(0.05)
    raise AssertionError("La ejecución no terminó a tiempo.")


def _volcado(runner, run: JobRun) -> dict:
    contenido = Path(run.log_path).read_text(encoding="utf-8")
    for linea in contenido.splitlines():
        if linea.startswith("VOLCADO "):
            return json.loads(linea[len("VOLCADO ") :])
    raise AssertionError(f"El watcher falso no dejó volcado. Log:\n{contenido}")


def _comando(runner, app_name: str, etiqueta: str) -> str:
    definicion = runner.app_de(app_name)
    for comando in definicion.commands:
        if comando.label == etiqueta:
            return comando.key
    raise AssertionError(f"No existe el comando {etiqueta}")


# ---------------------------------------------------------------------------
# Ejecución básica
# ---------------------------------------------------------------------------


def test_una_ejecucion_correcta_queda_registrada(runner, sesion):
    usuario = _usuario_listo(sesion)
    clave = _comando(runner, "stockwatcher", "Ejecutar")

    run = runner.lanzar(sesion, usuario, "stockwatcher", clave)
    assert run.status == JOB_RUNNING
    _esperar(runner, usuario.id)

    sesion.refresh(run)
    assert run.status == JOB_SUCCESS
    assert run.return_code == 0
    assert run.duration_seconds is not None


def test_un_fallo_del_watcher_se_marca_como_error(runner, sesion):
    usuario = _usuario_listo(sesion)
    run = runner.lanzar(
        sesion, usuario, "stockwatcher", _comando(runner, "stockwatcher", "Fallar")
    )
    _esperar(runner, usuario.id)
    sesion.refresh(run)
    assert run.status == JOB_ERROR
    assert run.return_code == 3


def test_el_log_vive_bajo_la_carpeta_del_usuario(runner, sesion, settings):
    usuario = _usuario_listo(sesion)
    run = runner.lanzar(
        sesion, usuario, "stockwatcher", _comando(runner, "stockwatcher", "Ejecutar")
    )
    _esperar(runner, usuario.id)
    assert Path(run.log_path).is_relative_to(settings.logs_dir / usuario.id)


def test_el_watcher_recibe_la_config_generada(runner, sesion):
    usuario = _usuario_listo(sesion)
    run = runner.lanzar(
        sesion, usuario, "stockwatcher", _comando(runner, "stockwatcher", "Ejecutar")
    )
    _esperar(runner, usuario.id)

    volcado = _volcado(runner, run)
    assert "--watches" in volcado["argv"]
    ruta = volcado["argv"][volcado["argv"].index("--watches") + 1]
    assert usuario.id in ruta
    assert Path(ruta).is_file()


def test_los_flags_globales_preceden_al_subcomando(runner, sesion):
    usuario = _usuario_listo(sesion)
    run = runner.lanzar(
        sesion, usuario, "stockwatcher", _comando(runner, "stockwatcher", "Ejecutar")
    )
    _esperar(runner, usuario.id)
    argv = _volcado(runner, run)["argv"]
    assert argv.index("--watches") < argv.index("run")


def test_el_cwd_es_el_repo_administrado(runner, sesion):
    """Así el `.env` del repo sigue aportando los secretos compartidos."""
    usuario = _usuario_listo(sesion)
    run = runner.lanzar(
        sesion, usuario, "stockwatcher", _comando(runner, "stockwatcher", "Ejecutar")
    )
    _esperar(runner, usuario.id)
    esperado = runner.app_de("stockwatcher").base_path
    assert Path(_volcado(runner, run)["cwd"]).resolve() == esperado.resolve()


# ---------------------------------------------------------------------------
# Aislamiento de notificaciones
# ---------------------------------------------------------------------------


def test_cada_usuario_recibe_su_propio_destino(runner, sesion):
    ana = _usuario_listo(sesion, "ana@example.com", "+573001112233")
    bruno = _usuario_listo(sesion, "bruno@example.com", "+573009998877")
    clave = _comando(runner, "stockwatcher", "Ejecutar")

    run_ana = runner.lanzar(sesion, ana, "stockwatcher", clave)
    _esperar(runner, ana.id)
    run_bruno = runner.lanzar(sesion, bruno, "stockwatcher", clave)
    _esperar(runner, bruno.id)

    assert _volcado(runner, run_ana)["env"]["WHATSAPP_TO"] == "+573001112233"
    assert _volcado(runner, run_bruno)["env"]["WHATSAPP_TO"] == "+573009998877"


def test_el_entorno_del_servidor_no_se_cuela(runner, sesion, monkeypatch):
    """Aunque el proceso del panel tenga `WHATSAPP_TO`, gana el del usuario."""
    monkeypatch.setenv("WHATSAPP_TO", "+570000000000")
    usuario = _usuario_listo(sesion)
    run = runner.lanzar(
        sesion, usuario, "stockwatcher", _comando(runner, "stockwatcher", "Ejecutar")
    )
    _esperar(runner, usuario.id)
    assert _volcado(runner, run)["env"]["WHATSAPP_TO"] == "+573001112233"


def test_el_estado_es_distinto_por_usuario(runner, sesion):
    ana = _usuario_listo(sesion, "ana@example.com")
    bruno = _usuario_listo(sesion, "bruno@example.com")
    clave = _comando(runner, "stockwatcher", "Ejecutar")

    run_ana = runner.lanzar(sesion, ana, "stockwatcher", clave)
    _esperar(runner, ana.id)
    run_bruno = runner.lanzar(sesion, bruno, "stockwatcher", clave)
    _esperar(runner, bruno.id)

    estado_ana = _volcado(runner, run_ana)["env"]["STOCKWATCHER_STATE_PATH"]
    estado_bruno = _volcado(runner, run_bruno)["env"]["STOCKWATCHER_STATE_PATH"]
    assert estado_ana != estado_bruno


# ---------------------------------------------------------------------------
# Exclusión y límites
# ---------------------------------------------------------------------------


def test_no_se_solapan_dos_corridas_del_mismo_usuario(runner, sesion):
    usuario = _usuario_listo(sesion)
    runner.lanzar(
        sesion, usuario, "stockwatcher", _comando(runner, "stockwatcher", "Colgarse")
    )
    try:
        with pytest.raises(YaEstaCorriendo):
            runner.lanzar(
                sesion,
                usuario,
                "stockwatcher",
                _comando(runner, "stockwatcher", "Ejecutar"),
            )
    finally:
        runner.cancelar(usuario.id, "stockwatcher")
        _esperar(runner, usuario.id)


def test_dos_usuarios_si_corren_a_la_vez(runner, sesion):
    """El lock es por (usuario, app): Ana no debe bloquear a Bruno."""
    ana = _usuario_listo(sesion, "ana@example.com")
    bruno = _usuario_listo(sesion, "bruno@example.com")
    colgarse = _comando(runner, "stockwatcher", "Colgarse")

    runner.lanzar(sesion, ana, "stockwatcher", colgarse)
    try:
        runner.lanzar(sesion, bruno, "stockwatcher", colgarse)
        assert runner.esta_corriendo(ana.id, "stockwatcher")
        assert runner.esta_corriendo(bruno.id, "stockwatcher")
    finally:
        runner.cancelar(ana.id, "stockwatcher")
        runner.cancelar(bruno.id, "stockwatcher")
        _esperar(runner, ana.id)
        _esperar(runner, bruno.id)


def test_se_respeta_el_tope_global(runner, sesion):
    runner.settings = replace(runner.settings, max_concurrent_jobs=1)
    ana = _usuario_listo(sesion, "ana@example.com")
    bruno = _usuario_listo(sesion, "bruno@example.com")
    colgarse = _comando(runner, "stockwatcher", "Colgarse")

    runner.lanzar(sesion, ana, "stockwatcher", colgarse)
    try:
        with pytest.raises(DemasiadosJobs):
            runner.lanzar(sesion, bruno, "stockwatcher", colgarse)
    finally:
        runner.cancelar(ana.id, "stockwatcher")
        _esperar(runner, ana.id)


def test_no_se_lanza_si_falta_configuracion(runner, sesion):
    vacio = User(
        email="vacio@example.com",
        password_hash=hash_password("Contrasena123"),
        role="user",
        status="active",
    )
    sesion.add(vacio)
    sesion.commit()

    with pytest.raises(NoEstaListo):
        runner.lanzar(
            sesion, vacio, "stockwatcher", _comando(runner, "stockwatcher", "Ejecutar")
        )


def test_un_hueco_ocupado_se_libera_si_falla_el_arranque(runner, sesion):
    """Un error al preparar no debe dejar al usuario bloqueado para siempre."""
    vacio = User(
        email="vacio@example.com",
        password_hash=hash_password("Contrasena123"),
        role="user",
        status="active",
    )
    sesion.add(vacio)
    sesion.commit()

    with pytest.raises(NoEstaListo):
        runner.lanzar(
            sesion, vacio, "stockwatcher", _comando(runner, "stockwatcher", "Ejecutar")
        )
    assert runner.esta_corriendo(vacio.id, "stockwatcher") is False
    assert runner.jobs_activos() == 0


# ---------------------------------------------------------------------------
# Cancelación y reconciliación
# ---------------------------------------------------------------------------


def test_cancelar_detiene_el_proceso(runner, sesion):
    usuario = _usuario_listo(sesion)
    run = runner.lanzar(
        sesion, usuario, "stockwatcher", _comando(runner, "stockwatcher", "Colgarse")
    )
    assert runner.cancelar(usuario.id, "stockwatcher") is True
    _esperar(runner, usuario.id)

    sesion.refresh(run)
    assert run.status == JOB_CANCELLED
    assert run.finished_at is not None


def test_cancelar_sin_nada_corriendo_devuelve_falso(runner, sesion):
    usuario = _usuario_listo(sesion)
    assert runner.cancelar(usuario.id, "stockwatcher") is False


def test_cancelar_no_afecta_a_otro_usuario(runner, sesion):
    ana = _usuario_listo(sesion, "ana@example.com")
    bruno = _usuario_listo(sesion, "bruno@example.com")
    colgarse = _comando(runner, "stockwatcher", "Colgarse")
    runner.lanzar(sesion, ana, "stockwatcher", colgarse)
    runner.lanzar(sesion, bruno, "stockwatcher", colgarse)
    try:
        runner.cancelar(ana.id, "stockwatcher")
        _esperar(runner, ana.id)
        assert runner.esta_corriendo(bruno.id, "stockwatcher") is True
    finally:
        runner.cancelar(bruno.id, "stockwatcher")
        _esperar(runner, bruno.id)


def test_las_corridas_colgadas_se_cierran_al_reiniciar(runner, sesion):
    usuario = _usuario_listo(sesion)
    huerfana = JobRun(
        user_id=usuario.id,
        app_name="stockwatcher",
        command_key="cmd-run",
        command_label="Ejecutar",
        args_json="[]",
        log_path="",
        status=JOB_RUNNING,
    )
    sesion.add(huerfana)
    sesion.commit()

    assert runner.reconciliar_huerfanos() >= 1
    sesion.refresh(huerfana)
    assert huerfana.status == JOB_ERROR
    assert "reinici" in (huerfana.skip_reason or "")


# ---------------------------------------------------------------------------
# dry-run
# ---------------------------------------------------------------------------


def test_dry_run_de_stockwatcher_va_tras_el_subcomando(runner, sesion):
    """En StockWatcher `--dry-run` es opción de `run`."""
    usuario = _usuario_listo(sesion)
    run = runner.lanzar(
        sesion,
        usuario,
        "stockwatcher",
        _comando(runner, "stockwatcher", "Ejecutar"),
        dry_run=True,
    )
    _esperar(runner, usuario.id)
    argv = _volcado(runner, run)["argv"]
    assert argv.index("run") < argv.index("--dry-run")


def test_dry_run_de_portfoliowatcher_va_antes_del_subcomando(runner, sesion):
    """En PortfolioWatcher `--dry-run` es un flag global."""
    usuario = _usuario_listo(sesion)
    from homelab_dashboard.models import PortfolioHolding

    sesion.add(
        PortfolioHolding(
            user_id=usuario.id, ticker="AAPL", quantity=1.0, avg_cost=100.0
        )
    )
    sesion.add(
        AppChannelPref(
            user_id=usuario.id,
            app_name="portfoliowatcher",
            channel=CHANNEL_WHATSAPP,
            enabled=True,
        )
    )
    sesion.commit()

    run = runner.lanzar(
        sesion,
        usuario,
        "portfoliowatcher",
        _comando(runner, "portfoliowatcher", "Ejecutar"),
        dry_run=True,
    )
    _esperar(runner, usuario.id, "portfoliowatcher")
    argv = _volcado(runner, run)["argv"]
    assert argv.index("--dry-run") < argv.index("run")


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


@pytest.fixture()
def cliente_listo(app_watchers):
    """Un usuario activo, con su configuración, autenticado por HTTP."""
    from conftest import PASSWORD_DE_PRUEBA, ClienteAutenticado, entrar, registrar

    cliente = TestClient(app_watchers)
    registrar(cliente, "admin@example.com")  # el primero nace admin activo
    entrar(cliente, "admin@example.com", PASSWORD_DE_PRUEBA)
    envuelto = ClienteAutenticado(cliente)
    envuelto.put("/api/v1/me/notifications", json={"whatsapp": "+573001112233"})
    envuelto.post(
        "/api/v1/me/stockwatcher/watches",
        json={
            "name": "Zapatillas",
            "match_terms": ["air max"],
            "countries": ["CO"],
            "notify_channels": ["whatsapp"],
        },
    )
    yield envuelto
    cliente.close()


def test_la_api_lista_las_apps_con_su_estado(cliente_listo):
    datos = cliente_listo.get("/api/v1/me/apps").json()
    nombres = {a["app_name"] for a in datos["items"]}
    assert nombres == {"stockwatcher", "portfoliowatcher"}
    stock = next(a for a in datos["items"] if a["app_name"] == "stockwatcher")
    assert stock["installed"] is True
    assert stock["readiness"]["ready"] is True
    assert stock["commands"]


def test_la_api_lanza_y_registra_la_ejecucion(cliente_listo, app_watchers):
    apps = cliente_listo.get("/api/v1/me/apps").json()["items"]
    stock = next(a for a in apps if a["app_name"] == "stockwatcher")
    clave = stock["commands"][0]["key"]

    r = cliente_listo.post(
        "/api/v1/me/apps/stockwatcher/runs", json={"command_key": clave}
    )
    assert r.status_code == 201, r.text
    run_id = r.json()["id"]

    runner = app_watchers.state.runner
    fin = time.monotonic() + 15
    while time.monotonic() < fin and runner.jobs_activos():
        time.sleep(0.05)

    historial = cliente_listo.get("/api/v1/me/runs").json()["items"]
    assert [h["id"] for h in historial] == [run_id]
    assert historial[0]["status"] == JOB_SUCCESS

    log = cliente_listo.get(f"/api/v1/me/runs/{run_id}/log").json()
    assert "VOLCADO" in log["content"]
    assert log["running"] is False


def test_un_comando_no_declarado_se_rechaza(cliente_listo):
    r = cliente_listo.post(
        "/api/v1/me/apps/stockwatcher/runs", json={"command_key": "rm -rf /"}
    )
    assert r.status_code == 404


def test_no_se_puede_lanzar_una_app_inexistente(cliente_listo):
    r = cliente_listo.post(
        "/api/v1/me/apps/inventada/runs", json={"command_key": "cmd-run"}
    )
    assert r.status_code == 404


def test_lanzar_sin_configuracion_explica_el_motivo(app_watchers):
    from conftest import PASSWORD_DE_PRUEBA, ClienteAutenticado, entrar, registrar

    primero = TestClient(app_watchers)
    registrar(primero, "admin@example.com")

    cliente = TestClient(app_watchers)
    registrar(cliente, "ana@example.com")
    entrar(cliente, "ana@example.com", PASSWORD_DE_PRUEBA)
    ana = ClienteAutenticado(cliente)

    # `pending` todavía no puede ejecutar.
    r = ana.post(
        "/api/v1/me/apps/stockwatcher/runs", json={"command_key": "cmd-run"}
    )
    assert r.status_code == 403
    primero.close()
    cliente.close()


def test_el_historial_de_un_usuario_no_incluye_al_otro(app_watchers, sesion):
    ana = _usuario_listo(sesion, "ana@example.com")
    bruno = _usuario_listo(sesion, "bruno@example.com")
    runner = app_watchers.state.runner
    clave = _comando(runner, "stockwatcher", "Ejecutar")

    run_ana = runner.lanzar(sesion, ana, "stockwatcher", clave)
    _esperar(runner, ana.id)
    runner.lanzar(sesion, bruno, "stockwatcher", clave)
    _esperar(runner, bruno.id)

    with app_watchers.state.session_factory() as db:
        from sqlalchemy import select

        de_ana = db.scalars(
            select(JobRun).where(JobRun.user_id == ana.id)
        ).all()
        assert [r.id for r in de_ana] == [run_ana.id]


def test_no_se_puede_ver_el_log_de_otro(app_watchers, sesion):
    from conftest import PASSWORD_DE_PRUEBA, ClienteAutenticado, entrar, registrar

    runner = app_watchers.state.runner
    ana = _usuario_listo(sesion, "ana@example.com")
    run_ana = runner.lanzar(
        sesion, ana, "stockwatcher", _comando(runner, "stockwatcher", "Ejecutar")
    )
    _esperar(runner, ana.id)

    cliente = TestClient(app_watchers)
    registrar(cliente, "bruno@example.com")
    entrar(cliente, "bruno@example.com", PASSWORD_DE_PRUEBA)
    bruno = ClienteAutenticado(cliente)

    assert bruno.get(f"/api/v1/me/runs/{run_ana.id}").status_code == 404
    assert bruno.get(f"/api/v1/me/runs/{run_ana.id}/log").status_code == 404
    cliente.close()


def test_los_logs_de_un_usuario_no_son_legibles_por_otro(runner, sesion, settings):
    """Permisos de disco, además del control de acceso de la API."""
    usuario = _usuario_listo(sesion)
    runner.lanzar(
        sesion, usuario, "stockwatcher", _comando(runner, "stockwatcher", "Ejecutar")
    )
    _esperar(runner, usuario.id)
    carpeta = settings.logs_dir / usuario.id
    assert oct(os.stat(carpeta).st_mode)[-3:] == "700"
