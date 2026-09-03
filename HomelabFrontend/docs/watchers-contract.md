# Contrato con PortfolioWatcher y StockWatcher

Este documento nace del §9 del plan de la migración a multiusuario de
HomelabDashboard, cuando seis hallazgos sobre los repos hermanos
(`PortfolioWatcher`, `StockWatcher`) quedaron documentados con archivo y
función exactos para poder arreglarlos sin re-investigar. **Los seis ya están
resueltos**, en sesiones de trabajo aparte en cada repo:

- **PortfolioWatcher**, commit `8bfa9fd` — "Add email notifier and fix
  multi-user config findings" (67 tests, ruff limpio).
- **StockWatcher**, commit `bcdf034` — "Pin the notification destination
  contract and share discoveries" (252 tests, ruff limpio).

Este documento ya no es una lista de pendientes: es el **registro de lo que
se hizo** en cada repo y el **contrato vigente** que el dashboard consume, con
los cambios que se hicieron aquí para aprovecharlo. Ninguno de los dos repos
se toca desde esta sesión; solo se lee su código para verificar el contrato.

---

## 1. PortfolioWatcher ya tiene notificador de correo — resuelto

**Antes**: el registro de notificadores solo tenía `console`, `whatsapp` y un
`telegram` que era un stub (`NotImplementedError`). La UI del dashboard tenía
que ocultar el canal "correo" para esta app.

**Ahora** (`src/portfoliowatcher/notifier.py:366-369`, commit `8bfa9fd`):

```python
register_notifier("console", lambda options: ConsoleNotifier())
register_notifier("whatsapp", lambda options: WhatsAppNotifier(options))
register_notifier("email", lambda options: EmailNotifier(options))
register_notifier("telegram", lambda options: TelegramNotifier(options))
```

`EmailNotifier` (línea 227) envía por Azure Communication Services Email,
mismo recurso y mismas claves de entorno que `StockWatcher/notifiers/email.py`
(`ACS_CONNECTION_STRING`, `ACS_EMAIL_SENDER`, `EMAIL_TO`, `EMAIL_SUBJECT`). De
paso, `TelegramNotifier` dejó de ser un stub: ya envía por la API del bot.

**Cambio hecho en el dashboard**:
- `watchers.py`: `PORTFOLIOWATCHER.canales_soportados` pasó de
  `(CHANNEL_WHATSAPP,)` a `(CHANNEL_WHATSAPP, CHANNEL_EMAIL)`. Este único
  campo alimenta tanto `GET /api/v1/me/notifications` (`supported`) como la
  validación de `PUT /me/notifications/preferences`, así que habilitarlo aquí
  bastó para que la API y la UI (que ya derivaban el selector de canales de
  `supported`, sin nada hardcodeado) ofrezcan correo para PortfolioWatcher sin
  tocar el frontend.
- Tests actualizados: `tests/test_me_api.py::test_portfoliowatcher_acepta_email`
  y `tests/test_watchers.py::test_portfoliowatcher_ya_recibe_email` /
  `test_portfoliowatcher_ya_tiene_notificador_de_email` (antes fijaban el
  comportamiento contrario).

---

## 2. Destino de notificación: de env global a `--notify-to` explícito — resuelto (parcial en PortfolioWatcher)

**Antes**: el único mecanismo era `WHATSAPP_TO`/`EMAIL_TO` por variable de
entorno, seguro solo porque `python-dotenv` usa `override=False` por
defecto — un contrato implícito, no fijado en ningún test de los repos
hermanos.

**Ahora**, ambos repos aceptan un flag `--notify-to` con precedencia
explícita sobre el entorno, pero con formas distintas:

- **StockWatcher** (`src/stockwatcher/cli.py:243-251`, commit `bcdf034`): flag
  **repetible** con prefijo de canal opcional, `[canal:]destino` (p. ej.
  `--notify-to whatsapp:+57300... --notify-to email:ana@x.com`). Se parsea con
  `parse_notify_destinations` (`config.py:234`) a un `dict[canal, [destinos]]`
  y se aplica en `_load()` (`cli.py:64-68`) como `config.notify.override_to`.
  La precedencia completa, documentada como "contrato de seguridad, no de
  preferencia" en `notifiers/base.py:76-98` (`resolve_destinations`):
  **`--notify-to` > entorno del proceso > `watches[].notify` >
  `notify_options.to`**. Un test de regresión,
  `tests/test_notify_destinations.py`, falla si alguien cambia ese orden o
  reintroduce `load_dotenv(override=True)`.
- **PortfolioWatcher** (`src/portfoliowatcher/cli.py:142-150`, commit
  `8bfa9fd`): flag **global, no repetible**, una sola lista de destinos
  separados por coma que se aplica **por igual a todos los notificadores
  activos** (`_dispatch`, `cli.py:46-59`: `options = {"to": notify_to}` se
  pasa idéntico a cada notificador construido desde `config.notifiers`). No
  distingue "este destino es para whatsapp, este otro para email" dentro de
  una misma invocación.

**Decisión tomada en el dashboard** (`watchers.py::construir_argumentos`):

- Para **StockWatcher**, `--notify-to` con prefijo de canal es estrictamente
  más robusto que el entorno y puede expresar un teléfono y un correo
  distintos en la misma corrida, así que se usa **siempre** que el usuario
  tenga un canal activo con destino: se emite un `--notify-to canal:destino`
  por cada `(canal, destino)` activo y soportado.
- Para **PortfolioWatcher**, `--notify-to` solo es seguro cuando el usuario
  tiene **exactamente un** canal activo con destino (WhatsApp *o* email, no
  ambos): en ese caso se pasa `--notify-to <destino>`. Con dos canales
  activos y destinos distintos se **omite** el flag — pasarlo mezclaría el
  correo y el teléfono en el mismo notificador — y se confía en las
  variables de entorno por canal (que sí distinguen `WHATSAPP_TO` de
  `EMAIL_TO`).
- En **ambos casos** se mantienen las variables de entorno de
  `construir_entorno` (siempre fijadas, vacías si no aplican) como segunda
  capa de defensa: si `--notify-to` no se pudo usar (PortfolioWatcher con dos
  canales) o si algún día el repo dejara de leerlo, el entorno sigue cerrando
  la puerta al cruce entre usuarios. `--notify-to` es ahora el mecanismo
  **primario**; el entorno es la red de seguridad, no al revés.
- Tests: `tests/test_watchers.py::test_stockwatcher_pasa_notify_to_por_canal`,
  `test_portfoliowatcher_pasa_notify_to_con_un_solo_canal`,
  `test_portfoliowatcher_omite_notify_to_con_dos_canales`.

Con esto, el riesgo de seguridad más serio del diseño original (que dependía
enteramente de que ningún repo cambiara a `load_dotenv(override=True)`) ya no
es la única línea de defensa: aunque alguien cambiara ese default mañana, la
mayoría de las corridas (single-channel en PortfolioWatcher, cualquier
combinación en StockWatcher) seguirían apuntando al destino correcto porque
viene de un argumento explícito, no del entorno heredado.

---

## 3. `analyze --interval-days` ya no es un no-op — resuelto, sin cambio de estrategia

**Antes**: `analyze --interval-days` escribía
`PORTFOLIOWATCHER_INTERVAL_OVERRIDE`, que ninguna función leía.

**Ahora** (`src/portfoliowatcher/config.py:195-199`, `apply_env_overrides`,
commit `8bfa9fd`):

```python
interval_override = os.getenv("PORTFOLIOWATCHER_INTERVAL_OVERRIDE")
if interval_override:
    config.analysis_interval_days = _parse_interval(
        interval_override, "PORTFOLIOWATCHER_INTERVAL_OVERRIDE"
    )
```

**Decisión**: el dashboard **sigue** generando `analysis_interval_days`
directo en el `portfolio.yaml` de cada usuario
(`watchers.py::generar_portfolio_yaml`) y **no** empezó a usar la variable de
entorno para esto. Razón: el YAML ya resuelve el caso sin ninguna dependencia
del entorno del subprocess — que es justo lo que el hallazgo #2 nos enseñó a
minimizar — y evita depender de que el usuario invoque el subcomando
`analyze` en vez de `daily`/`weekly` (el dashboard solo invoca comandos
declarados en `apps.yaml`, y hoy no incluye `analyze`). Si en el futuro se
expone `analyze` como comando ejecutable desde la UI, esta variable sería la
vía natural para un "forzar con otro intervalo justo esta vez" puntual, sin
tocar el YAML persistido.

---

## 4. `load_config` ya lee `notifiers` y `state_path` del YAML — resuelto, sin cambio de estrategia

**Antes**: esas dos claves solo se podían fijar por variable de entorno.

**Ahora** (`src/portfoliowatcher/config.py:179-184`, commit `8bfa9fd`):
`load_config` lee `data.get("state_path")` y `data.get("notifiers")` del YAML
como valores **base**, y `apply_env_overrides` (línea 191-211) los sigue
pudiendo sobreescribir — mismo orden de precedencia (YAML como base, entorno
como override) que ya usaba StockWatcher.

**Decisión**: el dashboard sigue **sin** emitir `notifiers`/`state_path` en el
YAML generado y sigue inyectándolos por `env=` en `construir_entorno`. Razón:
son valores que dependen de la ruta absoluta del workspace de ejecución por
usuario, no del contenido versionable/editable de la config; mantenerlos
fuera del YAML evita que `GET /me/apps/{app}/config-preview` (que muestra al
usuario exactamente el YAML que se generaría) filtre esas rutas de disco del
servidor.

---

## 5. Un portafolio vacío ya no aborta con una excepción sin controlar — resuelto

**Antes**: `load_config` lanzaba `ConfigError` si `holdings` estaba vacío.

**Ahora** (`src/portfoliowatcher/config.py:161-163`, commit `8bfa9fd`):

```python
raw_holdings = data.get("holdings") or []
if not raw_holdings:
    log.warning("%s defines no holdings; nothing to analyse", path)
```

Ya no lanza excepción; solo registra una advertencia y continúa con una lista
vacía.

**Decisión**: el dashboard **no** empezó a depender de este cambio para
despachar corridas. El scheduler sigue haciendo *pre-flight* y no lanza
PortfolioWatcher para un usuario sin holdings, exponiendo el motivo en
`readiness` (`GET /me/apps`) para que la UI lo explique en la tarjeta de
Inicio — porque aunque ya no aborte, correr el pipeline de análisis sin
holdings sigue siendo trabajo desperdiciado (llamadas a Azure OpenAI, precios)
para un resultado vacío. Este arreglo en el repo hermano es una red de
seguridad adicional (si algún día el pre-flight tuviera un bug), no el
mecanismo principal.

---

## 6. El discovery de StockWatcher ya no escribe en el estado por usuario — resuelto

**Antes**: `discover_stores` escribía cada tienda candidata directo en el
`StateStore` activo, que en el diseño multiusuario es privado por usuario —
cada usuario que activara discovery redescubría lo mismo.

**Ahora** (`src/stockwatcher/discovery/registry.py`, nuevo módulo, commit
`bcdf034`): el destino de la promoción de tiendas es **pluggable**:
`StateStoreRegistry` conserva el comportamiento de un solo usuario (default),
y `YamlStoreRegistry` escribe a un YAML **compartido y de solo-añadido**
(mismo formato que `config/stores.yaml`), seleccionable con
`--discovery-registry PATH`. `discover_stores` (`discovery/__init__.py:170`)
usa `build_store_registry(config, state)` para resolver cuál usar, y consulta
`registry.known_hosts()` (línea 174) antes de sondear, así que una tienda que
ya promovió otro usuario no se vuelve a probar.

**Decisión**: el dashboard **sigue sin activar discovery por defecto**
(`run --no-discovery` en la invocación generada) y **sigue tratando**
`stores.yaml` como registro compartido de solo lectura del repo administrado,
sin pasar `--discovery-registry`. Si un usuario activa discovery
explícitamente desde Ajustes, hoy seguiría escribiendo a su `StateStore`
privado (el registro pluggable requeriría que el dashboard generara y
apuntara a un `--discovery-registry` compartido, algo que no se necesita
mientras discovery esté apagado por defecto). Queda anotado como mejora
futura de bajo impacto si se decide activar discovery para todos.

---

## Notas de implementación en este dashboard

- `src/homelab_dashboard/watchers.py` concentra el conocimiento del contrato;
  es el único archivo que hay que tocar si alguno de los dos repos cambia de
  nuevo.
- `tests/test_watchers.py` incluye pruebas de contrato que **importan el
  código real** de ambos repos hermanos (saltándose si el repo no está
  disponible en la máquina) además de las pruebas unitarias con un
  entrypoint falso — así una regresión en cualquiera de los dos repos se
  detecta aquí antes de llegar a producción.
- Ningún cambio de esta ronda tocó `PortfolioWatcher` ni `StockWatcher`: solo
  se leyó su código (de solo lectura) para verificar los hashes y líneas
  citados arriba.
