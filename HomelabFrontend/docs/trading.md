# Contrato del módulo de trading

Este documento describe el módulo de trading del dashboard: por qué existen dos
motores, qué contrato cumple cada uno, y las tres barreras que impiden que el
sistema opere con dinero real.

Se escribe con el mismo criterio que `watchers-contract.md`: registrar las
decisiones con archivo y función exactos, para que la próxima persona no tenga
que reconstruir el razonamiento leyendo el código.

---

## 1. El módulo invierte el principio central de la app

El resto de HomelabDashboard está construido sobre una idea: **cada usuario ve y
ejecuta lo suyo**. Las vigilancias, el portafolio y las programaciones cuelgan de
un `user_id` y nadie puede tocar los datos de otro.

El trading hace lo contrario a propósito. Hay **un bot por motor, compartido**.
La configuración es una sola, la ve todo el que tenga acceso, y quien tenga
nivel de operador puede cambiarla para todos. Encenderlo o apagarlo afecta a
todo el mundo.

Esto no es un descuido: es la consecuencia de que el bot sea un proceso único en
una VM con recursos limitados. Un motor por usuario no cabe. Pero como rompe la
expectativa que crea el resto de la interfaz, el módulo tiene dos obligaciones
que ninguna otra pantalla tiene:

1. **Decir siempre quién cambió qué y cuándo.** `TradingBotConfig.updated_by_user_id`
   y `updated_at` se muestran en la propia pantalla (`routes/Trading.tsx`, fila
   "Última edición"). Sin esa línea, una configuración que cambió sola es
   indistinguible de un error del sistema.
2. **Asumir que el estado cambia mientras lo miras.** De ahí el bloqueo
   optimista de la sección 4.

---

## 2. Dos motores, porque ninguno cubre ambos mercados

| | Freqtrade | TradingLab (Lumibot) |
|---|---|---|
| Mercado | Cripto | Acciones y ETFs |
| Licencia | GPL-3.0 | GPL-3.0 |
| Forma | Demonio con API REST | Librería embebida en un proceso propio |
| Control | **Imperativo** | **Declarativo** |
| Datos simulados contra | Precios reales del exchange | Alpaca Paper |

La investigación previa descartó el resto: `backtrader`, `zipline`, `PyAlgoTrade`
y `Gekko` están abandonados; `StockSharp` dejó de ser software libre;
`vectorbt` y `PyBroker` llevan Commons Clause (prohíben el uso comercial, y una
app multiusuario es zona gris); `backtesting.py` es AGPL.

Conviene decirlo sin adornos: **ningún bot es rentable por sí mismo**. Freqtrade
tiene 54 000 estrellas porque es una buena infraestructura, no porque gane
dinero. La estrategia la pone quien lo configura, y la evidencia sobre operativa
frecuente es mala. Por eso este módulo es de simulación y la interfaz lo repite
en un aviso que no se puede descartar.

### La asimetría imperativo/declarativo

Es el concepto que hay que entender antes de tocar `trading.py`.

- **Freqtrade es imperativo.** El dashboard le *ordena* por REST
  (`POST /api/v1/start`, `/stop`). La verdad sobre si está corriendo vive en su
  proceso, y el dashboard la pregunta.
- **TradingLab es declarativo.** El dashboard *escribe* `enabled` en
  `trading_bot_config` y TradingLab lo consulta en cada ciclo. Por eso
  `AdaptadorTradingLab.encender()` y `.apagar()` son **no-op deliberados**: no
  hay nadie a quien darle la orden, el estado deseado ya quedó en la base.

El dashboard lee la base de TradingLab en **solo lectura**
(`file:...?mode=ro`), nunca escribe en ella.

---

## 3. Las tres capas que impiden operar con dinero real

Están documentadas en el docstring de `src/homelab_dashboard/trading.py` y son
independientes: cada una bastaría por sí sola, y por eso hay tres.

1. **Esquema.** La columna `trading_bot_config.mode` tiene un `CHECK` que solo
   admite `'paper'`. La base rechaza `mode='live'` aunque el código lo intente.
2. **Validación.** `CLAVES_PROHIBIDAS` en `validar_config` rechaza `dry_run`,
   `live`, `trading_mode`, `mode`, `api_key`, `api_secret`, `secret`,
   `password` y `exchange_key`. Además `ConfigTradingIn` hereda `extra="forbid"`,
   así que una clave desconocida ni siquiera llega al validador.
3. **Generación.** `config_freqtrade` fija `dry_run: True` como literal. No lo
   lee de la configuración guardada, así que no hay valor que manipular.

Como red extra: si Freqtrade reporta `dry_run: false`,
`AdaptadorFreqtrade.estado()` lo trata como anomalía grave y devuelve
`corriendo=False` con `modo="desconocido"`. El panel deja de decir que todo va
bien en cuanto el motor se sale del contrato.

`TRADING_MODES = ("paper",)` es una tupla de un solo elemento a propósito:
habilitar operativa real exigiría una migración de base de datos. La fricción
es deliberada.

---

## 4. Permisos y concurrencia

### Quién entra

El nivel efectivo lo resuelve **una sola función**: `User.trading_level`
(`models.py`). La consultan tanto `deps.acceso_trading`, que protege las rutas,
como `UsuarioOut`, que viaja en `/auth/me`. Tener una sola fuente evita el fallo
clásico de que la navegación ofrezca una sección que la API luego niega.

- Un **admin** cuenta como operador sin concesión explícita.
- Una cuenta que no esté `active` no tiene acceso aunque conserve su fila: el
  permiso no salta la aprobación.
- Revocar es **borrar la fila**. No hay columna `enabled` a propósito: un
  permiso "concedido pero desactivado" es un estado ambiguo.

### Códigos de error

| Situación | Respuesta |
|---|---|
| Sin acceso al módulo | **404** `no_encontrado` — no se revela que el módulo existe |
| `viewer` intentando mutar | **403** `trading_solo_lectura` |
| Versión desactualizada | **409** `trading_version_desactualizada` |
| Configuración inválida | **422** con `fields` por campo |

### Bloqueo optimista

Cada mutación viaja con la `version` que el cliente leyó. Si no coincide, el
servidor responde 409 en vez de sobrescribir el trabajo de otro. La `version`
cubre **la fila entera**: encender el bot también la sube, lo que invalida a
propósito cualquier edición de configuración que estuviera en vuelo.

En el frontend, `sembrarBot()` (`lib/consultas.ts`) siembra en la caché el bot
que devuelve cada mutación. Si solo se invalidara, un segundo guardado rápido
saldría con la versión vieja y chocaría contra su propio cambio anterior.

### El interruptor guarda intención, no resultado

Si el motor falla al encender, la intención **se persiste igual** y la API
responde 200 con `estado.alcanzable=false` y el detalle del fallo. No se
devuelve error porque lo que se pidió sí quedó guardado. La interfaz lo dice tal
cual: «Encendimos X, pero aún no responde».

---

## 5. Lo que TradingLab debe proveer

`AdaptadorTradingLab` lee un SQLite en la ruta de `DASHBOARD_TRADINGLAB_DB`.
El paquete hermano `TradingLab/` debe mantener estas dos tablas:

**`estado_motor`** — una fila, el latido del proceso:

| Columna | Sentido |
|---|---|
| `latido_en` | Marca de tiempo del último ciclo. Si se queda vieja, el panel lo reporta como caído |
| `detalle` | Texto corto que se muestra bajo el interruptor |
| `posiciones_abiertas` | Entero |
| `version` | Versión del motor, informativa |

**`operaciones`** — una fila por operación simulada:

`instrumento`, `lado`, `cantidad`, `precio_entrada`, `precio_salida`, `pnl_absoluto`,
`pnl_pct`, `costos`, `abierta_en`, `cerrada_en`.

TradingLab debe leer `enabled` de `trading_bot_config` en cada ciclo y detenerse
solo cuando esté en `false`.

---

## 6. Añadir un motor

`_fila()` en `routes_trading.py` crea la fila del motor al vuelo, no en la
migración. Añadir un motor es, por tanto, **registrar un `MotorSpec` en
`MOTORES`** (`trading.py`) y escribir su adaptador. Ni la base ni la interfaz
necesitan cambios: la pantalla se adapta a `MotorInfoOut`, que declara el
término singular y plural, el ejemplo de instrumento, el máximo y los marcos
temporales.

---

## 7. Operación en la VM

Estos puntos no son opcionales; el bot comparte máquina con el dashboard.

- **Tamaño de la VM.** `Standard_B2s` (2 vCPU, 4 GiB) no da para ambos motores
  más el dashboard. `PortfolioWatcher/infra/variables.tf` pasa a
  `Standard_B2as_v2` (2 vCPU, **8 GiB**, ≈ 54,90 USD/mes en East US, PAYG),
  que cabe en el presupuesto de 150 USD/mes. Requiere `terraform apply`.
- **Límite de memoria.** Cada unidad `systemd` necesita `MemoryMax=`. Sin él, un
  motor con fuga de memoria tumba el dashboard entero.
- **Secretos.** `DASHBOARD_FREQTRADE_USER` y `DASHBOARD_FREQTRADE_PASSWORD` van
  en el entorno de la unidad, **nunca en la base de datos**.
- **Exposición.** La documentación de Freqtrade pide explícitamente no exponer
  su API a internet: `listen_ip_address: 127.0.0.1`.
- **Límites de instrumentos.** Freqtrade 15, TradingLab 25. No son arbitrarios:
  cada instrumento cuesta memoria y llamadas en una máquina compartida.

### Implicación tributaria (Colombia)

Operar a diario configura **habitualidad** ante la DIAN, lo que lleva las
ganancias a renta ordinaria (hasta 39 %) en vez de ganancia ocasional. Aunque
hoy todo sea simulado, si algún día se opera de verdad hará falta el histórico:
**guardar la TRM del día junto a cada operación desde el primer día**.
Reconstruirla después es mucho más caro que registrarla al vuelo.
