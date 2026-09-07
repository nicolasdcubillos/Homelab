"""Tests de la API de trading: el único recurso compartido de la app.

Lo que se prueba aquí no es "que guarde", sino lo que hace distinto a este
módulo del resto: que sin permiso el módulo no exista, que un `viewer` no pueda
tocarlo, que dos personas editando a la vez no se pisen, y que todo lo que muta
quede en la bitácora.
"""

from __future__ import annotations

import importlib
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session

from homelab_dashboard import trading
from homelab_dashboard.api import routes_trading
from homelab_dashboard.api.errors import ApiError
from homelab_dashboard.models import TradingBotConfig, User

CONFIG = {
    "instrumentos": ["BTC/USDT", "ETH/USDT"],
    "estrategia": "MiEstrategia",
    "timeframe": "1h",
    "capital_simulado": 10000.0,
    "max_posiciones_abiertas": 3,
    "stop_loss_pct": 5.0,
    "take_profit_pct": 10.0,
    "max_perdida_diaria_pct": 8.0,
}


class MotorFalso:
    """Doble de un motor. Guarda las órdenes que recibió y puede fingirse caído."""

    def __init__(self) -> None:
        self.ordenes: list[str] = []
        self.caido = False
        self.corriendo = False
        self.config_version = None

    def estado(self):
        if self.caido:
            raise trading.ErrorDeMotor("servicio no disponible")
        return trading.EstadoMotor(
            alcanzable=True,
            corriendo=self.corriendo,
            detalle="Operando" if self.corriendo else "En pausa",
            estado="operando" if self.corriendo else "pausado",
            config_version=self.config_version,
        )

    def encender(self):
        if self.caido:
            raise trading.ErrorDeMotor("servicio no disponible")
        self.ordenes.append("encender")
        self.corriendo = True

    def apagar(self):
        if self.caido:
            raise trading.ErrorDeMotor("servicio no disponible")
        self.ordenes.append("apagar")
        self.corriendo = False

    def operaciones(self, limite=50):
        if self.caido:
            raise trading.ErrorDeMotor("servicio no disponible")
        return []

    def rendimiento(self, capital_inicial):
        if self.caido:
            raise trading.ErrorDeMotor("servicio no disponible")
        return trading.Rendimiento.vacio(capital_inicial)


@pytest.fixture()
def motores(app):
    """Sustituye los motores reales por dobles, como el 'entrypoint falso'."""
    dobles: dict[str, MotorFalso] = {
        nombre: MotorFalso() for nombre in trading.MOTORES
    }

    def fabrica(spec, settings, *, habilitado):
        return dobles[spec.bot_name]

    app.state.trading_adaptadores = fabrica
    return dobles


def _id_de(admin, email: str) -> str:
    items = admin.get("/api/v1/admin/users").json()["items"]
    return next(u["id"] for u in items if u["email"] == email)


@pytest.fixture()
def activar(admin):
    """Activa una cuenta recién registrada: sin esto no llega al trading."""

    def _activar(email: str) -> str:
        uid = _id_de(admin, email)
        respuesta = admin.patch(f"/api/v1/admin/users/{uid}", json={"status": "active"})
        assert respuesta.status_code == 200, respuesta.text
        return uid

    return _activar


@pytest.fixture()
def operador(admin, nuevo_usuario, activar):
    cliente = nuevo_usuario("operador@ejemplo.com")
    uid = activar("operador@ejemplo.com")
    assert admin.put(f"/api/v1/trading/access/{uid}", json={"level": "operator"}).status_code == 200
    return cliente


@pytest.fixture()
def lector(admin, nuevo_usuario, activar):
    cliente = nuevo_usuario("lector@ejemplo.com")
    uid = activar("lector@ejemplo.com")
    assert admin.put(f"/api/v1/trading/access/{uid}", json={"level": "viewer"}).status_code == 200
    return cliente


def _bot(cliente, nombre="freqtrade"):
    respuesta = cliente.get(f"/api/v1/trading/bots/{nombre}")
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()


def _guardar(cliente, version, nombre="freqtrade", **cambios):
    return cliente.put(
        f"/api/v1/trading/bots/{nombre}/config",
        json={**CONFIG, **cambios, "version": version},
    )


# ---------------------------------------------------------------------------
# Quién puede ver el módulo
# ---------------------------------------------------------------------------


def test_anonimo_no_entra(client):
    assert client.get("/api/v1/trading/bots").status_code == 401


def test_sin_permiso_el_modulo_no_existe(admin, nuevo_usuario, activar, motores):
    """404 y no 403: quien no fue autorizado no debe deducir que hay un bot."""
    cliente = nuevo_usuario("ajeno@ejemplo.com")
    activar("ajeno@ejemplo.com")
    respuesta = cliente.get("/api/v1/trading/bots")
    assert respuesta.status_code == 404
    assert respuesta.json()["error"]["code"] == "no_encontrado"


def test_cuenta_pendiente_no_entra_aunque_tenga_permiso(admin, nuevo_usuario, motores):
    """El permiso no salta la aprobación: `acceso_trading` cuelga de operativo."""
    cliente = nuevo_usuario("pendiente@ejemplo.com")
    uid = _id_de(admin, "pendiente@ejemplo.com")
    assert admin.put(f"/api/v1/trading/access/{uid}", json={"level": "operator"}).status_code == 200
    respuesta = cliente.get("/api/v1/trading/bots")
    assert respuesta.status_code == 403
    assert respuesta.json()["error"]["code"] == "cuenta_no_activa"


def test_admin_es_operador_implicito(admin, motores):
    cuerpo = admin.get("/api/v1/trading/bots").json()
    assert cuerpo["nivel"] == "operator"
    assert {i["motor"]["bot_name"] for i in cuerpo["items"]} == set(trading.MOTORES)


def test_la_sesion_declara_el_nivel(admin, nuevo_usuario, activar, lector, motores):
    """La navegación lo lee de aquí: no puede ofrecer lo que la API negaría."""
    assert admin.get("/api/v1/auth/me").json()["user"]["trading_level"] == "operator"
    assert lector.get("/api/v1/auth/me").json()["user"]["trading_level"] == "viewer"

    ajeno = nuevo_usuario("ajeno2@ejemplo.com")
    activar("ajeno2@ejemplo.com")
    assert ajeno.get("/api/v1/auth/me").json()["user"]["trading_level"] is None


def test_el_nivel_cae_al_suspender(admin, operador, motores):
    """Suspender corta la sesión de raíz, sin depender del permiso de trading."""
    uid = _id_de(admin, "operador@ejemplo.com")
    suspender = admin.patch(f"/api/v1/admin/users/{uid}", json={"status": "suspended"})
    assert suspender.status_code == 200
    assert operador.raw.get("/api/v1/auth/me").status_code == 401
    assert operador.raw.get("/api/v1/trading/bots").status_code == 401


def test_revocar_baja_el_nivel_de_la_sesion(admin, operador, motores):
    """Sin fila no hay nivel: la navegación deja de ofrecer la sección."""
    uid = _id_de(admin, "operador@ejemplo.com")
    assert operador.get("/api/v1/auth/me").json()["user"]["trading_level"] == "operator"
    assert admin.delete(f"/api/v1/trading/access/{uid}").status_code == 204
    assert operador.get("/api/v1/auth/me").json()["user"]["trading_level"] is None


def test_todos_ven_la_misma_configuracion(admin, operador, lector, motores):
    """El bot es compartido: lo que guarda uno lo ven los demás."""
    bot = _bot(operador)
    assert _guardar(operador, bot["version"], estrategia="Compartida").status_code == 200
    for cliente in (admin, lector):
        assert _bot(cliente)["config"]["estrategia"] == "Compartida"


# ---------------------------------------------------------------------------
# Niveles
# ---------------------------------------------------------------------------


def test_lector_ve_pero_no_toca(lector, motores):
    assert lector.get("/api/v1/trading/bots").json()["nivel"] == "viewer"

    guardado = _guardar(lector, _bot(lector)["version"])
    assert guardado.status_code == 403
    assert guardado.json()["error"]["code"] == "trading_solo_lectura"

    interruptor = lector.post(
        "/api/v1/trading/bots/freqtrade/switch", json={"enabled": True, "version": 1}
    )
    assert interruptor.status_code == 403
    assert interruptor.json()["error"]["code"] == "trading_solo_lectura"


def test_lector_no_gestiona_accesos(lector, motores):
    """Los accesos son de admin: para un operador o lector no existen."""
    assert lector.get("/api/v1/trading/access").status_code == 404


def test_operador_no_gestiona_accesos(operador, motores):
    assert operador.get("/api/v1/trading/access").status_code == 404


def test_operador_guarda_y_sube_version(operador, motores):
    bot = _bot(operador)
    respuesta = _guardar(operador, bot["version"], take_profit_pct=12.0)
    assert respuesta.status_code == 200
    nuevo = respuesta.json()
    assert nuevo["config"]["take_profit_pct"] == 12.0
    assert nuevo["version"] == bot["version"] + 1
    assert nuevo["updated_by_email"] == "operador@ejemplo.com"


# ---------------------------------------------------------------------------
# Ediciones concurrentes
# ---------------------------------------------------------------------------


def test_bloqueo_optimista(admin, operador, motores):
    """Dos personas editando la misma fila: la segunda no pisa a la primera."""
    version = _bot(operador)["version"]
    assert _guardar(operador, version, estrategia="Primera").status_code == 200

    segunda = _guardar(admin, version, estrategia="Segunda")
    assert segunda.status_code == 409
    assert segunda.json()["error"]["code"] == "trading_version_desactualizada"
    assert _bot(admin)["config"]["estrategia"] == "Primera"


def test_encender_tambien_sube_la_version(operador, motores):
    """El interruptor cambia la fila, así que invalida las versiones en vuelo."""
    bot = _bot(operador, "lumibot")
    assert _guardar(
        operador, bot["version"], "lumibot", instrumentos=["AAPL"], estrategia="cruce_medias"
    ).status_code == 200
    version = _bot(operador, "lumibot")["version"]

    encendido = operador.post(
        "/api/v1/trading/bots/lumibot/switch", json={"enabled": True, "version": version}
    )
    assert encendido.status_code == 200
    assert encendido.json()["version"] == version + 1
    # Quien tuviera la versión anterior en pantalla ya no puede guardar a ciegas.
    assert _guardar(operador, version, "lumibot").status_code == 409


# ---------------------------------------------------------------------------
# Interruptor
# ---------------------------------------------------------------------------


def test_no_se_enciende_sin_instrumentos(operador, motores):
    """Un bot sin nada que vigilar diría 'operando' sin operar: peor que apagado."""
    bot = _bot(operador)
    assert bot["config"]["instrumentos"] == []
    respuesta = operador.post(
        "/api/v1/trading/bots/freqtrade/switch",
        json={"enabled": True, "version": bot["version"]},
    )
    assert respuesta.status_code == 422
    assert "instrumentos" in respuesta.json()["error"]["fields"]
    assert motores["freqtrade"].ordenes == []


def test_encender_y_apagar_llegan_al_motor(operador, motores):
    version = _guardar(
        operador, _bot(operador, "lumibot")["version"], "lumibot",
        instrumentos=["AAPL"], estrategia="cruce_medias",
    ).json()["version"]
    encendido = operador.post(
        "/api/v1/trading/bots/lumibot/switch", json={"enabled": True, "version": version}
    )
    assert encendido.status_code == 200
    assert encendido.json()["enabled"] is True
    assert encendido.json()["estado"]["corriendo"] is True

    version = encendido.json()["version"]
    apagado = operador.post(
        "/api/v1/trading/bots/lumibot/switch", json={"enabled": False, "version": version}
    )
    assert apagado.status_code == 200
    assert apagado.json()["enabled"] is False
    assert motores["lumibot"].ordenes == ["encender", "apagar"]


def test_motor_caido_conserva_la_intencion(operador, motores):
    """Se guarda lo que se pidió y se dice que el motor no respondió."""
    version = _guardar(
        operador, _bot(operador, "lumibot")["version"], "lumibot",
        instrumentos=["AAPL"], estrategia="cruce_medias",
    ).json()["version"]
    motores["lumibot"].caido = True

    respuesta = operador.post(
        "/api/v1/trading/bots/lumibot/switch", json={"enabled": True, "version": version}
    )
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["enabled"] is True
    assert cuerpo["estado"]["alcanzable"] is False
    assert "no respondió" in cuerpo["estado"]["detalle"]

    # Y la intención quedó persistida, no se perdió con el fallo.
    assert _bot(operador, "lumibot")["enabled"] is True


def test_lecturas_sobreviven_a_un_motor_caido(operador, motores):
    """La configuración se debe poder ver aunque el bot esté abajo."""
    motores["freqtrade"].caido = True
    assert _bot(operador)["estado"]["alcanzable"] is False

    operaciones = operador.get("/api/v1/trading/bots/freqtrade/trades")
    assert operaciones.status_code == 200
    # "No pude preguntar" no es lo mismo que "no hay ninguna".
    assert operaciones.json()["disponible"] is False

    rendimiento = operador.get("/api/v1/trading/bots/freqtrade/performance")
    assert rendimiento.status_code == 200
    assert rendimiento.json()["disponible"] is False


# ---------------------------------------------------------------------------
# El modo simulado no se puede desactivar
# ---------------------------------------------------------------------------


def test_el_modo_siempre_es_paper(operador, motores):
    for item in operador.get("/api/v1/trading/bots").json()["items"]:
        assert item["modo"] == "paper"


@pytest.mark.parametrize("clave", ["dry_run", "mode", "api_key", "live"])
def test_la_api_rechaza_lo_que_lleve_a_dinero_real(operador, motores, clave):
    """`extra=forbid` no es higiene aquí: es la barrera contra el modo real."""
    respuesta = operador.put(
        "/api/v1/trading/bots/freqtrade/config",
        json={**CONFIG, "version": _bot(operador)["version"], clave: False},
    )
    assert respuesta.status_code == 422


def test_motor_inexistente(operador, motores):
    assert operador.get("/api/v1/trading/bots/inventado").status_code == 404


# ---------------------------------------------------------------------------
# Auditoría
# ---------------------------------------------------------------------------


def test_todo_lo_que_muta_queda_en_la_bitacora(admin, operador, motores):
    """Sin dueño por fila, la bitácora es la única forma de saber quién fue."""
    version = _guardar(operador, _bot(operador)["version"], estrategia="Auditada").json()["version"]
    operador.post(
        "/api/v1/trading/bots/freqtrade/switch", json={"enabled": False, "version": version}
    )

    entradas = admin.get("/api/v1/admin/audit?limit=50").json()["items"]
    acciones = {e["action"] for e in entradas}
    assert "trading.config_actualizada" in acciones
    assert "trading.apagado" in acciones
    assert "trading.acceso_concedido" in acciones

    config = next(e for e in entradas if e["action"] == "trading.config_actualizada")
    assert config["actor_email"] == "operador@ejemplo.com"
    assert config["detail_json"]["bot_name"] == "freqtrade"
    assert config["detail_json"]["por_admin"] is False
    assert config["detail_json"]["cambios"]["estrategia"]["despues"] == "Auditada"


def test_la_bitacora_distingue_al_admin(admin, motores):
    """Importa saber si alguien entró por permiso explícito o por ser admin."""
    _guardar(admin, _bot(admin)["version"])
    entradas = admin.get("/api/v1/admin/audit?limit=20").json()["items"]
    config = next(e for e in entradas if e["action"] == "trading.config_actualizada")
    assert config["detail_json"]["por_admin"] is True


# ---------------------------------------------------------------------------
# Concesión y revocación de accesos
# ---------------------------------------------------------------------------


def test_admin_lista_los_accesos(admin, operador, lector, motores):
    items = admin.get("/api/v1/trading/access").json()["items"]
    por_email = {i["email"]: i["level"] for i in items}
    assert por_email == {"operador@ejemplo.com": "operator", "lector@ejemplo.com": "viewer"}
    assert all(i["granted_by_email"] == "admin@ejemplo.com" for i in items)


def test_cambiar_de_nivel(admin, lector, motores):
    uid = _id_de(admin, "lector@ejemplo.com")
    assert admin.put(f"/api/v1/trading/access/{uid}", json={"level": "operator"}).status_code == 200
    assert _guardar(lector, _bot(lector)["version"]).status_code == 200


def test_revocar_devuelve_el_modulo_a_la_inexistencia(admin, operador, motores):
    uid = _id_de(admin, "operador@ejemplo.com")
    assert admin.delete(f"/api/v1/trading/access/{uid}").status_code == 204
    assert operador.get("/api/v1/trading/bots").status_code == 404

    entradas = admin.get("/api/v1/admin/audit?limit=20").json()["items"]
    revocado = next(e for e in entradas if e["action"] == "trading.acceso_revocado")
    assert revocado["target_email"] == "operador@ejemplo.com"


def test_revocar_a_quien_no_tiene_acceso(admin, nuevo_usuario, activar, motores):
    nuevo_usuario("nadie@ejemplo.com")
    uid = activar("nadie@ejemplo.com")
    assert admin.delete(f"/api/v1/trading/access/{uid}").status_code == 404


def test_conceder_a_un_usuario_inexistente(admin, motores):
    assert admin.put("/api/v1/trading/access/noexiste", json={"level": "viewer"}).status_code == 404


def test_nivel_invalido(admin, nuevo_usuario, activar, motores):
    nuevo_usuario("raro@ejemplo.com")
    uid = activar("raro@ejemplo.com")
    assert admin.put(f"/api/v1/trading/access/{uid}", json={"level": "dios"}).status_code == 422


# ---------------------------------------------------------------------------
# CSRF
# ---------------------------------------------------------------------------


def test_mutar_sin_csrf(operador, motores):
    """La cookie sola no basta: la SPA debe reenviar el token."""
    respuesta = operador.raw.put(
        "/api/v1/trading/bots/freqtrade/config", json={**CONFIG, "version": 1}
    )
    assert respuesta.status_code == 403
    assert respuesta.json()["error"]["code"] == "csrf_invalido"


def test_freqtrade_activacion_bloqueada_no_guarda_intencion(operador, motores):
    guardado = _guardar(operador, _bot(operador)["version"]).json()
    assert guardado["config_aplicada"] is False
    assert not guardado["motor"]["permite_encender"]
    respuesta = operador.post(
        "/api/v1/trading/bots/freqtrade/switch",
        json={"enabled": True, "version": guardado["version"]},
    )
    assert respuesta.status_code == 409
    assert respuesta.json()["error"]["code"] == "trading_activacion_bloqueada"
    posterior = _bot(operador)
    assert posterior["version"] == guardado["version"]
    assert not posterior["enabled"]
    assert motores["freqtrade"].ordenes == []


def test_confirmacion_de_config_exige_version_observada(operador, motores):
    bot = _bot(operador, "lumibot")
    assert not bot["config_aplicada"]
    motores["lumibot"].config_version = bot["version"]
    assert _bot(operador, "lumibot")["config_aplicada"]
    nuevo = _guardar(
        operador, bot["version"], "lumibot", instrumentos=["AAPL"], estrategia="cruce_medias",
    ).json()
    assert not nuevo["config_aplicada"]
    motores["lumibot"].caido = True
    motores["lumibot"].config_version = nuevo["version"]
    assert not _bot(operador, "lumibot")["config_aplicada"]


@pytest.mark.parametrize("campo,valor", [
    ("capital_simulado", True), ("capital_simulado", "10000"),
    ("capital_simulado", "NaN"), ("max_posiciones_abiertas", True),
    ("max_posiciones_abiertas", 2.5), ("max_posiciones_abiertas", 2.0),
    ("stop_loss_pct", True), ("version", True),
])
def test_api_rechaza_coerciones_de_config(operador, motores, campo, valor):
    version = _bot(operador)["version"]
    respuesta = operador.put(
        "/api/v1/trading/bots/freqtrade/config",
        json={**CONFIG, "version": version, campo: valor},
    )
    assert respuesta.status_code == 422
    assert _bot(operador)["version"] == version


@pytest.mark.parametrize("valor", ["false", "true", 0, 1, None])
def test_interruptor_exige_booleano_real(operador, motores, valor):
    respuesta = operador.post(
        "/api/v1/trading/bots/lumibot/switch", json={"enabled": valor, "version": 1},
    )
    assert respuesta.status_code == 422


def test_retirar_todos_instrumentos_conserva_habilitado_y_bloqueo_optimista(operador, motores):
    bot = _guardar(
        operador, _bot(operador, "lumibot")["version"], "lumibot",
        instrumentos=["AAPL"], estrategia="cruce_medias",
    ).json()
    encendido = operador.post(
        "/api/v1/trading/bots/lumibot/switch",
        json={"enabled": True, "version": bot["version"]},
    ).json()
    respuesta = _guardar(
        operador, encendido["version"], "lumibot", instrumentos=[], estrategia="cruce_medias",
    )
    assert respuesta.status_code == 200
    guardado = respuesta.json()
    assert guardado["enabled"]
    assert guardado["config"]["instrumentos"] == []
    assert guardado["version"] == encendido["version"] + 1
    assert guardado["estado"]["config_version"] == encendido["estado"]["config_version"]
    assert not guardado["config_aplicada"]
    assert motores["lumibot"].ordenes == ["encender"]
    assert _guardar(
        operador, encendido["version"], "lumibot",
        instrumentos=["SPY"], estrategia="cruce_medias",
    ).status_code == 409
    persistido = _bot(operador, "lumibot")
    assert persistido["enabled"] and persistido["config"]["instrumentos"] == []


def test_encendido_revalida_config_almacenada_y_apagado_no_se_impide(
    operador, motores, db
):
    bot = _bot(operador, "lumibot")
    fila = db.get(TradingBotConfig, "lumibot")
    fila.config_json = {**CONFIG, "instrumentos": ["AAPL"], "estrategia": "no_existe"}
    db.commit()
    respuesta = operador.post(
        "/api/v1/trading/bots/lumibot/switch",
        json={"enabled": True, "version": bot["version"]},
    )
    assert respuesta.status_code == 422
    assert motores["lumibot"].ordenes == []
    assert operador.post(
        "/api/v1/trading/bots/lumibot/switch",
        json={"enabled": False, "version": bot["version"]},
    ).status_code == 200


@pytest.mark.parametrize("estado", ["error", "bloqueado", "stale", "desconocido"])
def test_datos_no_vigentes_no_se_presentan_como_resultados(operador, motores, estado):
    motores["lumibot"].estado = lambda: trading.EstadoMotor(
        alcanzable=estado != "stale", corriendo=False,
        detalle="Motor no operativo", estado=estado,
    )
    for recurso in ("performance", "trades"):
        respuesta = operador.get(f"/api/v1/trading/bots/lumibot/{recurso}")
        assert respuesta.status_code == 200
        assert not respuesta.json()["disponible"]


def test_comparacion_atomica_rechaza_fila_ya_leida(admin, motores, db):
    _bot(admin, "lumibot")
    usuario = db.get(User, _id_de(admin, "admin@ejemplo.com"))
    contexto = SimpleNamespace(usuario=usuario)
    fila_vieja = db.get(TradingBotConfig, "lumibot")
    with Session(db.get_bind()) as concurrente:
        otra_fila = concurrente.get(TradingBotConfig, "lumibot")
        routes_trading._marcar(concurrente, otra_fila, contexto, enabled=True)
        concurrente.commit()
    with pytest.raises(ApiError) as exc:
        routes_trading._marcar(db, fila_vieja, contexto, enabled=False)
    assert exc.value.code == "trading_version_desactualizada"
    db.rollback()
    assert db.get(TradingBotConfig, "lumibot").enabled


def test_la_api_respeta_capacidad_de_activacion(operador, motores, monkeypatch):
    version = _guardar(
        operador, _bot(operador, "lumibot")["version"], "lumibot",
        instrumentos=["AAPL"], estrategia="cruce_medias",
    ).json()["version"]
    monkeypatch.setitem(trading.MOTORES, "lumibot", replace(
        trading.LUMIBOT, permite_encender=False, motivo_bloqueo="Control no implementado",
    ))
    respuesta = operador.post(
        "/api/v1/trading/bots/lumibot/switch", json={"enabled": True, "version": version},
    )
    assert respuesta.status_code == 409
    assert motores["lumibot"].ordenes == []
    assert not _bot(operador, "lumibot")["enabled"]


def test_motor_no_registrado_no_se_puede_activar(operador, motores):
    respuesta = operador.post(
        "/api/v1/trading/bots/no_implementado/switch", json={"enabled": True, "version": 1},
    )
    assert respuesta.status_code == 404


@pytest.fixture()
def estado_real_tradinglab(app, tmp_path, monkeypatch):
    raiz = Path(__file__).resolve().parents[2] / "TradingLab" / "src"
    monkeypatch.syspath_prepend(str(raiz))
    fuente = importlib.import_module("tradinglab.estado")
    assert Path(fuente.__file__).is_relative_to(raiz)
    ruta = tmp_path / "tradinglab-real.sqlite"
    monkeypatch.setattr(app.state, "settings", replace(app.state.settings, tradinglab_db=ruta))
    with fuente.AlmacenEstado(ruta) as almacen:
        yield almacen, fuente


def test_config_compartida_se_guarda_y_habilita_con_alpaca_pausado(
    operador, estado_real_tradinglab
):
    almacen, _ = estado_real_tradinglab
    almacen.vincular("alpaca_paper")
    almacen.latir(
        estado="pausado", modo="alpaca_paper", config_version=1,
        version="tradinglab prueba", posiciones_abiertas=2, detalle="En pausa",
    )
    antes = almacen.db_path.read_bytes()
    version = _bot(operador, "lumibot")["version"]
    respuesta = _guardar(
        operador, version, "lumibot", instrumentos=["AAPL"],
        estrategia="cruce_medias", capital_simulado=20000,
    )
    assert respuesta.status_code == 200, respuesta.text
    guardado = respuesta.json()
    assert guardado["config"]["capital_simulado"] == 20000
    assert guardado["version"] == version + 1
    assert guardado["estado"]["estado"] == "pausado"
    assert guardado["estado"]["alcanzable"]
    assert guardado["estado"]["config_version"] == 1
    assert guardado["estado"]["version"] == "tradinglab prueba"
    assert guardado["estado"]["posiciones_abiertas"] == 2
    assert "Alpaca Paper está bloqueado preventivamente" in guardado["estado"]["detalle"]
    habilitar = operador.post(
        "/api/v1/trading/bots/lumibot/switch",
        json={"enabled": True, "version": guardado["version"]},
    )
    assert habilitar.status_code == 200, habilitar.text
    assert habilitar.json()["enabled"]
    assert not habilitar.json()["estado"]["corriendo"]
    assert habilitar.json()["estado"]["estado"] == "pausado"
    assert almacen.db_path.read_bytes() == antes


def test_cambiar_presupuesto_demo_no_muta_identidad_ni_base_de_rendimiento(
    operador, estado_real_tradinglab
):
    almacen, fuente = estado_real_tradinglab
    almacen.vincular("simulado")
    almacen.restaurar_simulacion(10000)
    operacion = almacen.registrar_apertura(fuente.Apertura(
        instrumento="AAPL", lado="compra", cantidad=2, precio_entrada=100, costos=1,
    ))
    almacen.registrar_cierre(operacion, precio_salida=110, costos_salida=1)
    almacen.latir(
        estado="operando", modo="simulado", config_version=1, detalle="Simulación local",
    )
    antes = almacen.db_path.read_bytes()
    respuesta = _guardar(
        operador, _bot(operador, "lumibot")["version"], "lumibot",
        instrumentos=["AAPL"], estrategia="cruce_medias", capital_simulado=20000,
    )
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["config"]["capital_simulado"] == 20000
    assert almacen.conexion.execute(
        "SELECT capital_inicial FROM identidad_motor WHERE id = 1"
    ).fetchone()["capital_inicial"] == 10000
    rendimiento = operador.get("/api/v1/trading/bots/lumibot/performance")
    assert rendimiento.status_code == 200, rendimiento.text
    datos = rendimiento.json()
    assert datos["disponible"]
    assert datos["capital_inicial"] == 10000
    assert datos["capital_actual"] == 10018
    assert datos["pnl_pct"] == pytest.approx(0.18)
    assert almacen.db_path.read_bytes() == antes
