"""Tests de la generación de configuración de los watchers.

Hay dos capas:

1. Tests estructurales que fijan el contrato tal como lo verificamos leyendo el
   código de los repos hermanos. Corren siempre.
2. Tests de contrato real que **cargan el YAML generado con el parser de
   verdad** de cada watcher, importándolo desde el repo hermano si está
   presente. Se saltan solos cuando no lo está (CI, la VM), pero en la máquina
   de desarrollo son la única forma de detectar que un repo hermano cambió su
   contrato.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

from homelab_dashboard import watchers
from homelab_dashboard.models import (
    CHANNEL_EMAIL,
    CHANNEL_WHATSAPP,
    PortfolioClosedPosition,
    PortfolioHolding,
    PortfolioProfile,
    StockWatch,
)

REPO_STOCKWATCHER = Path("/Users/nicolas/Desktop/StockWatcher")
REPO_PORTFOLIOWATCHER = Path("/Users/nicolas/Desktop/PortfolioWatcher")


def _watch(**kw) -> StockWatch:
    base = {
        "user_id": "a" * 32,
        "name": "Zapatillas",
        "enabled": True,
        "match_terms": ["air max"],
        "exclude_terms": [],
        "variants": [],
        "colors": [],
        "countries": ["CO"],
        "notify_channels": [CHANNEL_WHATSAPP],
        "gender": "mens",
        "max_price": None,
        "currency": "USD",
    }
    base.update(kw)
    return StockWatch(**base)


def _generar_watches(watches, canales=None) -> dict:
    texto = watchers.generar_watches_yaml(
        watches,
        state_path="/tmp/estado.db",
        canales_activos=canales if canales is not None else {CHANNEL_WHATSAPP},
    )
    return yaml.safe_load(texto)


# ---------------------------------------------------------------------------
# StockWatcher: estructura
# ---------------------------------------------------------------------------


def test_el_yaml_generado_lleva_cabecera_de_aviso():
    texto = watchers.generar_watches_yaml(
        [_watch()], state_path="/tmp/e.db", canales_activos={CHANNEL_WHATSAPP}
    )
    assert texto.startswith("#")
    assert "No lo edites a mano" in texto


def test_watches_incluye_los_campos_del_contrato():
    datos = _generar_watches([_watch()])
    watch = datos["watches"][0]
    assert watch["name"] == "Zapatillas"
    assert watch["match"] == ["air max"]
    assert watch["countries"] == ["CO"]
    assert watch["gender"] == "mens"
    assert watch["notify"] == [CHANNEL_WHATSAPP]
    assert watch["enabled"] is True


def test_el_estado_va_por_usuario():
    """Sin estado propio, el primero en correr marcaría todo como visto."""
    datos = _generar_watches([_watch()])
    assert datos["state"] == {"backend": "sqlite", "path": "/tmp/estado.db"}


def test_no_se_emite_bloque_defaults():
    """StockWatcher fusiona `defaults` en cada watch; escribirlo todo explícito
    evita depender de esa semántica."""
    assert "defaults" not in _generar_watches([_watch()])


def test_los_watches_desactivados_no_se_emiten():
    datos = _generar_watches([_watch(name="A"), _watch(name="B", enabled=False)])
    assert [w["name"] for w in datos["watches"]] == ["A"]


def test_el_precio_maximo_se_emite_como_texto():
    """Un float de YAML podría introducir error de redondeo en dinero."""
    datos = _generar_watches([_watch(max_price="1299.50")])
    assert datos["watches"][0]["max_price"] == "1299.50"
    assert isinstance(datos["watches"][0]["max_price"], str)


def test_los_campos_opcionales_vacios_se_omiten():
    watch = _generar_watches([_watch()])["watches"][0]
    for clave in ("exclude", "variants", "colors", "max_price"):
        assert clave not in watch


def test_los_campos_opcionales_presentes_se_emiten():
    watch = _generar_watches(
        [_watch(exclude_terms=["usado"], variants=["42"], colors=["negro"])]
    )["watches"][0]
    assert watch["exclude"] == ["usado"]
    assert watch["variants"] == ["42"]
    assert watch["colors"] == ["negro"]


def test_apagar_un_canal_lo_quita_del_yaml():
    """Apagar WhatsApp en el panel tiene que silenciar el envío de verdad."""
    watch = _watch(notify_channels=[CHANNEL_WHATSAPP, CHANNEL_EMAIL])
    datos = _generar_watches([watch], canales={CHANNEL_EMAIL})
    assert datos["watches"][0]["notify"] == [CHANNEL_EMAIL]


def test_sin_canales_activos_la_lista_de_notify_queda_vacia():
    datos = _generar_watches([_watch()], canales=set())
    assert datos["watches"][0]["notify"] == []


def test_los_paises_vacios_caen_al_default_del_watcher():
    datos = _generar_watches([_watch(countries=[])])
    assert datos["watches"][0]["countries"] == ["US"]


def test_el_yaml_admite_acentos_sin_escapar():
    datos = _generar_watches([_watch(name="Camiseta Ñandú")])
    assert datos["watches"][0]["name"] == "Camiseta Ñandú"


# ---------------------------------------------------------------------------
# PortfolioWatcher: estructura
# ---------------------------------------------------------------------------


def _perfil(**kw) -> PortfolioProfile:
    base = {
        "user_id": "a" * 32,
        "horizon": "long_term",
        "tolerance": "moderate",
        "notes": "sin notas",
        "analysis_interval_days": 5,
    }
    base.update(kw)
    return PortfolioProfile(**base)


def _holding(ticker="AAPL", **kw) -> PortfolioHolding:
    base = {
        "user_id": "a" * 32,
        "ticker": ticker,
        "quantity": 10.0,
        "avg_cost": 150.0,
        "sector_hint": "tech",
    }
    base.update(kw)
    return PortfolioHolding(**base)


def test_portfolio_incluye_perfil_y_holdings():
    datos = yaml.safe_load(
        watchers.generar_portfolio_yaml(_perfil(), [_holding()], [])
    )
    assert datos["risk_profile"]["horizon"] == "long_term"
    assert datos["risk_profile"]["tolerance"] == "moderate"
    assert datos["holdings"][0]["ticker"] == "AAPL"
    assert datos["holdings"][0]["quantity"] == 10.0


def test_el_intervalo_va_en_el_yaml_no_por_flag():
    """`--interval-days` de PortfolioWatcher es un no-op (hallazgo 3)."""
    datos = yaml.safe_load(
        watchers.generar_portfolio_yaml(_perfil(analysis_interval_days=3), [_holding()], [])
    )
    assert datos["analysis_interval_days"] == 3


def test_portfolio_sin_perfil_usa_valores_por_defecto():
    datos = yaml.safe_load(watchers.generar_portfolio_yaml(None, [_holding()], []))
    assert datos["analysis_interval_days"] == 7
    assert datos["risk_profile"]["tolerance"] == "moderate"


def test_no_se_emiten_claves_que_load_config_ignora():
    """`state_path` y `notifiers` solo se leen del entorno (hallazgo 4)."""
    datos = yaml.safe_load(
        watchers.generar_portfolio_yaml(_perfil(), [_holding()], [])
    )
    assert "state_path" not in datos
    assert "notifiers" not in datos


def test_las_posiciones_cerradas_se_emiten_solo_si_existen():
    sin = yaml.safe_load(watchers.generar_portfolio_yaml(_perfil(), [_holding()], []))
    assert "closed_positions" not in sin

    cerrada = PortfolioClosedPosition(user_id="a" * 32, ticker="TSLA", note="vendida")
    con = yaml.safe_load(
        watchers.generar_portfolio_yaml(_perfil(), [_holding()], [cerrada])
    )
    assert con["closed_positions"] == [{"ticker": "TSLA", "note": "vendida"}]


# ---------------------------------------------------------------------------
# Entorno inyectado
# ---------------------------------------------------------------------------


def test_el_entorno_define_todas_las_variables_de_destino():
    """La exhaustividad es la defensa contra el cruce de notificaciones: si una
    variable quedara sin definir, el `.env` del repo administrado aportaría el
    destino del dueño de la máquina."""
    entorno = watchers.construir_entorno(
        watchers.STOCKWATCHER,
        destinos={},
        canales_activos=set(),
        state_path="/tmp/e.db",
        config_path="/tmp/c.yaml",
    )
    assert set(watchers.VARIABLES_DE_DESTINO) <= set(entorno)
    assert entorno["WHATSAPP_TO"] == ""
    assert entorno["EMAIL_TO"] == ""


def test_el_entorno_lleva_el_destino_del_usuario():
    entorno = watchers.construir_entorno(
        watchers.STOCKWATCHER,
        destinos={CHANNEL_WHATSAPP: "+573001112233", CHANNEL_EMAIL: "ana@x.com"},
        canales_activos={CHANNEL_WHATSAPP, CHANNEL_EMAIL},
        state_path="/tmp/e.db",
        config_path="/tmp/c.yaml",
    )
    assert entorno["WHATSAPP_TO"] == "+573001112233"
    assert entorno["EMAIL_TO"] == "ana@x.com"


def test_un_canal_apagado_no_recibe_destino():
    entorno = watchers.construir_entorno(
        watchers.STOCKWATCHER,
        destinos={CHANNEL_WHATSAPP: "+573001112233"},
        canales_activos=set(),
        state_path="/tmp/e.db",
        config_path="/tmp/c.yaml",
    )
    assert entorno["WHATSAPP_TO"] == ""


def test_portfoliowatcher_ya_recibe_email():
    """Hallazgo 1 resuelto (commit 8bfa9fd): ahora sí hay notificador de
    email registrado, así que el destino se propaga por entorno."""
    entorno = watchers.construir_entorno(
        watchers.PORTFOLIOWATCHER,
        destinos={CHANNEL_EMAIL: "ana@x.com", CHANNEL_WHATSAPP: "+573001112233"},
        canales_activos={CHANNEL_EMAIL, CHANNEL_WHATSAPP},
        state_path="/tmp/e.db",
        config_path="/tmp/c.yaml",
    )
    assert entorno["EMAIL_TO"] == "ana@x.com"
    assert sorted(entorno["PORTFOLIOWATCHER_NOTIFIERS"].split(",")) == ["email", "whatsapp"]


def test_portfoliowatcher_recibe_estado_y_config_por_entorno():
    entorno = watchers.construir_entorno(
        watchers.PORTFOLIOWATCHER,
        destinos={CHANNEL_WHATSAPP: "+57300"},
        canales_activos={CHANNEL_WHATSAPP},
        state_path="/tmp/e.db",
        config_path="/tmp/c.yaml",
    )
    assert entorno["PORTFOLIOWATCHER_STATE_PATH"] == "/tmp/e.db"
    assert entorno["PORTFOLIOWATCHER_CONFIG_PATH"] == "/tmp/c.yaml"


def test_los_flags_globales_van_antes_del_subcomando():
    """Ambos CLIs usan un parser global de argparse."""
    args = watchers.construir_argumentos(
        watchers.STOCKWATCHER,
        config_path="/tmp/w.yaml",
        state_path="/tmp/e.db",
        stores_path="/repo/config/stores.yaml",
    )
    assert args[:2] == ["--watches", "/tmp/w.yaml"]
    assert "--state-path" in args
    assert "--stores" in args


def test_sin_stores_no_se_pasa_el_flag():
    args = watchers.construir_argumentos(
        watchers.STOCKWATCHER, config_path="/tmp/w.yaml", state_path="/tmp/e.db", stores_path=None
    )
    assert "--stores" not in args


def test_portfoliowatcher_solo_recibe_config():
    args = watchers.construir_argumentos(
        watchers.PORTFOLIOWATCHER,
        config_path="/tmp/p.yaml",
        state_path="/tmp/e.db",
        stores_path=None,
    )
    assert args == ["--config", "/tmp/p.yaml"]


def test_stockwatcher_pasa_notify_to_por_canal():
    """Hallazgo 2 resuelto: preferimos --notify-to explícito por invocación
    antes que depender solo de la precedencia implícita del entorno. Como
    StockWatcher distingue canal, puede llevar un teléfono y un correo
    distintos en la misma corrida."""
    args = watchers.construir_argumentos(
        watchers.STOCKWATCHER,
        config_path="/tmp/w.yaml",
        state_path="/tmp/e.db",
        stores_path=None,
        destinos={CHANNEL_WHATSAPP: "+573001112233", CHANNEL_EMAIL: "ana@x.com"},
        canales_activos={CHANNEL_WHATSAPP, CHANNEL_EMAIL},
    )
    pares = list(zip(args, args[1:]))
    assert ("--notify-to", "whatsapp:+573001112233") in pares
    assert ("--notify-to", "email:ana@x.com") in pares


def test_portfoliowatcher_pasa_notify_to_con_un_solo_canal():
    """PortfolioWatcher aplica --notify-to por igual a todos los
    notificadores activos, así que solo es seguro usarlo con un canal."""
    args = watchers.construir_argumentos(
        watchers.PORTFOLIOWATCHER,
        config_path="/tmp/p.yaml",
        state_path="/tmp/e.db",
        stores_path=None,
        destinos={CHANNEL_WHATSAPP: "+573001112233"},
        canales_activos={CHANNEL_WHATSAPP},
    )
    assert args == ["--config", "/tmp/p.yaml", "--notify-to", "+573001112233"]


def test_portfoliowatcher_omite_notify_to_con_dos_canales():
    """Con dos canales de destinos distintos no hay forma de expresarlos en
    un solo --notify-to sin ambigüedad, así que se omite y las variables de
    entorno (por canal) hacen el trabajo."""
    args = watchers.construir_argumentos(
        watchers.PORTFOLIOWATCHER,
        config_path="/tmp/p.yaml",
        state_path="/tmp/e.db",
        stores_path=None,
        destinos={CHANNEL_WHATSAPP: "+573001112233", CHANNEL_EMAIL: "ana@x.com"},
        canales_activos={CHANNEL_WHATSAPP, CHANNEL_EMAIL},
    )
    assert "--notify-to" not in args


# ---------------------------------------------------------------------------
# Contrato real contra los repos hermanos
# ---------------------------------------------------------------------------


def _importar(repo: Path, modulo: str):
    """Importa un módulo del repo hermano, o salta el test si no está."""
    if not (repo / "src").is_dir():
        pytest.skip(f"El repo hermano {repo.name} no está disponible aquí.")
    ruta = str(repo / "src")
    if ruta not in sys.path:
        sys.path.insert(0, ruta)
    try:
        import importlib

        return importlib.import_module(modulo)
    except ImportError as exc:  # pragma: no cover - depende del entorno
        pytest.skip(f"No se pudo importar {modulo}: {exc}")


def test_stockwatcher_carga_de_verdad_el_yaml_generado(tmp_path):
    """El parser real de StockWatcher acepta lo que generamos."""
    config_mod = _importar(REPO_STOCKWATCHER, "stockwatcher.config")

    destino = tmp_path / "watches.yaml"
    destino.write_text(
        watchers.generar_watches_yaml(
            [
                _watch(
                    name="Air Max",
                    match_terms=["air max"],
                    exclude_terms=["usado"],
                    variants=["42", "43"],
                    colors=["negro"],
                    max_price="1299.50",
                    countries=["CO", "US"],
                    notify_channels=[CHANNEL_WHATSAPP, CHANNEL_EMAIL],
                )
            ],
            state_path=str(tmp_path / "estado.db"),
            canales_activos={CHANNEL_WHATSAPP, CHANNEL_EMAIL},
        ),
        encoding="utf-8",
    )

    config = config_mod.load_config(destino)

    assert len(config.watches) == 1
    watch = config.watches[0]
    assert watch.name == "Air Max"
    assert watch.match == ["air max"]
    assert watch.exclude == ["usado"]
    assert watch.variants == ["42", "43"]
    assert watch.colors == ["negro"]
    assert str(watch.max_price) == "1299.50"
    assert watch.countries == ["CO", "US"]
    assert sorted(t.channel for t in watch.notify) == ["email", "whatsapp"]
    assert config.state.backend == "sqlite"
    assert config.state.path == str(tmp_path / "estado.db")


def test_stockwatcher_rechaza_un_yaml_sin_watches(tmp_path):
    """Confirma el hallazgo 5: hay que hacer pre-vuelo antes de lanzar."""
    config_mod = _importar(REPO_STOCKWATCHER, "stockwatcher.config")

    destino = tmp_path / "watches.yaml"
    destino.write_text(
        watchers.generar_watches_yaml([], state_path="/tmp/e.db", canales_activos=set()),
        encoding="utf-8",
    )
    with pytest.raises(config_mod.ConfigError):
        config_mod.load_config(destino)


def test_portfoliowatcher_carga_de_verdad_el_yaml_generado(tmp_path, monkeypatch):
    config_mod = _importar(REPO_PORTFOLIOWATCHER, "portfoliowatcher.config")

    # `load_config` aplica overrides desde el entorno del proceso; se limpian
    # para que el test no dependa de la máquina donde corre.
    for var in ("PORTFOLIOWATCHER_STATE_PATH", "PORTFOLIOWATCHER_NOTIFIERS"):
        monkeypatch.delenv(var, raising=False)

    destino = tmp_path / "portfolio.yaml"
    destino.write_text(
        watchers.generar_portfolio_yaml(
            _perfil(horizon="short_term", tolerance="aggressive", analysis_interval_days=3),
            [_holding("AAPL", quantity=10, avg_cost=150.25)],
            [PortfolioClosedPosition(user_id="a" * 32, ticker="TSLA", note="vendida")],
        ),
        encoding="utf-8",
    )

    config = config_mod.load_config(destino)

    assert config.analysis_interval_days == 3
    assert config.risk_profile.horizon == "short_term"
    assert config.risk_profile.tolerance == "aggressive"
    assert config.holdings[0].ticker == "AAPL"
    assert config.holdings[0].avg_cost == 150.25
    assert config.closed_positions[0].ticker == "TSLA"


def test_portfoliowatcher_acepta_un_yaml_sin_holdings(tmp_path):
    """Hallazgo 5 resuelto (commit 8bfa9fd): un portafolio vacío ya no
    lanza una excepción sin controlar. Seguimos sin despachar la corrida
    en ese caso: el `readiness` del scheduler exige holdings antes de
    lanzar el job, así que este cambio en el repo hermano es una red de
    seguridad adicional, no el mecanismo principal."""
    config_mod = _importar(REPO_PORTFOLIOWATCHER, "portfoliowatcher.config")

    destino = tmp_path / "portfolio.yaml"
    destino.write_text(
        watchers.generar_portfolio_yaml(_perfil(), [], []), encoding="utf-8"
    )
    config = config_mod.load_config(destino)
    assert config.holdings == []


def test_portfoliowatcher_ya_tiene_notificador_de_email():
    """Hallazgo 1 resuelto (commit 8bfa9fd): ya hay notificador de email
    registrado, además del stub de Telegram que dejó de ser un stub."""
    notifier = _importar(REPO_PORTFOLIOWATCHER, "portfoliowatcher.notifier")
    registrados = set(notifier.available_notifiers())
    assert registrados, "El registro de notificadores llegó vacío."
    assert "email" in registrados, (
        "PortfolioWatcher volvió a quedarse sin notificador de email: revierte "
        "watchers.PORTFOLIOWATCHER.canales_soportados y docs/watchers-contract.md"
    )
    assert "whatsapp" in registrados
