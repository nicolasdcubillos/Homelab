# Fuentes y derechos del regimen de mercado

Revision documental: **2026-09-07**. Una pagina visible, un endpoint gratuito
o la posibilidad de guardar un archivo **no conceden licencia multiusuario**.
Separar derechos de almacenamiento, procesamiento, visualizacion, derivados y
envio externo. Los datos cerrados estan bloqueados por defecto, no sustituidos
por proxies.

## Datos oficiales

| Fuente | Acceso y disponibilidad | Condicion temporal y operativa |
|---|---|---|
| [Treasury XML](https://home.treasury.gov/treasury-daily-interest-rate-xml-feed) | GET publico sin clave; campos `BC_2YEAR`, `BC_10YEAR`, `NEW_DATE`; consultas por mes/ano. Acceso observado sin cargo. | Curva par nominal diaria, no yield intradia. `NEW_DATE` a medianoche y el `updated` del feed NO prueban hora original de publicacion. No usar historico consolidado como vintage pasada. |
| [Avisos Treasury XML](https://home.treasury.gov/developer-notice-xml-changes) | Documenta cambios de formato/vencimientos y retirada del host antiguo. | Parsear nombres, no posiciones de columnas. No se encontro cuota/SLA garantizado: hay limites locales. |
| [Fed H.15](https://www.federalreserve.gov/releases/h15/) | Serie de tasas, incluido fed funds efectivo; normalmente dias habiles 16:15, salvo feriados/cierre del Board. XML oficial enlazado en el release. | Fecha de observacion distinta de fecha de release; promedios mensuales distintos de cierre diario. EFFR no es el rango objetivo ni expectativa de futuros. |
| [Fed H.10](https://www.federalreserve.gov/releases/h10/about.htm) | USDJPY en yenes por dolar, referencia del mediodia de Nueva York, NO cierre FX. Publicacion lunes 16:15 con la semana laboral anterior, siguiente dia habil si feriado federal. | Los releases fechados pasados no se revisan; el historico consolidado si puede actualizarse. El viernes no se conoce la semana que el Board publicara el lunes siguiente. |
| [Historico JPY](https://www.federalreserve.gov/releases/h10/hist/dat00_ja.htm) | Descarga oficial sin clave. | La antiguedad debe evaluarse segun el lag H.10; broad dollar no sustituye DXY. |
| [Fed H.4.1](https://www.federalreserve.gov/releases/h41/) | Balance, normalmente jueves 16:30. Desglosa activos, reservas, TGA y operaciones. | Saldo del miercoles y promedio semanal son magnitudes distintas. Un aumento del balance NO equivale automaticamente a QE; contrastar componentes y directivas. |
| [FOMC calendario](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm) | Reuniones, declaraciones, minutas y SEP enlazados por separado. | Guardar fecha de observacion del calendario: puede cambiar. Minutas normalmente tres semanas despues de la reunion. No retrofechar su disponibilidad a la reunion. |
| [FOMC archivo](https://www.federalreserve.gov/monetarypolicy/fomc_historical.htm) | Documentos oficiales historicos. | Un documento interno publicado anos despues no estaba disponible en la fecha de su contenido. Dot plot es proyeccion, no probabilidad de mercado. |
| [BLS API](https://www.bls.gov/developers/api_technical.htm) | Registro gratuito opcional; limites superiores para v2 registrada. | Paginas FAQ/v2/calendarios respondieron 403 durante investigacion. Los numeros 500 consultas/dia, 50 series y 20 anos son informacion oficial indexada, **no revalidada por lectura directa**. No interpretar el 403 como cuota consumida. |
| [BEA API, guia PDF](https://apps.bea.gov/api/_pdf/bea_web_service_api_user_guide.pdf) | Clave gratuita; 100 consultas/min, 100 MB/min, 30 errores/min segun guia leida localmente. | No son 1000 consultas/dia. Validar errores del JSON aun con HTTP 200; no request `ALL` ilimitado. |
| [BEA calendario](https://www.bea.gov/news/schedule/full) | JSON publico enlazado por BEA: [release_dates.json](https://apps.bea.gov/API/signup/release_dates.json), sin clave. Hay publicaciones a 08:30 y a 10:00. | No imponer hora universal. Guardar revisiones y aplazamientos. Una fecha programada, incluso pasada, no demuestra que se publico. |
| [BEA archivo](https://www.bea.gov/news/archive) y [citas](https://www.bea.gov/help/guidelines-for-citing-bea) | Releases originales y pautas de atribucion. | Interactive Data contiene ultima revision, no identifica por si solo la vintage. La discontinuidad de anexos PIO en 2026 impide asumir que cada enlace Excel/PDF historico permanece. |
| [FRED/ALFRED realtime](https://fred.stlouisfed.org/docs/api/fred/realtime_period.html) | Clave para API, catalogo de derechos por serie. | `realtime_start/end` por defecto = hoy. Pedirlo sin fechas NO es point-in-time. Fecha de vintage sin hora requiere disponibilidad conservadora; guardar ingested_at real aunque se recupere hoy. |
| [DOL claims](https://oui.doleta.gov/unemploy/claims.asp) | Publicaciones oficiales semanales, confirmador de empleo. | Sin acceso/parseo validado, informar falta de cobertura; no completar con cero. |
| [Census indicadores](https://www.census.gov/economic-indicators/) | Retail y bienes duraderos como confirmadores de crecimiento. | Conservar ajustes estacionales, unidades y revisiones; no mezclar ventas nominales con crecimiento real. |

El [aviso del Federal Reserve Board](https://www.federalreserve.gov/disclaimer.htm)
permite copiar/distribuir su informacion salvo indicacion contraria, pidiendo
atribucion; **exceptua materiales de terceros**. No extender automaticamente ese
permiso a Chicago Fed, NY Fed, propietarios de indices o cualquier serie en FRED.
La investigacion comprobo acceso sin clave a Treasury; no una licencia especifica
de toda su web o de todos sus enlaces.

El [aviso de continuidad del DDP](https://www.federalreserve.gov/data/data-download-fred-information.htm)
anuncia retirada de "Build Your Package" la semana del 9 de noviembre de 2026.
Los XML historicos seguiran enlazados desde releases. Evitar una dependencia
nueva de `Choose.aspx` o paquetes personalizados.

## Datos de mercado: bloqueados sin permiso verificado

| Familia | Fuente/documento primario | Decision |
|---|---|---|
| HY OAS | [BAMLH0A0HYM2](https://fred.stlouisfed.org/series/BAMLH0A0HYM2) | FRED indica ventana de 3 anos desde abril 2026. ICE restringe entrega a terceros sin permiso escrito. Guardar desde hoy no autoriza publicar datos ni derivados. |
| IG OAS | [ICE indices de renta fija](https://www.ice.com/fixed-income-data-services/index-solutions/fixed-income-indices) | Permisos independientes; no extender derechos de HY ni de otro distribuidor. |
| DXY | [Catalogo ICE](https://developer.ice.com/fixed-income-data-services/catalog/ice-data-indices-currency-indices) | Oferta RT/delayed/EOD/historica por API/files/feed; catalogo no equivale a API gratuita. |
| MOVE | [Catalogo ICE](https://developer.ice.com/fixed-income-data-services/catalog/ice-data-indices-move-index) | No sustituir por volatilidad realizada o un ETF. |
| ICE derechos | [Terminos](https://www.ice.com/privacy-security-center/terms-of-use) | Revisar almacenamiento, extraccion, display/no-display y derivados. Precio especifico no confirmado. |
| Nasdaq/NDX | [DN2024-5](https://www.nasdaqtrader.com/TraderNews.aspx?id=DN2024-5), [DN2026-5](https://www.nasdaqtrader.com/TraderNews.aspx?id=DN2026-5) | Redistribucion requiere aprobacion; EOD/historicos tienen licencias. Desde 1-9-2026 GIDS Delayed no se ofrece a nuevos clientes. |
| Russell | [Atribucion FTSE Russell](https://www.lseg.com/en/ftse-russell/index-resources/attribution), [terminos LSEG](https://www.lseg.com/en/policies/website-terms-of-use) | Permiso web personal/no profesional no habilita servidor multiusuario. |
| VIX | [Historico Cboe](https://www.cboe.com/tradable-products/vix/vix-historical-data), [licencias](https://www.cboe.com/market_data_services/document_library/) | Hay enlaces diarios publicos; no se acredito autorizacion raw/derivados para esta app. |
| SPX y Dow | [S&P data licensing](https://www.spglobal.com/spdji/en/landing/data-licensing/) | Consulta devolvio 403; contrato y precio no verificados. No aprobar mediante una cotizacion visible. |
| ES/NQ/Fed Funds futures | [CME licensing](https://www.cmegroup.com/market-data/distributor/licensing.html), [derived data](https://www.cmegroup.com/market-data/browse-data/derived-data.html) | Paginas respondieron timeout durante investigacion. No suponer cobertura ni derivados gratis. FedWatch publico no demuestra API gratuita autorizada. |
| ETF/FX via Alpha Vantage | [Terminos PDF](https://www.alphavantage.co/terms_of_service/) | Licencia personal no demuestra permiso multiusuario. ETF no equivale al indice. |

ISM, S&P PMI, ADP, Conference Board y Michigan permanecen fuera de la ingestion
automatica sin condiciones verificadas. Para noticias financieras se usan
referencias/enlaces permitidos: ninguna suscripcion nueva, scraping de paywall
o copia de articulos. No se contrataron proveedores ni se crearon cuentas.

Estado ejecutable v1: Treasury/Fed/BLS/calendario BEA tienen ingestion real.
BEA numerico y FRED tienen adaptadores condicionados a claves; Census/DOL
quedan explicitamente no configurados. Los feeds consolidados sin fecha
original de publicacion conservan `published_at=null`, disponibilidad observada
e ingestion real. No se promueve ese historico revisado a vintage point-in-time.

### NFCI y FCI-G no son validacion bursatil

[NFCI/ANFCI](https://www.chicagofed.org/research/data/nfci/about) normaliza 105
indicadores y se revisa. Valores positivos indican condiciones relativamente
restrictivas; no prueba retorno futuro de equities. Los
[terminos Chicago Fed](https://www.chicagofed.org/utilities/legal-notices)
no permiten presumir redistribucion o derivados de esta aplicacion; NFCI queda
restringido, incluso si se obtiene mediante FRED.

[FCI-G](https://www.federalreserve.gov/econres/notes/feds-notes/a-new-index-to-measure-us-financial-conditions-20230630.html)
relaciona siete variables con impulso al PIB del siguiente ano, no retornos
bursatiles. Su interpretacion de movimientos como exogenos es una aproximacion.
La publicacion del agregado no concede derechos sobre todos sus inputs
comerciales. Ninguno se suma otra vez al score junto a yields/VIX/credito:
seria doble conteo.

## Calendario y mensajeria

[NYSE horarios](https://www.nyse.com/trade/hours-calendars) y el
[comunicado 2026-2028](https://ir.theice.com/press/news-details/2025/NYSE-Group-Announces-2026-2027-and-2028-Holiday-and-Early-Closings-Calendar/default.aspx)
son la referencia de sesiones. Regular: 09:30-16:00 ET; early close de acciones:
13:00 ET. **2026-07-02 y 2027-12-23 no son cierres tempranos**, y 2027-12-31
no es feriado observado por Ano Nuevo 2028. Usar `America/New_York`, no UTC-5
fijo; [NIST explica DST](https://www.nist.gov/pml/time-and-frequency-division/popular-links/daylight-saving-time-dst).

Ultima sesion de la semana +90 minutos es una **decision del producto**, no una
regla NYSE. Si el viernes es feriado puede ejecutarse el jueves. El margen no
garantiza que H.4.1 u otras fuentes hayan publicado: la disponibilidad de cada
dato sigue mandando.

[Advanced Messaging es GA](https://azure.microsoft.com/en-us/blog/microsoft-cost-management-updates-june-2024/);
GA no significa gratuito. Los
[templates WhatsApp](https://learn.microsoft.com/en-us/azure/communication-services/concepts/advanced-messaging/whatsapp/template-messages)
requieren opt-in y aprobacion apropiada para iniciar un reporte semanal; no
suponer abierta una ventana de 24 horas. No reutilizar una plantilla de stock
para contenido financiero sin verificar aprobacion/categoria.

[Precio WhatsApp ACS](https://learn.microsoft.com/en-us/azure/communication-services/concepts/advanced-messaging/whatsapp/pricing):
componente ACS publicado de USD 0.005 por mensaje mas tarifas Meta aplicables;
desde julio 2025 Meta cobra por template, no por conversacion. El total depende
del destino/categoria. [Email](https://learn.microsoft.com/en-us/azure/communication-services/concepts/email-pricing)
es pay-as-you-go por destinatario y volumen. No hay cotizacion garantizada de
esta instalacion: los envios del modulo nacen deshabilitados.
