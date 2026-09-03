from __future__ import annotations

import time

from homelab_dashboard.jobs import STATUS_ERROR, STATUS_SUCCESS, JobAlreadyRunningError, JobManager
from homelab_dashboard.registry import load_registry


def _get_fake_app(apps_yaml_file):
    apps = load_registry(apps_yaml_file)
    return next(a for a in apps if a.name == "fakeapp")


def _wait_until_finished(jm: JobManager, app_name: str, timeout: float = 30.0) -> None:
    # 30s, no 5s: este test arranca subprocesos reales de Python (uno o dos a
    # la vez) que compiten por CPU con lo que sea que esté corriendo en la
    # máquina. Bajo carga, el arranque del intérprete más el `--slow` (que
    # duerme 1.5s) más el polling de este bucle pueden comerse un margen de
    # 5s sin que el job esté realmente colgado. Subir el timeout NO ralentiza
    # la suite: el bucle retorna en cuanto `is_running` es falso, así que en
    # el camino feliz el tiempo es idéntico; el timeout solo decide cuánto se
    # espera antes de declarar el fallo. Es margen gratis contra runners
    # lentos y compartidos (ver CI en .github/workflows/ci.yml), no latencia
    # añadida.
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not jm.is_running(app_name):
            return
        time.sleep(0.05)
    raise AssertionError("job did not finish in time")


def test_start_job_success_updates_history(tmp_path, apps_yaml_file):
    app = _get_fake_app(apps_yaml_file)
    jm = JobManager(db_path=tmp_path / "dashboard.db", logs_dir=tmp_path / "logs")

    command = next(c for c in app.commands if c.label == "Run OK")
    record = jm.start_job(app, command)
    assert record.status == "running"

    _wait_until_finished(jm, app.name)

    last = jm.last_run(app.name)
    assert last.status == STATUS_SUCCESS
    assert last.return_code == 0
    assert last.duration_seconds is not None

    history = jm.history(app.name)
    assert len(history) == 1

    log_content = jm.tail_log(last.log_path)
    assert "fake-entrypoint called" in log_content
    assert "done" in log_content


def test_start_job_failure_recorded_as_error(tmp_path, apps_yaml_file):
    app = _get_fake_app(apps_yaml_file)
    jm = JobManager(db_path=tmp_path / "dashboard.db", logs_dir=tmp_path / "logs")

    command = next(c for c in app.commands if c.label == "Run Fail")
    jm.start_job(app, command)
    _wait_until_finished(jm, app.name)

    last = jm.last_run(app.name)
    assert last.status == STATUS_ERROR
    assert last.return_code != 0

    log_content = jm.tail_log(last.log_path)
    assert "simulated failure" in log_content


def test_cannot_run_two_jobs_concurrently_for_same_app(tmp_path, apps_yaml_file):
    app = _get_fake_app(apps_yaml_file)
    jm = JobManager(db_path=tmp_path / "dashboard.db", logs_dir=tmp_path / "logs")

    slow_command = next(c for c in app.commands if c.label == "Run Slow")
    jm.start_job(app, slow_command)
    assert jm.is_running(app.name) is True

    ok_command = next(c for c in app.commands if c.label == "Run OK")
    try:
        jm.start_job(app, ok_command)
        raised = False
    except JobAlreadyRunningError:
        raised = True
    assert raised is True

    _wait_until_finished(jm, app.name, timeout=30.0)


def test_different_apps_can_run_in_parallel(tmp_path, apps_yaml_file, fake_app_dir):
    import stat

    apps = load_registry(apps_yaml_file)
    app1 = next(a for a in apps if a.name == "fakeapp")

    # Build a second, independent fake app so we can prove two *different*
    # apps may run jobs at the same time.
    app2_dir = tmp_path / "fakeapp2"
    (app2_dir / "config").mkdir(parents=True)
    venv_bin = app2_dir / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    script = venv_bin / "fakeapp2"
    script.write_text((fake_app_dir / ".venv" / "bin" / "fakeapp").read_text(), encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    from homelab_dashboard.registry import AppDefinition, Command

    app2 = AppDefinition(
        name="fakeapp2",
        display_name="Fake App 2",
        path=str(app2_dir),
        venv_bin=str(venv_bin),
        entrypoint="fakeapp2",
        config_files=[],
        commands=[Command(label="Run Slow", args=["--slow"])],
    )

    jm = JobManager(db_path=tmp_path / "dashboard.db", logs_dir=tmp_path / "logs")
    slow1 = next(c for c in app1.commands if c.label == "Run Slow")
    slow2 = app2.commands[0]

    jm.start_job(app1, slow1)
    jm.start_job(app2, slow2)

    assert jm.is_running(app1.name) is True
    assert jm.is_running(app2.name) is True

    _wait_until_finished(jm, app1.name)
    _wait_until_finished(jm, app2.name)
