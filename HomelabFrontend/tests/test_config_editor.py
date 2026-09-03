from __future__ import annotations

import pytest

from homelab_dashboard import config_editor
from homelab_dashboard.registry import load_registry


def _get_fake_app(apps_yaml_file):
    apps = load_registry(apps_yaml_file)
    return next(a for a in apps if a.name == "fakeapp")


def test_read_config_returns_existing_content(apps_yaml_file):
    app = _get_fake_app(apps_yaml_file)
    cf = app.config_files[0]
    content = config_editor.read_config(app, cf)
    assert "key: value" in content


def test_write_config_rejects_invalid_yaml(apps_yaml_file):
    app = _get_fake_app(apps_yaml_file)
    cf = app.config_files[0]
    original = config_editor.read_config(app, cf)
    with pytest.raises(config_editor.ConfigEditorError):
        config_editor.write_config(app, cf, "key: [unclosed")
    # Original file must remain untouched.
    assert config_editor.read_config(app, cf) == original


def test_write_config_creates_backup_before_overwrite(apps_yaml_file):
    app = _get_fake_app(apps_yaml_file)
    cf = app.config_files[0]
    target = app.resolve_config_path(cf.path)
    assert target.is_file()

    new_content = "key: new_value\nother: 123\n"
    written_path = config_editor.write_config(app, cf, new_content)
    assert written_path == target
    assert target.read_text(encoding="utf-8") == new_content

    backups = list(target.parent.glob(f"{target.name}.bak.*"))
    assert len(backups) == 1
    assert "key: value" in backups[0].read_text(encoding="utf-8")


def test_write_config_no_backup_when_file_did_not_exist(apps_yaml_file):
    app = _get_fake_app(apps_yaml_file)
    cf = app.config_files[0]
    target = app.resolve_config_path(cf.path)
    target.unlink()

    config_editor.write_config(app, cf, "fresh: true\n")
    backups = list(target.parent.glob(f"{target.name}.bak.*"))
    assert backups == []
    assert target.is_file()


def test_write_config_blocks_path_traversal(apps_yaml_file):
    from homelab_dashboard.registry import ConfigFile

    app = _get_fake_app(apps_yaml_file)
    traversal_cf = ConfigFile(label="evil", path="config/settings.yaml")
    object.__setattr__(traversal_cf, "path", "../../../etc/passwd")
    with pytest.raises(ValueError):
        config_editor.write_config(app, traversal_cf, "a: 1\n")
