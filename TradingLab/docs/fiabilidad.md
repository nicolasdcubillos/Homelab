# Fiabilidad y limites operativos

## Estado de la integracion

Alpaca Paper **no esta habilitado**. `MotorAlpaca.ejecutar`, `comprar` y `vender`
rechazan la ejecucion antes de crear sesiones u ordenes. Instalar Lumibot, poner
claves o marcar `enabled=true` no elimina el bloqueo. No hay modo de dinero real.

El adaptador anterior podia contabilizar `partial_fill` como toda la cantidad
solicitada y reintentar despues de un timeout con una orden todavia activa.
Tampoco conciliaba posiciones de la cuenta con SQLite. Se retiro ese ejecutor,
incluido el filtrado silencioso de argumentos y la reutilizacion del broker
cerrado; no se presenta como una integracion Alpaca terminada.

Se reviso la fuente publica de **Lumibot v4.5.88**:
[Trader.run_all](https://github.com/Lumiwealth/lumibot/blob/v4.5.88/lumibot/traders/trader.py)
admite `run_once`; en
[StrategyExecutor](https://github.com/Lumiwealth/lumibot/blob/v4.5.88/lumibot/strategies/strategy_executor.py)
el mercado cerrado puede omitir la iteracion. No es correcto afirmar que siempre
espera a la apertura. Sin embargo, hay sincronizacion de red, espera programada,
hooks de nube y cierre del broker en `gracefully_exit`: no garantiza el limite de
tiempo, aislamiento ni recuperacion durable que necesita este supervisor.

Para habilitar paper falta una implementacion conjunta, no un flag:

- Diario durable de intenciones antes del envio, con `client_order_id` idempotente.
- Recuperar por ID ante envio incierto, sin crear otra orden; cantidades llenadas
  acumuladas y precios de ejecucion reales, nunca la cantidad solicitada por defecto.
- Cancelacion confirmada, tratamiento de llenados durante la cancelacion y ordenes
  abiertas al reiniciar. Un timeout o una respuesta perdida no es un rechazo.
- Conciliacion de cuenta, posiciones y ordenes contra el diario, asociada a una
  identidad de cuenta paper. Diferencias/manuales/short deben bloquear y alertar.
- Sesion con operaciones acotadas, control de parada durante red, sin hooks cloud
  ajenos, ni reutilizacion de conexiones que el SDK ya cerro.

No se consultaron cuentas ni se enviaron ordenes durante esta revision. Los tests
de SDK falso demuestran la barrera y el rechazo de datos invalidos, no que el flujo
de ejecucion y conciliacion pendiente este implementado.

## Supervisor y contrato publicado

`estado_motor` conserva las columnas anteriores y agrega columnas anulables para
migrar bases existentes sin atribuirles un estado inventado:

| Columna | Contrato |
| --- | --- |
| `estado` | `pausado`, `operando`, `esperando`, `error`, `bloqueado`, `detenido` |
| `modo` | `simulado` (demo local) o `alpaca_paper` (sin ejecucion habilitada) |
| `config_version` | Ultima version aceptada en pausa o usada por un ciclo; nula si ninguna |

`enabled` es intencion, no prueba de que el proceso opera. Errores y bloqueo no
promueven una version nueva. La salida, incluido `--una-vez`, publica `detenido`.
Al fallar lectura se libera el motor, y un nuevo timeframe reconstruye el motor.
Una base cuyo conteo no puede leerse no publica cero posiciones como fallback.

El latido y la evaluacion tienen distinta cadencia, pero **no son concurrentes**.
El camino habilitado es el demo local, con SQLite y TRM opcional con timeout;
no existe una garantia general de latido mientras una dependencia esta bloqueada.
El camino paper no consulta TRM ni carga SDK. SIGTERM interrumpe la espera entre
vueltas; antes de cada orden demo se relee configuracion y se comprueba parada.

## Persistencia demo y contabilidad

`identidad_motor` vincula una base a un modo. No se permite mezclar demo/paper ni
adoptar bases antiguas con operaciones sin origen verificable; esas bases se
conservan para lectura y revision manual. No se etiquetan automaticamente como
Alpaca ni se venden posiciones supuestas.

`--simulado` exige `--db` explicita. Utilizar siempre una base demo separada;
no usar la ruta que consume el dashboard de produccion. En `identidad_motor`
se fija el capital inicial al primer ciclo demo. El saldo se reconstruye desde
el diario: capital inicial + PnL cerrado - importes y costos de posiciones abiertas.
Cambiar capital en el panel cambia el presupuesto, no deposita dinero ficticio.
`estado_simulado` conserva las series generadas y su avance.

La transaccion SQLite `BEGIN IMMEDIATE` abarca restauracion, ciclo, diario y
avance de precios. Dos ciclos no leen simultaneamente un saldo anterior; un
fallo revierte el ciclo y el siguiente restaura desde datos confirmados. Esto es
valido porque **no hay efectos externos en demo**, no soluciona atomicidad Alpaca.
El rollback tambien restaura los precios en memoria si aun no existia la primera
instantanea. Saldo, costos y PnL demo usan precision monetaria de seis decimales:
un residuo flotante al agotar el efectivo no bloquea el reinicio, pero un deficit
real se rechaza.

El simulador rechaza short, margen, cantidades fraccionarias/invalidas y precios
no finitos. El deslizamiento se cobra en costos, no tambien en el precio. Las
compras respetan efectivo y presupuesto incluidos costos. Las salidas parciales
no se registran como cierres totales; el ciclo detiene esa contabilidad.

## Riesgo y limites honestos

Pausar o detener **no liquida** ni mantiene stops vigilados. Los stops/take-profit
demo se evaluan por ciclo y pueden saltarse precios entre revisiones; no son
ordenes protectoras alojadas en un broker. El freno diario cuenta solo PnL cerrado,
no limita perdidas no realizadas ni garantiza una perdida maxima. No se reabre
el ticker que acaba de cerrarse en la misma evaluacion.

Quitar todos los tickers con el motor habilitado sigue revisando las posiciones
demo existentes para cerrarlas. Con mercado cerrado no se encolan entradas ni
salidas. Un error al valorar/cerrar bloquea entradas nuevas durante ese ciclo.
La rentabilidad demo no es rentabilidad Alpaca ni una prediccion de ganancias.

`doctor` es diagnostico local, sin red: no prueba credenciales, cuenta, conexion,
datos ni horario. Devuelve 1 explicando el bloqueo Alpaca. El servicio pausado no
necesita claves ni el extra pesado `alpaca`; el nucleo soporta Python 3.10+.
