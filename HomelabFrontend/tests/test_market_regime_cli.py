"""El esquema/preflight no debe usar accidentalmente la BD configurada del servicio."""

import json

from homelab_dashboard.cli import main


def test_openapi_no_toca_db_del_entorno(tmp_path, monkeypatch, capsys):
    actual = tmp_path / "production-placeholder.db"
    actual.write_bytes(b"do-not-open-this-database")
    monkeypatch.setenv("DASHBOARD_DB_FILE", str(actual))
    assert main(["openapi"]) == 0
    assert actual.read_bytes() == b"do-not-open-this-database"
    schema = json.loads(capsys.readouterr().out)
    assert "/api/v1/market-regime/overview" in schema["paths"]
    assert "regime_level" in schema["components"]["schemas"]["UsuarioOut"]["properties"]
