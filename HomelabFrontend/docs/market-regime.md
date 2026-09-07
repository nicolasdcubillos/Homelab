# Regimen de mercado

Modulo compartido de analisis macro-financiero. **No ejecuta ordenes, no configura
bots y no depende del permiso de trading.** Vive dentro del dashboard
FastAPI/React, en la misma SQLite y el scheduler central.

La primera instalacion es government-only: fuentes oficiales permitidas pueden
recopilarse sin comprar datos. Esto **no cubre automaticamente el universo
obligatorio** SPX/ES, NDX/NQ, Russell, Dow, DXY, USDJPY, VIX, MOVE, HY/IG OAS y
Treasury 2y/10y, ademas de la macro/politica oficial.

Sin cobertura, frescura, derechos e historia suficientes, los scores son `null`.
`SIN_DATOS` e `INCOMPLETO` no son `NEUTRAL`: neutral requiere evidencia suficiente
pero contradictoria. No se rellena un faltante con 50 ni se redistribuye su peso.
El catalogo indica cada bloqueo y su fuente; los permisos se revisan por uso.
Ver [fuentes y licencias](market-regime-sources.md).

## Lectura y metodo

Tres horizontes independientes:

| Horizonte | Ventana central | Contexto |
|---|---|---|
| SHORT | 12 sesiones (configurable 10-15) | Reaccion/persistencia reciente, barras diarias cerradas. |
| MEDIUM | 8 semanas (6-10) | Ciclo de publicaciones y estructura semanal cerrada. |
| LONG | 12 meses (9-18) | Transmision monetaria y estructura mensual cerrada. |

La historia necesaria para normalizar una variable puede exceder el horizonte de
salida. No se usan RSI, MACD, medias moviles o barras intradia. Un pivote solo
existe despues de cerrarse las barras que lo confirman; no se mira hacia adelante.
Una lectura mensual puede estar vigente durante semanas: la frescura depende de
su cadencia y publicacion, no de una unica edad maxima para todo.

El modelo inicial es **heuristico, no calibrado**. El score 0-100 indica
favorabilidad segun reglas, **no probabilidad de ganar, prediccion de precio ni
rentabilidad esperada**. Una confianza alta en la evidencia tampoco prueba
eficacia estadistica.

| Categoria | SHORT | MEDIUM | LONG |
|---|---:|---:|---:|
| Macro/politica | 30 | 40 | 50 |
| Tasas | 10 | 10 | 10 |
| FX | 10 | 10 | 5 |
| Volatilidad | 15 | 10 | 5 |
| Credito | 15 | 15 | 15 |
| Equity | 15 | 10 | 10 |
| Confirmacion cross-asset | 5 | 5 | 5 |

Cada categoria entrega un valor en [-1,1], razones y observaciones exactas;
contribucion = peso * (valor + 1) / 2. Las siete contribuciones suman el score.
Las reglas y ventanas estan versionadas en la configuracion; un cambio crea una
nueva identidad del modelo y no recalcula silenciosamente los snapshots antiguos.
La identidad incluye el codigo instalado y el calendario. Sus sesiones verificadas
se incorporan desde el recurso versionado, no desde el editor JSON del operador.
Cambiar modelo reinicia las confirmaciones con sus reglas propias.

Macro/politica requieren contexto conjunto de inflacion, empleo/crecimiento y
trayectoria monetaria. No hay regla universal "CPI alto = Risk Off" o "yields
bajan = Risk On". Desinflacion por menor presion de precios y desinflacion con
deterioro de empleo/crecimiento no se interpretan igual. Las hipotesis causales
se identifican como interpretacion, no como hechos probados. Noticias/opiniones
no reemplazan fuentes primarias ni cambian numeros.

Equity y futuros no se cuentan dos veces; las relaciones cross-asset son
interacciones acotadas. NFCI no se vuelve a sumar a sus componentes y no es
un clasificador bursatil probado. VIX y MOVE no se sustituyen por ETF o
volatilidad realizada; sus rangos historicos necesitan suficiente historia.

Bandas orientativas: [0,20) Off fuerte, [20,40) Off, [40,60] Neutral, (60,80] On,
(80,100] On fuerte. El estado confirmado tiene hysteresis y persistencia
independientes del score bruto: transiciones necesitan varias categorias y
nuevas barras elegibles, no recalcular diez veces el mismo dato. El panel expone
drivers, contradicciones, cambios y condiciones que cambiarian la lectura.

## Historia, revisiones y eventos

Se conservan payloads permitidos comprimidos/deduplicados por SHA-256, valores
decimales originales, unidad, periodo economico, fecha observada/publicada,
precision temporal, available_at, ingestion real, vintage y URL. Una revision
inserta otra observacion; no sobrescribe evidencia usada en reportes.

Dos conceptos distintos:

- **OPERACIONAL:** lo que la aplicacion realmente tenia disponible al corte,
  incluyendo ingestion previa. El historial no empieza antes del primer snapshot
  creado por el sistema.
- **RECONSTRUCCION:** estudio historico o recuperacion tardia rotulada. Una
  vintage recuperada hoy necesita prueba de disponibilidad original; ingested_at
  sigue siendo hoy. No se presenta como una emision antigua real.

Una vintage por fecha no implica conocer su hora. Los calendarios de eventos
tambien se versionan: cambiar la fecha futura no modifica lo que se habia
anunciado antes. H.10 de la semana aun no publicado no entra al reporte del
viernes. Historia revisada puede contextualizar hoy, pero no sirve por si sola
para un backtest point-in-time.

UI: 1 semana, 1/3/6/12 meses, con fecha inicial real y huecos visibles. No genera
historia ficticia para rellenar graficas. Los snapshots/reports contienen su
modelo y hash, y no exponen raw ni datos de destinatarios.

## Informes, calendario y ejecucion

El informe comienza con brief de tres horizontes, drivers, mayor riesgo y que
cambiaria la lectura; despues matriz de evidencia y 13 secciones:

1. Semana y cronologia.
2. Macro.
3. Fed.
4. Tasas.
5. Dolar.
6. Volatilidad.
7. Equity.
8. Credito.
9. Cross-asset.
10. Regimen por horizonte.
11. Cambio de regimen.
12. Correccion o deterioro estructural.
13. Proxima semana y riesgos.

Las secciones permanecen aunque falten datos; se dice que no pueden evaluarse.
El informe determinista no necesita LLM. Ninguna redaccion puede modificar el
score, inventar cifras/citas o convertir titulares en datos.

Calendario bursatil versionado `America/New_York`: ultima sesion de la semana
mas 90 minutos. Habitual viernes 17:30 NY; early close 14:30; viernes feriado
puede llevarlo al jueves. Respetar DST y anos verificados; fuera del rango
conocido se bloquea, no se supone lunes-viernes. Los mercados/proveedores no
comparten necesariamente el mismo cierre o release.

El scheduler central tiene un despachador independiente, trabajo/leases
persistentes y un worker acotado. No crear ni activar timers antiguos de
PortfolioWatcher/StockWatcher. API manual encola y devuelve un ID; la pantalla
muestra pendiente/en ejecucion/resultado, no un exito antes de terminar.
Una corrida incompleta conserva evidencia y motivos; no tumba otros modulos.
La recopilacion manual y diaria utiliza un corte **posterior** al HTTP, conservando
`ingested_at` real. Hay una recopilacion diaria y otra entre cierre +60 y +90
minutos, sujetas al presupuesto local; esta ultima prepara el corte semanal.
El informe automatico de corte fijo usa solo evidencia ya persistida: no descarga
despues del corte para intentar completar retroactivamente la semana.
Si hubo caida o ingestion tardia, se abstiene. Una recuperacion de mas de cinco
minutos se etiqueta `RECONSTRUCCION` y no notifica ni avanza transiciones.

La deduplicacion semanal evita crear varios reportes canonicos de la misma
semana. La recuperacion tardia no desplaza el corte ni reescribe el pasado.
Recalcular no cuenta como otra sesion ni reenvia un informe ya creado.
Cada informe conserva los IDs de sus snapshots comparados: revocar derechos de
un antecedente tambien bloquea los derivados de esa comparacion.

## Permisos y entrega

Admin activo tiene acceso efectivo operator; puede conceder viewer/operator a
otros usuarios. `regime_level` es independiente de `trading_level`.
Viewer lee el motor compartido y modifica solo sus preferencias. Operator
puede encolar trabajos y cambiar configuracion versionada (409 si esta
desactualizada). Suspender/revocar acceso impide consultas y cancela pendientes.

Destinos se reutilizan de Ajustes (`NotificationChannel`); las preferencias del
modulo nacen desactivadas. Opt-in esta ligado al destino y version del texto:
cambiar numero/correo exige consentimiento nuevo. No se hereda del opt-in de un
watcher ni de `verified_at`. Nunca hay To masivo o direccion fallback del dueno
de la VM.

Email recibe HTML/texto completos. WhatsApp recibe brief mediante plantilla
apropiada aprobada por Meta, idioma/parametros coincidentes y consentimiento.
No usar texto libre suponiendo abierta la ventana de 24 horas, ni llamar
"utility" a una plantilla financiera sin aprobacion correspondiente.

El extra opcional **`regime-notifications`** instala SDK ACS compatibles con el
paquete del dashboard. Instalar SDK no registra cuentas, no carga secretos de
watchers y no habilita envios. Credenciales via EnvironmentFile propio
`/etc/homelab/market-regime.env`, nombres `DASHBOARD_REGIME_*`; no via API.

Outbox privada y dedupe reporte-usuario-canal, intentos limitados y revalidacion
al enviar. ACEPTADO por el proveedor no implica ENTREGADO al buzon/telefono.
Timeout despues de posible aceptacion queda INCIERTO y no se reintenta a
ciegas. No se promete exactly-once externo. Revocacion, cambio de destino,
consentimiento ausente, clave/SDK ausente o plantilla no aprobada bloquean el
envio. El flag de entregas inicia apagado; ACS no es gratuito.
La version inicial bloquea ademas las notificaciones de datos importados o
restringidos, aunque puedan estar autorizados para analisis/visualizacion local.
No hay conciliacion automatica que convierta `INCIERTO` en entregado ni reenvio
ciego: requiere revision operativa del receipt en el proveedor.

## CLI y operacion

Usar el entrypoint instalado del dashboard con las mismas rutas de datos que el
servicio. Los comandos CLI no envian mensajes:

```text
homelab-dashboard market-regime doctor --json
homelab-dashboard market-regime ingest
homelab-dashboard market-regime snapshot
homelab-dashboard market-regime report --dry-run
homelab-dashboard market-regime report
homelab-dashboard market-regime backtest
homelab-dashboard market-regime import-authorized archivo.json
```

`doctor` no hace HTTP ni migra: exit 0 significa cobertura completa, 2 evidencia
incompleta (normal al iniciar government-only), 1 error operativo. Devuelve
estado de esquema, flags, proxima ejecucion, faltantes y fuentes, nunca claves.
Incluye readiness de cada canal y presencia del SDK sin crear clientes ni hacer
HTTP. La base debe existir y estar migrada.

Importacion autorizada por CLI: JSON con `manifest` y `observations`, maximo
8 MiB/10000 observaciones. El parser estricto esta en
`market_regime/providers/authorized_import.py`: valida unidad/frecuencia del
catalogo, barra cerrada, convencion FX y contrato/metodo de roll en futuros.
No acepta el JSON generico de `Observation` como atajo. Registrar previamente
la evidencia revisada por el responsable de la instalacion con
`market-regime record-license --source <id> --reference <documento> --expires
<ISO-con-zona> --evidence-sha256 <hash-del-documento>`.
El manifiesto requiere `schema_version: "1"`, `provider`, `source_url`, `terms_url`,
`license_id`, `license_evidence_sha256`, `attribution` y `permissions`
(`storage`, `processing`, `shared_display`, `derivatives`).
La licencia exacta/hash/alcance deben coincidir con el registro independiente y
con el propietario canonico de todas las series del archivo. El payload conserva
esa vinculacion: revocarlo impide usar o mostrar su evidencia; otra licencia
generica no lo rehabilita. URLs declaradas no se descargan.
Ese registro **no compra ni concede derechos**: documenta los que el operador
de la instalacion ya tiene. Un usuario viewer/operator de la web no puede
aprobar licencias por si mismo ni cargar URLs arbitrarias al servidor.

El backtest usa todas las vintages elegibles, labels forward maduras por
horizonte y separacion temporal. Sin licencias/vintages/historia/folds suficientes
devuelve HISTORIA_INSUFICIENTE: pasar tests sinteticos no demuestra calibracion.
No promociona un modelo automaticamente ni implementa una estrategia de trading.

Los datos/canales/modelos se conservan en SQLite WAL. El control de disco puede
detener nuevas ingestas del modulo, no borrar silenciosamente historia.
Respaldo consistente con SQLite backup, no copia aislada de un archivo vivo
ignorando WAL. La base comparte usuarios/watchers: nunca restaurarla
automaticamente para revertir solo este modulo.

El presupuesto durable reserva el peor caso de solicitudes HTTP y reintentos,
no solo cuenta llamadas al conector. Limites diarios locales: Treasury 18,
Fed 24, BLS 20, BEA 20, FRED 40 y calendario BEA 4. Son deliberadamente
conservadores y pueden impedir una segunda recopilacion del mismo proveedor.
El estado explica el presupuesto agotado, sin atribuirlo a una cuota oficial.
La lectura operacional selecciona la ultima revision elegible en SQL antes de
materializarla, sin borrar payloads o vintages.

### Activacion y limites de esta entrega

Instalacion no editable con `homelab-dashboard[regime-notifications]`; el
entrypoint del release es
`/opt/services/homelab-dashboard/current/.venv/bin/homelab-dashboard`.
El archivo [market-regime.env.example](../market-regime.env.example) enumera
las variables propias. `DASHBOARD_REGIME_ENABLED=true` habilita el proceso;
un operator debe activar tambien la configuracion persistida desde
**Modelo y operacion** para encolar desde la UI y programar. Mantener
`DASHBOARD_REGIME_DELIVERIES_ENABLED=false` durante el arranque inicial.
CLI `ingest` es una accion local explicita y funciona con automatizacion apagada;
reusa lease/heartbeat, pero nunca despacha outbox.

Conectores probados por HTTP publico: Treasury, Fed, BLS y calendario BEA.
BEA numerico y FRED necesitan claves; Census/DOL permanecen
`NO_CONFIGURADO` (no hay parser operativo validado). H.15/H.4.1 aportan
historia actual limitada; un campo cubierto no significa historia suficiente
para una feature. No se implemento redaccion LLM ni se afirma calibracion.

Smoke aislado del 2026-09-07: 996 observaciones Treasury, 500 Fed, 132 BLS,
76 eventos Fed y 136 BEA; recorrido manual 5,505 segundos en Windows local.
Persistencia, API autenticada tras nuevo lifecycle e informe de 13 secciones
comprobados con outbox vacia. No es una medicion de RSS de la VM ni validacion
estadistica del modelo; la comprobacion Linux/preflight corresponde al despliegue.

Despliegue, releases aislados y precauciones despues de una migracion:
[deployment.md](deployment.md). No ampliar la VM ni arrancar bots para instalar
este modulo.
