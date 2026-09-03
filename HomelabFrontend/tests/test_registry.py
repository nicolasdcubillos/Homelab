from __future__ import annotations

import pytest

from homelab_dashboard.registry import RegistryError, load_registry


def test_load_registry_parses_apps(apps_yaml_file):
    apps = load_registry(apps_yaml_file)
    assert len(apps) == 2
    fake = next(a for a in apps if a.name == "fakeapp")
    assert fake.display_name == "Fake App"
    assert fake.is_installed is True
    assert len(fake.config_files) == 1
    assert fake.config_files[0].path == "config/settings.yaml"
    assert len(fake.commands) == 3

    not_installed = next(a for a in apps if a.name == "notinstalled")
    assert not_installed.is_installed is False


def test_load_registry_missing_file(tmp_path):
    with pytest.raises(RegistryError):
        load_registry(tmp_path / "does-not-exist.yaml")


def test_load_registry_invalid_yaml(tmp_path):
    bad = tmp_path / "apps.yaml"
    bad.write_text("apps: [this is not: valid: yaml: at all", encoding="utf-8")
    with pytest.raises(RegistryError):
        load_registry(bad)


def test_load_registry_missing_root_key(tmp_path):
    bad = tmp_path / "apps.yaml"
    bad.write_text("not_apps: []\n", encoding="utf-8")
    with pytest.raises(RegistryError):
        load_registry(bad)


def test_load_registry_missing_required_field(tmp_path):
    bad = tmp_path / "apps.yaml"
    bad.write_text(
        """
apps:
  - name: broken
    display_name: "Broken"
    venv_bin: /tmp/bin
    entrypoint: broken
""",
        encoding="utf-8",
    )
    with pytest.raises(RegistryError):
        load_registry(bad)


def test_load_registry_duplicate_names(tmp_path, fake_app_dir):
    bad = tmp_path / "apps.yaml"
    bad.write_text(
        f"""
apps:
  - name: dup
    display_name: "Dup 1"
    path: {fake_app_dir}
    venv_bin: {fake_app_dir}/.venv/bin
    entrypoint: fakeapp
  - name: dup
    display_name: "Dup 2"
    path: {fake_app_dir}
    venv_bin: {fake_app_dir}/.venv/bin
    entrypoint: fakeapp
""",
        encoding="utf-8",
    )
    with pytest.raises(RegistryError):
        load_registry(bad)


def test_config_file_path_traversal_rejected_at_parse(tmp_path, fake_app_dir):
    bad = tmp_path / "apps.yaml"
    bad.write_text(
        f"""
apps:
  - name: fakeapp
    display_name: "Fake App"
    path: {fake_app_dir}
    venv_bin: {fake_app_dir}/.venv/bin
    entrypoint: fakeapp
    config_files:
      - label: "Escape"
        path: "../../etc/passwd"
        type: yaml
""",
        encoding="utf-8",
    )
    with pytest.raises(RegistryError):
        load_registry(bad)


def test_resolve_config_path_blocks_traversal(apps_yaml_file):
    apps = load_registry(apps_yaml_file)
    fake = next(a for a in apps if a.name == "fakeapp")
    with pytest.raises(ValueError):
        fake.resolve_config_path("../../etc/passwd")


def test_resolve_config_path_ok(apps_yaml_file):
    apps = load_registry(apps_yaml_file)
    fake = next(a for a in apps if a.name == "fakeapp")
    resolved = fake.resolve_config_path("config/settings.yaml")
    assert resolved.is_file()
