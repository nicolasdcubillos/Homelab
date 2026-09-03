"""Fixtures compartidas para los tests de homelab_dashboard."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

FAKE_ENTRYPOINT_SCRIPT = """#!/usr/bin/env python3
import sys
import time

def main():
    print("fake-entrypoint called with args:", sys.argv[1:])
    if "--fail" in sys.argv:
        time.sleep(0.05)
        print("simulated failure", file=sys.stderr)
        sys.exit(1)
    if "--slow" in sys.argv:
        time.sleep(1.5)
    print("done")
    sys.exit(0)

if __name__ == "__main__":
    main()
"""


@pytest.fixture()
def fake_app_dir(tmp_path: Path) -> Path:
    """Crea una estructura de app falsa: venv/bin/fakeapp + config/*.yaml."""
    app_dir = tmp_path / "fakeapp"
    (app_dir / "config").mkdir(parents=True)
    (app_dir / "config" / "settings.yaml").write_text("key: value\n", encoding="utf-8")

    venv_bin = app_dir / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    script_path = venv_bin / "fakeapp"
    script_path.write_text(FAKE_ENTRYPOINT_SCRIPT, encoding="utf-8")
    script_path.chmod(script_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    return app_dir


@pytest.fixture()
def apps_yaml_file(tmp_path: Path, fake_app_dir: Path) -> Path:
    content = f"""
apps:
  - name: fakeapp
    display_name: "Fake App"
    path: {fake_app_dir}
    venv_bin: {fake_app_dir}/.venv/bin
    entrypoint: fakeapp
    config_files:
      - label: "Settings"
        path: config/settings.yaml
        type: yaml
    commands:
      - label: "Run OK"
        args: ["--ok"]
      - label: "Run Fail"
        args: ["--fail"]
      - label: "Run Slow"
        args: ["--slow"]
  - name: notinstalled
    display_name: "Not Installed App"
    path: {tmp_path}/does-not-exist
    venv_bin: {tmp_path}/does-not-exist/.venv/bin
    entrypoint: notinstalled
    config_files: []
    commands:
      - label: "Run"
        args: ["run"]
"""
    path = tmp_path / "apps.yaml"
    path.write_text(content, encoding="utf-8")
    return path
