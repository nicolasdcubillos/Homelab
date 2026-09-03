from __future__ import annotations

import time

from fastapi.testclient import TestClient

from homelab_dashboard.app import create_app


def _client(tmp_path, apps_yaml_file):
    app = create_app(
        apps_file=apps_yaml_file,
        db_path=tmp_path / "dashboard.db",
        logs_dir=tmp_path / "logs",
    )
    return TestClient(app)


def test_index_lists_installed_and_not_installed(tmp_path, apps_yaml_file):
    client = _client(tmp_path, apps_yaml_file)
    res = client.get("/")
    assert res.status_code == 200
    assert "Fake App" in res.text
    assert "Not Installed App" in res.text
    assert "no instalado" in res.text


def test_app_detail_not_installed_shows_message(tmp_path, apps_yaml_file):
    client = _client(tmp_path, apps_yaml_file)
    res = client.get("/apps/notinstalled")
    assert res.status_code == 200
    assert "no está instalada" in res.text


def test_app_detail_unknown_app_404(tmp_path, apps_yaml_file):
    client = _client(tmp_path, apps_yaml_file)
    res = client.get("/apps/does-not-exist-in-registry")
    assert res.status_code == 404


def test_run_command_and_history(tmp_path, apps_yaml_file):
    client = _client(tmp_path, apps_yaml_file)
    res = client.get("/apps/fakeapp")
    assert res.status_code == 200
    assert "Run OK" in res.text

    res = client.post("/apps/fakeapp/commands/cmd-ok")
    assert res.status_code == 200
    assert res.json()["ok"] is True

    deadline = time.time() + 5
    while time.time() < deadline:
        status = client.get("/apps/fakeapp/status").json()
        if not status["running"]:
            break
        time.sleep(0.05)
    assert status["running"] is False
    assert status["last_run"]["status"] == "success"

    log = client.get("/apps/fakeapp/log").text
    assert "fake-entrypoint called" in log


def test_run_unknown_command_rejected(tmp_path, apps_yaml_file):
    client = _client(tmp_path, apps_yaml_file)
    res = client.post("/apps/fakeapp/commands/rm-rf-slash")
    assert res.status_code == 400


def test_run_command_on_not_installed_app_rejected(tmp_path, apps_yaml_file):
    client = _client(tmp_path, apps_yaml_file)
    res = client.post("/apps/notinstalled/commands/cmd-run")
    assert res.status_code == 400


def test_concurrent_run_returns_409(tmp_path, apps_yaml_file):
    client = _client(tmp_path, apps_yaml_file)
    res1 = client.post("/apps/fakeapp/commands/cmd-slow")
    assert res1.status_code == 200
    res2 = client.post("/apps/fakeapp/commands/cmd-ok")
    assert res2.status_code == 409

    deadline = time.time() + 5
    while time.time() < deadline:
        if not client.get("/apps/fakeapp/status").json()["running"]:
            break
        time.sleep(0.05)


def test_save_config_valid_yaml(tmp_path, apps_yaml_file):
    client = _client(tmp_path, apps_yaml_file)
    res = client.post(
        "/apps/fakeapp/config",
        data={"rel_path": "config/settings.yaml", "content": "new: true\n"},
        follow_redirects=False,
    )
    assert res.status_code == 303
    assert "saved=" in res.headers["location"]

    res = client.get("/apps/fakeapp")
    assert "new: true" in res.text


def test_save_config_invalid_yaml_redirects_with_error(tmp_path, apps_yaml_file):
    client = _client(tmp_path, apps_yaml_file)
    res = client.post(
        "/apps/fakeapp/config",
        data={"rel_path": "config/settings.yaml", "content": "bad: [unterminated"},
        follow_redirects=False,
    )
    assert res.status_code == 303
    assert "error=" in res.headers["location"]
    # original content must be unchanged
    res = client.get("/apps/fakeapp")
    assert "key: value" in res.text


def test_save_config_unknown_file_rejected(tmp_path, apps_yaml_file):
    client = _client(tmp_path, apps_yaml_file)
    res = client.post(
        "/apps/fakeapp/config",
        data={"rel_path": "config/other.yaml", "content": "a: 1\n"},
    )
    assert res.status_code == 400


def test_save_config_path_traversal_rejected(tmp_path, apps_yaml_file):
    client = _client(tmp_path, apps_yaml_file)
    res = client.post(
        "/apps/fakeapp/config",
        data={"rel_path": "../../../etc/passwd", "content": "a: 1\n"},
    )
    # The registry only knows about the declared relative path, so an
    # arbitrary path is never even looked up against the filesystem - it is
    # rejected as an unrecognized config file.
    assert res.status_code == 400
