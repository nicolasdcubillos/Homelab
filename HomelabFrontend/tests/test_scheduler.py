"""Fase 4: scheduler.

No se usa el reloj real en ningún punto: `tick()` toma `utcnow()` de la base,
así que los tests fijan `next_run_at` en el pasado para provocar el disparo, y
el lanzamiento real de procesos se sustituye por un runner falso salvo donde
interesa el camino completo.
"""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import pytest
from conftest import PASSWORD_DE_PRUEBA, crear_usuario
from sqlalchemy import select

from homelab_dashboard.db import utcnow
from homelab_dashboard.models import (
    JOB_SKIPPED,
    SCHEDULE_CRON,
    SCHEDULE_INTERVAL,
    TRIGGER_SCHEDULE,
    USER_ACTIVE,
    USER_PENDING,
    USER_SUSPENDED,
    JobRun,
    Schedule,
)
from homelab_dashboard.scheduler import (
    ErrorDeProgramacion,
    Scheduler,
    calcular_siguiente,
    validar_cron,
    validar_programacion,
    zona_de,
)

# ---------------------------------------------------------------------------
# Cálculo del siguiente disparo
# ---------------------------------------------------------------------------


def _schedule(**kw) -> Schedule:
    base = dict(
        user_id="u",
        app_name="stockwatcher",
        command_key="run",
        enabled=True,
        kind=SCHEDULE_INTERVAL,
        interval_minutes=60,
    )
    base.update(kw)
    return Schedule(**base)


UTC = dt.timezone.utc
BOGOTA = ZoneInfo("America/Bogota")


def test_intervalo_suma_los_minutos():
    ahora = dt.datetime(2025, 1, 1, 12, 0, tzinfo=UTC)
    siguiente = calcular_siguiente(_schedule(interval_minutes=90), UTC, desde=ahora)
    assert siguiente == dt.datetime(2025, 1, 1, 13, 30, tzinfo=UTC)


def test_deshabilitada_no_tiene_siguiente():
    assert calcular_siguiente(_schedule(enabled=False), UTC) is None


def test_cron_respeta_la_zona_del_usuario():
    """Las 8:00 de Bogotá son las 13:00 UTC; si no, el usuario recibiría el
    informe a media madrugada."""
    ahora = dt.datetime(2025, 1, 1, 6, 0, tzinfo=UTC)
    siguiente = calcular_siguiente(
        _schedule(kind=SCHEDULE_CRON, cron_expr="0 8 * * *", interval_minutes=None),
        BOGOTA,
        desde=ahora,
    )
    assert siguiente.astimezone(UTC) == dt.datetime(2025, 1, 1, 13, 0, tzinfo=UTC)


def test_cron_avanza_al_dia_siguiente_si_ya_paso():
    ahora = dt.datetime(2025, 1, 1, 20, 0, tzinfo=UTC)
    siguiente = calcular_siguiente(
        _schedule(kind=SCHEDULE_CRON, cron_expr="0 8 * * *", interval_minutes=None),
        BOGOTA,
        desde=ahora,
    )
    assert siguiente.astimezone(UTC) == dt.datetime(2025, 1, 2, 13, 0, tzinfo=UTC)


def test_cron_sin_expresion_no_revienta():
    assert (
        calcular_siguiente(
            _schedule(kind=SCHEDULE_CRON, cron_expr=None, interval_minutes=None), UTC
        )
        is None
    )


def test_el_resultado_siempre_es_utc():
    siguiente = calcular_siguiente(
        _schedule(kind=SCHEDULE_CRON, cron_expr="*/10 * * * *", interval_minutes=None),
        BOGOTA,
    )
    assert siguiente.utcoffset() == dt.timedelta(0)


# ---------------------------------------------------------------------------
# Validación
# ---------------------------------------------------------------------------


def test_cron_valido():
    assert validar_cron("0 8 * * *") is not None


@pytest.mark.parametrize(
    "expr", ["", "no es cron", "0 8 * *", "99 8 * * *", "* * * * * *"]
)
def test_cron_invalido(expr):
    with pytest.raises(ErrorDeProgramacion):
        validar_programacion(SCHEDULE_CRON, None, expr)


def test_intervalo_por_debajo_del_minimo():
    with pytest.raises(ErrorDeProgramacion):
        validar_programacion(SCHEDULE_INTERVAL, 1, None)


def test_intervalo_por_encima_del_maximo():
    with pytest.raises(ErrorDeProgramacion):
        validar_programacion(SCHEDULE_INTERVAL, 60 * 24 * 40, None)


def test_intervalo_ausente():
    with pytest.raises(ErrorDeProgramacion):
        validar_programacion(SCHEDULE_INTERVAL, None, None)


def test_tipo_desconocido():
    with pytest.raises(ErrorDeProgramacion):
        validar_programacion("cuando_sea", 60, None)


def test_intervalo_valido_en_el_limite():
    validar_programacion(SCHEDULE_INTERVAL, 5, None)


def test_zona_invalida_cae_a_la_del_servidor(settings, db):
    usuario = crear_usuario(db, "raro@example.com", timezone="Marte/Olympus")
    assert zona_de(usuario, settings) == ZoneInfo(settings.default_timezone)


def test_zona_valida_se_respeta(settings, db):
    usuario = crear_usuario(db, "tz@example.com", timezone="Europe/Madrid")
    assert zona_de(usuario, settings) == ZoneInfo("Europe/Madrid")


# ---------------------------------------------------------------------------
# Tick
# ---------------------------------------------------------------------------


class RunnerFalso:
    """Sustituye al JobRunner: registra qué se le pidió, sin lanzar procesos."""

    def __init__(self, *, corriendo: set | None = None, falla: Exception | None = None):
        self.lanzados: list[tuple[str, str, str]] = []
        self.omitidas: list[tuple[str, str, str]] = []
        self.corriendo = corriendo or set()
        self.falla = falla

    def esta_corriendo(self, user_id, app_name):
        return (user_id, app_name) in self.corriendo

    def lanzar(self, db, usuario, app_name, command_key, **kw):
        if self.falla is not None:
            raise self.falla
        self.lanzados.append((usuario.id, app_name, command_key))
        return JobRun(
            user_id=usuario.id,
            app_name=app_name,
            command_key=command_key,
            command_label=command_key,
            status="running",
            trigger=kw.get("trigger", "manual"),
            started_at=utcnow(),
        )

    def registrar_omitida(self, db, usuario, app_name, command_key, motivo, **kw):
        self.omitidas.append((usuario.id, app_name, motivo))


@pytest.fixture()
def factory(settings):
    from homelab_dashboard.db import create_db_engine, make_session_factory
    from homelab_dashboard.migrate import upgrade_to_head

    upgrade_to_head(settings)
    return make_session_factory(create_db_engine(settings.db_path))


@pytest.fixture()
def app(app_watchers):
    """Los tests de este módulo necesitan un registro que conozca de verdad a
    `stockwatcher`, para poder validar sus comandos."""
    return app_watchers


def _sched(settings, factory, runner):
    return Scheduler(settings, factory, runner)


def _usuario_listo(db, email="listo@example.com", **kw):
    """Usuario que pasa el pre-vuelo de StockWatcher."""
    from homelab_dashboard.models import (
        CHANNEL_WHATSAPP,
        AppChannelPref,
        NotificationChannel,
        StockWatch,
    )

    usuario = crear_usuario(db, email, status=USER_ACTIVE, **kw)
    db.add(
        NotificationChannel(
            user_id=usuario.id, channel=CHANNEL_WHATSAPP, destination="+573001112233"
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
    db.add(
        StockWatch(
            user_id=usuario.id,
            name="Zapatos",
            match_terms=["zapato"],
            notify_channels=[CHANNEL_WHATSAPP],
        )
    )
    db.commit()
    return usuario


def _programar(db, user_id, *, vencida=True, **kw):
    campos = dict(
        user_id=user_id,
        app_name="stockwatcher",
        command_key="run",
        enabled=True,
        kind=SCHEDULE_INTERVAL,
        interval_minutes=60,
        next_run_at=utcnow() - dt.timedelta(minutes=1)
        if vencida
        else utcnow() + dt.timedelta(hours=5),
    )
    campos.update(kw)
    schedule = Schedule(**campos)
    db.add(schedule)
    db.commit()
    return schedule


def test_dispara_lo_vencido(settings, factory):
    with factory() as db:
        usuario = _usuario_listo(db)
        _programar(db, usuario.id)
    runner = RunnerFalso()
    assert _sched(settings, factory, runner).tick() == 1
    assert runner.lanzados == [(usuario.id, "stockwatcher", "run")]


def test_no_dispara_lo_que_no_ha_vencido(settings, factory):
    with factory() as db:
        usuario = _usuario_listo(db)
        _programar(db, usuario.id, vencida=False)
    runner = RunnerFalso()
    assert _sched(settings, factory, runner).tick() == 0
    assert runner.lanzados == []


def test_no_dispara_las_deshabilitadas(settings, factory):
    with factory() as db:
        usuario = _usuario_listo(db)
        _programar(db, usuario.id, enabled=False)
    runner = RunnerFalso()
    assert _sched(settings, factory, runner).tick() == 0


def test_avanza_next_run_at_tras_disparar(settings, factory):
    with factory() as db:
        usuario = _usuario_listo(db)
        _programar(db, usuario.id, interval_minutes=60)
    _sched(settings, factory, RunnerFalso()).tick()
    with factory() as db:
        schedule = db.scalars(select(Schedule)).one()
        assert schedule.next_run_at > utcnow()
        assert schedule.last_run_at is not None


def test_un_segundo_tick_no_repite(settings, factory):
    """El avance de `next_run_at` es lo que impide la ejecución doble."""
    with factory() as db:
        usuario = _usuario_listo(db)
        _programar(db, usuario.id)
    runner = RunnerFalso()
    sched = _sched(settings, factory, runner)
    sched.tick()
    sched.tick()
    assert len(runner.lanzados) == 1


def test_claim_atomico_rechaza_al_segundo(settings, factory):
    """Si otro proceso ya movió `next_run_at`, el UPDATE condicionado falla.

    Se simula con dos sesiones distintas: una hace de worker rezagado, que aún
    tiene en memoria el `next_run_at` viejo, y la otra de worker adelantado.
    """
    with factory() as db:
        usuario = _usuario_listo(db)
        sid = _programar(db, usuario.id).id

    runner = RunnerFalso()
    sched = _sched(settings, factory, runner)

    with factory() as rezagado, factory() as adelantado:
        fila_vieja = rezagado.get(Schedule, sid)
        otra = adelantado.get(Schedule, sid)
        otra.next_run_at = utcnow() + dt.timedelta(hours=1)
        adelantado.commit()

        assert sched._reclamar(rezagado, fila_vieja, utcnow()) is False
    assert runner.lanzados == []


def test_app_desconocida_se_omite(settings, factory):
    """Una programación de una app que ya no existe no puede tumbar el tick."""
    with factory() as db:
        usuario = _usuario_listo(db, email="fantasma@example.com")
        _programar(db, usuario.id, app_name="app-que-ya-no-existe")
    runner = RunnerFalso()
    assert _sched(settings, factory, runner).tick() == 0
    assert runner.omitidas and runner.omitidas[0][2]


@pytest.mark.parametrize("estado", [USER_PENDING, USER_SUSPENDED])
def test_cuenta_no_activa_se_omite(settings, factory, estado):
    with factory() as db:
        usuario = _usuario_listo(db, email=f"{estado}@example.com")
        usuario.status = estado
        db.commit()
        _programar(db, usuario.id)
    runner = RunnerFalso()
    assert _sched(settings, factory, runner).tick() == 0
    assert len(runner.omitidas) == 1
    assert "activa" in runner.omitidas[0][2]


def test_sin_configuracion_se_omite_con_motivo(settings, factory):
    """Sin watches el watcher abortaría con ConfigError; mejor no lanzarlo."""
    with factory() as db:
        usuario = crear_usuario(db, "vacio@example.com", status=USER_ACTIVE)
        _programar(db, usuario.id)
    runner = RunnerFalso()
    assert _sched(settings, factory, runner).tick() == 0
    assert runner.omitidas and runner.omitidas[0][2]


def test_omitida_queda_en_el_historial(settings, factory):
    """Con el runner real, la omisión debe verse en el historial del usuario."""
    from homelab_dashboard.runner import JobRunner

    with factory() as db:
        usuario = crear_usuario(db, "hist@example.com", status=USER_ACTIVE)
        _programar(db, usuario.id)
    runner = JobRunner(settings, factory)
    _sched(settings, factory, runner).tick()
    with factory() as db:
        run = db.scalars(select(JobRun)).one()
        assert run.status == JOB_SKIPPED
        assert run.trigger == TRIGGER_SCHEDULE
        assert run.user_id == usuario.id
        assert run.skip_reason


def test_no_solapa_si_ya_esta_corriendo(settings, factory):
    with factory() as db:
        usuario = _usuario_listo(db)
        _programar(db, usuario.id)
    runner = RunnerFalso(corriendo={(usuario.id, "stockwatcher")})
    assert _sched(settings, factory, runner).tick() == 0
    assert "anterior" in runner.omitidas[0][2]


def test_un_usuario_no_bloquea_a_otro(settings, factory):
    """El lock es por (usuario, app): que Ana corra no frena a Bruno."""
    with factory() as db:
        ana = _usuario_listo(db, email="ana@example.com")
        bruno = _usuario_listo(db, email="bruno@example.com")
        _programar(db, ana.id)
        _programar(db, bruno.id)
    runner = RunnerFalso(corriendo={(ana.id, "stockwatcher")})
    assert _sched(settings, factory, runner).tick() == 1
    assert runner.lanzados == [(bruno.id, "stockwatcher", "run")]


def test_el_fallo_de_un_usuario_no_tumba_el_tick(settings, factory):
    """Aislamiento de fallos: el resto del lote debe seguir."""
    with factory() as db:
        ana = _usuario_listo(db, email="ana2@example.com")
        bruno = _usuario_listo(db, email="bruno2@example.com")
        _programar(db, ana.id)
        _programar(db, bruno.id)

    runner = RunnerFalso()
    lanzar_original = runner.lanzar
    fallados: list[str] = []

    def lanzar_con_bomba(db, usuario, app_name, command_key, **kw):
        if usuario.id == ana.id:
            fallados.append(usuario.id)
            raise RuntimeError("boom")
        return lanzar_original(db, usuario, app_name, command_key, **kw)

    runner.lanzar = lanzar_con_bomba
    assert _sched(settings, factory, runner).tick() == 1
    assert fallados == [ana.id]
    assert runner.lanzados == [(bruno.id, "stockwatcher", "run")]


def test_error_de_ejecucion_se_registra_como_omitida(settings, factory):
    from homelab_dashboard.runner import DemasiadosJobs

    with factory() as db:
        usuario = _usuario_listo(db)
        _programar(db, usuario.id)
    runner = RunnerFalso(falla=DemasiadosJobs("El panel está saturado."))
    assert _sched(settings, factory, runner).tick() == 0
    assert "saturado" in runner.omitidas[0][2]





def test_cron_vencido_dispara_y_recalcula(settings, factory):
    with factory() as db:
        usuario = _usuario_listo(db)
        _programar(
            db,
            usuario.id,
            kind=SCHEDULE_CRON,
            cron_expr="0 8 * * *",
            interval_minutes=None,
        )
    runner = RunnerFalso()
    assert _sched(settings, factory, runner).tick() == 1
    with factory() as db:
        schedule = db.scalars(select(Schedule)).one()
        assert schedule.next_run_at.astimezone(BOGOTA).hour == 8


def test_start_y_shutdown_son_idempotentes(settings, factory):
    sched = _sched(settings, factory, RunnerFalso())
    sched.start()
    sched.start()
    sched.shutdown()
    sched.shutdown()


# ---------------------------------------------------------------------------
# API de automatización
# ---------------------------------------------------------------------------


def test_lista_vacia_al_principio(usuario_cliente):
    r = usuario_cliente.get("/api/v1/me/schedules")
    assert r.status_code == 200
    assert r.json()["items"] == []
    assert r.json()["timezone"]


def test_crear_programacion_por_intervalo(usuario_cliente):
    r = usuario_cliente.put(
        "/api/v1/me/schedules/stockwatcher/cmd-run",
        json={"enabled": True, "kind": "interval", "interval_minutes": 60},
    )
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["interval_minutes"] == 60
    assert cuerpo["next_run_at"] is not None
    assert cuerpo["command_label"]


def test_crear_programacion_por_cron(usuario_cliente):
    r = usuario_cliente.put(
        "/api/v1/me/schedules/stockwatcher/cmd-run",
        json={"enabled": True, "kind": "cron", "cron_expr": "0 8 * * *"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["cron_expr"] == "0 8 * * *"
    assert r.json()["next_run_at"] is not None


def test_cron_invalido_da_422(usuario_cliente):
    r = usuario_cliente.put(
        "/api/v1/me/schedules/stockwatcher/cmd-run",
        json={"enabled": True, "kind": "cron", "cron_expr": "esto no es cron"},
    )
    assert r.status_code == 422
    assert "cron_expr" in r.json()["error"]["fields"]


def test_intervalo_demasiado_corto_da_422(usuario_cliente):
    r = usuario_cliente.put(
        "/api/v1/me/schedules/stockwatcher/cmd-run",
        json={"enabled": True, "kind": "interval", "interval_minutes": 1},
    )
    assert r.status_code == 422


def test_deshabilitar_borra_la_proxima(usuario_cliente):
    usuario_cliente.put(
        "/api/v1/me/schedules/stockwatcher/cmd-run",
        json={"enabled": True, "kind": "interval", "interval_minutes": 60},
    )
    r = usuario_cliente.put(
        "/api/v1/me/schedules/stockwatcher/cmd-run",
        json={"enabled": False, "kind": "interval", "interval_minutes": 60},
    )
    assert r.json()["next_run_at"] is None


def test_actualizar_no_duplica(usuario_cliente):
    for minutos in (60, 120):
        usuario_cliente.put(
            "/api/v1/me/schedules/stockwatcher/cmd-run",
            json={"enabled": True, "kind": "interval", "interval_minutes": minutos},
        )
    items = usuario_cliente.get("/api/v1/me/schedules").json()["items"]
    assert len(items) == 1
    assert items[0]["interval_minutes"] == 120


def test_cambiar_a_cron_limpia_el_intervalo(usuario_cliente):
    usuario_cliente.put(
        "/api/v1/me/schedules/stockwatcher/cmd-run",
        json={"enabled": True, "kind": "interval", "interval_minutes": 60},
    )
    r = usuario_cliente.put(
        "/api/v1/me/schedules/stockwatcher/cmd-run",
        json={"enabled": True, "kind": "cron", "cron_expr": "0 8 * * *"},
    )
    assert r.json()["interval_minutes"] is None


def test_app_desconocida_da_404(usuario_cliente):
    r = usuario_cliente.put(
        "/api/v1/me/schedules/inventada/run",
        json={"enabled": True, "kind": "interval", "interval_minutes": 60},
    )
    assert r.status_code == 404


def test_comando_desconocido_da_422(usuario_cliente):
    r = usuario_cliente.put(
        "/api/v1/me/schedules/stockwatcher/rm-rf",
        json={"enabled": True, "kind": "interval", "interval_minutes": 60},
    )
    assert r.status_code == 422


def test_borrar_programacion(usuario_cliente):
    usuario_cliente.put(
        "/api/v1/me/schedules/stockwatcher/cmd-run",
        json={"enabled": True, "kind": "interval", "interval_minutes": 60},
    )
    assert (
        usuario_cliente.delete("/api/v1/me/schedules/stockwatcher/cmd-run").status_code
        == 204
    )
    assert usuario_cliente.get("/api/v1/me/schedules").json()["items"] == []


def test_borrar_inexistente_da_404(usuario_cliente):
    assert (
        usuario_cliente.delete("/api/v1/me/schedules/stockwatcher/cmd-run").status_code
        == 404
    )


def test_cambiar_zona_recalcula_el_cron(usuario_cliente):
    usuario_cliente.put(
        "/api/v1/me/schedules/stockwatcher/cmd-run",
        json={"enabled": True, "kind": "cron", "cron_expr": "0 8 * * *"},
    )
    antes = usuario_cliente.get("/api/v1/me/schedules").json()["items"][0][
        "next_run_at"
    ]
    r = usuario_cliente.put(
        "/api/v1/me/timezone", json={"timezone": "Asia/Tokyo"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["timezone"] == "Asia/Tokyo"
    assert r.json()["items"][0]["next_run_at"] != antes


def test_zona_invalida_da_422(usuario_cliente):
    r = usuario_cliente.put("/api/v1/me/timezone", json={"timezone": "Marte/Olympus"})
    assert r.status_code == 422


def test_la_proxima_aparece_en_la_tarjeta_de_la_app(usuario_cliente):
    usuario_cliente.put(
        "/api/v1/me/schedules/stockwatcher/cmd-run",
        json={"enabled": True, "kind": "interval", "interval_minutes": 60},
    )
    apps = usuario_cliente.get("/api/v1/me/apps").json()["items"]
    stock = next(a for a in apps if a["app_name"] == "stockwatcher")
    assert stock["next_run_at"] is not None


def test_borrar_mis_datos_borra_las_programaciones(usuario_cliente):
    usuario_cliente.put(
        "/api/v1/me/schedules/stockwatcher/cmd-run",
        json={"enabled": True, "kind": "interval", "interval_minutes": 60},
    )
    r = usuario_cliente.request(
        "DELETE", "/api/v1/me/data", json={"password": PASSWORD_DE_PRUEBA}
    )
    assert r.status_code == 204, r.text
    assert usuario_cliente.get("/api/v1/me/schedules").json()["items"] == []


# -- aislamiento ------------------------------------------------------------


def test_no_veo_las_programaciones_de_otro(nuevo_usuario):
    ana = nuevo_usuario("ana@example.com")
    bruno = nuevo_usuario("bruno@example.com")
    ana.put(
        "/api/v1/me/schedules/stockwatcher/cmd-run",
        json={"enabled": True, "kind": "interval", "interval_minutes": 60},
    )
    assert bruno.get("/api/v1/me/schedules").json()["items"] == []


def test_no_puedo_borrar_la_programacion_de_otro(nuevo_usuario):
    ana = nuevo_usuario("ana3@example.com")
    bruno = nuevo_usuario("bruno3@example.com")
    ana.put(
        "/api/v1/me/schedules/stockwatcher/cmd-run",
        json={"enabled": True, "kind": "interval", "interval_minutes": 60},
    )
    assert bruno.delete("/api/v1/me/schedules/stockwatcher/cmd-run").status_code == 404
    assert len(ana.get("/api/v1/me/schedules").json()["items"]) == 1


def test_anonimo_no_puede_programar(client):
    r = client.put(
        "/api/v1/me/schedules/stockwatcher/cmd-run",
        json={"enabled": True, "kind": "interval", "interval_minutes": 60},
    )
    assert r.status_code == 401
