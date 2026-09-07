# Contrato del módulo de trading

Este documento describe el módulo de trading del dashboard: por qué existen dos
motores, qué contrato cumple cada uno y qué actuaciones se bloquean cuando no
se puede garantizar su ejecución PAPER.

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
| Control | Lectura y solicitud de parada PAPER; arranque bloqueado | **Declarativo** |
| Datos simulados contra | Precios del exchange configurado fuera del panel | Simulador local; Alpaca Paper bloqueado |

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

- **Freqtrade es imperativo.** El dashboard consulta REST y puede solicitar
  `/stop` solo tras verificar `dry_run is True`. **Nunca llama `/start`**:
  `config_freqtrade` es un generador desconectado, no instala archivos ni
  recarga el proceso; tampoco integra el freno de pérdida diaria. Guardar su
  configuración persiste una propuesta, no la aplica.
- **TradingLab es declarativo.** El dashboard *escribe* `enabled` en
  `trading_bot_config` y TradingLab lo consulta en cada ciclo. Por eso
  `AdaptadorTradingLab.encender()` y `.apagar()` son **no-op deliberados**: no
  hay nadie a quien darle la orden, el estado deseado ya quedó en la base.

El dashboard lee la base de TradingLab en **solo lectura**
(`file:...?mode=ro`), nunca escribe en ella.

---

## 3. PAPER y bloqueo preventivo

La API solo admite PAPER. Eso **no demuestra** que un proceso externo esté en
PAPER ni que se haya detenido. No hay una garantía basada en un archivo que
nadie aplica.

1. **Esquema.** La columna `trading_bot_config.mode` tiene un `CHECK` que solo
   admite `'paper'`. La base rechaza `mode='live'` aunque el código lo intente.
2. **Validación.** `CLAVES_PROHIBIDAS` en `validar_config` rechaza `dry_run`,
   `live`, `trading_mode`, `mode`, `api_key`, `api_secret`, `secret`,
   `password` y `exchange_key`. Además `ConfigTradingIn` hereda `extra="forbid"`,
   así que una clave desconocida ni siquiera llega al validador.
3. **Control cerrado.** Freqtrade no se puede activar desde el panel. Su
   configuración guardada siempre tiene `config_aplicada=false`. Las lecturas
   de resultados y solicitudes de parada exigen `dry_run` booleano `true`:
   ausencia, texto `"true"`, `1` o `false` no bastan.

Ante modo no confirmado se publica `estado="bloqueado"`, sin presentar datos
reales como simulados ni afirmar que se detuvo el proceso externo. La operación
con Alpaca Paper está bloqueada preventivamente hasta verificar SDK y
reconciliación durable; solo queda operativo el simulador local aislado.

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
| Motor sin activación implementada/verificada | **409** `trading_activacion_bloqueada`, sin mutar intención |

### Bloqueo optimista

Cada mutación viaja con la `version` que el cliente leyó. Si no coincide, el
servidor responde 409 en vez de sobrescribir el trabajo de otro. La `version`
cubre **la fila entera**: encender el bot también la sube, lo que invalida a
propósito cualquier edición de configuración que estuviera en vuelo.
La comparación y escritura usan un `UPDATE ... WHERE version = :leida`
atómico; comparar en Python antes de un `UPDATE` incondicional no protege de
dos peticiones concurrentes.

En el frontend, `sembrarBot()` (`lib/consultas.ts`) siembra en la caché el bot
que devuelve cada mutación. Si solo se invalidara, un segundo guardado rápido
saldría con la versión vieja y chocaría contra su propio cambio anterior.
El editor conserva el borrador y su versión al refrescar; no los sustituye con
la edición de otro operador. Recargar y descartar el borrador es explícito.
Se sondea también con todos los bots apagados, para detectar cambios ajenos.

### El interruptor guarda intención, no resultado

Primero se valida la configuración almacenada y la capacidad del motor.
Freqtrade devuelve 409 al intentar activarlo. En motores declarativos se guarda
la intención y se consulta el estado, nunca se deduce `corriendo` del flag.
Una actuación admitida que falla conserva la intención con estado sin confirmar.
El aviso dice «Guardamos la solicitud», no «el bot está apagado/operando».
Un apagado no liquida posiciones ni garantiza que sus stops sigan supervisados.
`motor_respondio=null` en la auditoría declarativa evita fingir una respuesta
del motor a un método que deliberadamente no hace nada.

La entrada rechaza booleanos como números, enteros fraccionarios, números no
finitos y claves desconocidas. Activar revalida todos los campos persistidos;
apagar sigue disponible ante configuración inválida. Retirar tickers, incluso
todos, conserva el bot habilitado y solicita cerrar esas posiciones demo en el
siguiente ciclo; no se debe exigir una pausa que las deje sin supervisión.
El guardado conserva el bloqueo optimista y no confirma anticipadamente los cierres.
`capital_simulado` es un presupuesto configurable para cálculos y límites:
cambiarlo no recarga el saldo ni reinicia el capital inicial durable.
Guardar configuración o intención no escribe en la SQLite del motor ni requiere
que su identidad sea demo; también se admite con Alpaca Paper pausado.

---

## 5. Lo que TradingLab debe proveer

`AdaptadorTradingLab` lee un SQLite en la ruta de `DASHBOARD_TRADINGLAB_DB`.
El paquete hermano [`TradingLab/`](../../TradingLab/README.md) mantiene estas dos
tablas:

**`estado_motor`** — una fila, el latido del proceso:

| Columna | Sentido |
|---|---|
| `latido_en` | Marca de tiempo del último ciclo. Si se queda vieja, el panel lo reporta como caído |
| `detalle` | Texto corto que se muestra bajo el interruptor |
| `posiciones_abiertas` | Entero |
| `version` | Versión del motor, informativa |
| `estado` | `operando`, `esperando`, `pausado`, `detenido`, `error` o `bloqueado` |
| `modo` | Origen observado: `simulado` o `alpaca_paper`; nunca deducido del flag |
| `config_version` | Última versión procesada por el supervisor, nullable; no es la versión del software |

La API conserva `detalle`, `latido_en`, `config_version` y el estado observado.
Solo `estado="operando"` implica `corriendo=true`; `esperando` es una espera
observada, no un error ni una evaluación en curso. `config_aplicada` solo se
confirma para TradingLab con latido vigente, estado sin error y versión
coincidente. No confirma fills ni rentabilidad. `detenido` no se presenta como
proceso alcanzable. Un esquema antiguo sin estas columnas se puede leer,
pero queda **sin confirmación**, jamás “operando” por estar `enabled=true`.
`posiciones_abiertas=null` significa desconocido; no se inventa un cero.
Para `modo="alpaca_paper"` se conservan el estado observado, las versiones y
el conteo informado; el bloqueo preventivo se añade al detalle, sin sustituir
`pausado`, `detenido` o `error` por un estado inventado. `corriendo` permanece
falso incluso si un productor Paper afirma `operando` o `esperando`.

**`operaciones`** — una fila por operación simulada:

`instrumento`, `lado`, `cantidad`, `precio_entrada`, `precio_salida`, `pnl_absoluto`,
`pnl_pct`, `costos`, `abierta_en`, `cerrada_en`.

**`identidad_motor`** identifica el origen de la SQLite y su capital inicial
durable. El dashboard solo publica operaciones del origen `simulado`; una base
sin identidad o de otro origen queda sin resultados disponibles. El capital
de resultados se lee de esta identidad, no de una propuesta en el formulario.
Freqtrade usa el `starting_balance` que reporta el proceso; si falta, los
resultados quedan no disponibles.

TradingLab debe releer `enabled` de `trading_bot_config`; el flag no demuestra
que haya aplicado todavía el cambio ni que haya cerrado posiciones.

### Vocabulario de `lado`

`lado` admite exactamente **`compra`** y **`venta`**, y no el vocabulario del
motor que tocó responder. `AdaptadorFreqtrade` traduce el suyo (`_a_operacion`
en `trading.py`) y TradingLab lo garantiza con un `CHECK` en la tabla. Es lo que
permite que `LADO_OPERACION` en `lib/etiquetas.ts` sea un mapa de dos entradas:
un valor fuera de esos dos aparecería en la tabla de operaciones como un guion,
sin ningún error visible que explicara por qué.

### El latido va separado del ciclo de trading

Es la consecuencia práctica de que la tolerancia sean **3 minutos** mientras el
`timeframe` puede ser `1d`. Si el motor solo latiera al evaluar, un bot en velas
diarias aparecería como caído 22 horas de cada 24.

TradingLab late **cada minuto** pase lo que pase —también en pausa, también tras
un error— y evalúa el mercado cada `timeframe`. Efecto secundario deseable: el
interruptor del panel puede observarse sin esperar al marco diario; no se
promete una latencia máxima si el ciclo o el proceso está bloqueado.

Consecuencia para quien escriba otro motor: **el latido no es la señal de «hice
algo», es la señal de «sigo vivo»**. Escribirlo solo cuando hay trabajo real es
el error a evitar.

Un latido ilegible, sin zona horaria, demasiado futuro (más de 5 s de desfase)
o antiguo queda `stale`, no vigente. Los endpoints de resultados y operaciones
responden `disponible=false` cuando el estado no confirma PAPER vigente, en
vez de convertir un fallo en cartera vacía. Errores de sondeo en la SPA marcan
la caché como desactualizada y no mantienen controles operativos.

`win_rate` viaja como fracción y se multiplica por 100 al mostrarlo.
“Capital más resultado realizado” excluye valoración de posiciones abiertas;
los costos no reportados se representan con `null`, no con cero.

### Marcas de tiempo

ISO-8601 en UTC con desfase explícito (`+00:00`, nunca `Z`). El dashboard ordena
con `ORDER BY abierta_en DESC`, que es un orden **de texto**: solo en ese formato
coincide con el cronológico. Además `datetime.fromisoformat` no aceptó el sufijo
`Z` hasta Python 3.11 y el dashboard declara soportar 3.10.

---

## 6. Añadir un motor

`_fila()` en `routes_trading.py` crea la fila del motor al vuelo, no en la
migración. Añadir un motor es, por tanto, **registrar un `MotorSpec` en
`MOTORES`** (`trading.py`) y escribir su adaptador. Su activación queda
bloqueada por defecto (`permite_encender=false`); solo se habilita tras
implementar y verificar el control. Los nombres desconocidos devuelven 404.
La pantalla se adapta a `MotorInfoOut`, que declara el
término singular y plural, el ejemplo de instrumento, el máximo y los marcos
temporales.

### El catálogo de estrategias es opcional a propósito

`MotorSpec.estrategias` puede ir vacío, y esa diferencia es visible en la
pantalla:

| | Catálogo declarado | Catálogo vacío |
|---|---|---|
| Motor | TradingLab | Freqtrade |
| Campo en la UI | Selector | Texto libre |
| Validación | El nombre debe estar en la lista | Identificador (`^[A-Za-z][A-Za-z0-9_]{0,63}$`) |

La razón es que en Freqtrade una estrategia es una clase Python que alguien deja
en un directorio de la VM: el dashboard **no puede** saber cuáles existen, así
que no finge saberlo. TradingLab, en cambio, las construye por nombre desde
`DISPONIBLES`, que sí es una lista cerrada.

Cuando la lista existe se rechaza cualquier otro valor en vez de aceptarlo «por
si acaso». La elección desconocida debe fallar cerrada tanto en la API como
en el productor, nunca sustituirse silenciosamente por otra estrategia.

Esa lista está escrita dos veces, en dos procesos que no se importan entre sí
(`_ESTRATEGIAS_LUMIBOT` aquí y `DISPONIBLES` en TradingLab). Es duplicación
deliberada. `tests/test_trading.py` importa la fuente real de TradingLab y
compara nombres, etiquetas, timeframes, límites, defaults y modo. También lee
SQLite escrita por `AlmacenEstado`, no solo una copia manual del esquema.

---

## 7. Operación en la VM

Estos puntos no son opcionales; el bot comparte máquina con el dashboard.

- **Tamaño de la VM.** `Standard_B2s` (2 vCPU, 4 GiB) no da para ambos motores
  más el dashboard. `PortfolioWatcher/infra/variables.tf` pasa a
  `Standard_B2as_v2` (2 vCPU, **8 GiB**, ≈ 54,90 USD/mes en East US, PAYG),
  que cabe en el presupuesto de 150 USD/mes. Requiere `terraform apply`.
- **Espacio en disco.** Lumibot arrastra **más de cincuenta dependencias
  directas** (`pyarrow`, `polars`, `scipy`, `boto3`, `ccxt`, `duckdb`,
  `matplotlib`…) y ocupa **varios cientos de megabytes**. El dimensionado hay que
  revisarlo en disco, no solo en RAM.
- **Límite de memoria.** Cada unidad `systemd` necesita `MemoryMax=`. Sin él, un
  motor con fuga de memoria tumba el dashboard entero.
- **Directorio de trabajo.** La unidad de TradingLab necesita `WorkingDirectory=`:
  Lumibot escribe sus logs relativos al CWD, y bajo systemd el CWD es `/`.
- **Señal de parada.** Lumibot instala su propio manejador de **SIGINT**, no de
  SIGTERM. TradingLab atiende ambas, pero conviene `KillSignal=SIGINT` para no
  depender de ello.
- **Escaneo de disco al importar.** Importar `lumibot.credentials` busca un
  `.env` recorriendo el sistema de archivos. Se apaga con
  `Environment=LUMIBOT_DISABLE_DOTENV=1`.
- **Secretos.** `DASHBOARD_FREQTRADE_USER`, `DASHBOARD_FREQTRADE_PASSWORD`,
  `ALPACA_API_KEY` y `ALPACA_API_SECRET` van en el entorno de la unidad, **nunca
  en la base de datos**: la configuración compartida la puede leer cualquier
  usuario autorizado desde el panel.
- **Exposición.** La documentación de Freqtrade pide explícitamente no exponer
  su API a internet: `listen_ip_address: 127.0.0.1`.
- **Límites de instrumentos.** Freqtrade 15, TradingLab 25. No son arbitrarios:
  cada instrumento cuesta memoria y llamadas en una máquina compartida.

### Arrancar antes de tener credenciales

`tradinglab --db RUTA_DEMO_SEPARADA correr --simulado` opera contra precios
generados con una semilla fija, sin Alpaca y sin credenciales. La ruta explícita
es obligatoria para no reutilizar por accidente `TRADINGLAB_DB` de producción.
Comprueba el contrato local —latidos, operaciones y pantalla—, no la conexión
ni la preparación de Alpaca. Al salir, incluso con `--una-vez`, publica
`estado="detenido"`.

`tradinglab doctor` es **diagnóstico local**, no una prueba de conexión,
compatibilidad del SDK, reconciliación ni preparación para operar. No se
deben introducir credenciales, contactar cuentas o desbloquear Alpaca a
partir de un diagnóstico local satisfactorio.

### Implicación tributaria (Colombia)

Operar a diario configura **habitualidad** ante la DIAN, lo que lleva las
ganancias a renta ordinaria (hasta 39 %) en vez de ganancia ocasional. Aunque
hoy todo sea simulado, si algún día se opera de verdad hará falta el histórico:
**guardar la TRM del día junto a cada operación desde el primer día**.
Reconstruirla después es mucho más caro que registrarla al vuelo.
