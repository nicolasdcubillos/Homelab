## Arquitectura de PortfolioWatcher

```
                          ┌─────────────────────────┐
                          │   systemd timers (VM)   │
                          │  daily 2x/día, weekly    │
                          │  cada analysis_interval  │
                          └───────────┬─────────────┘
                                      │
                     ┌────────────────┴────────────────┐
                     ▼                                 ▼
            portfoliowatcher daily             portfoliowatcher weekly
                     │                                 │
   ┌─────────────────┼─────────────────┐               │
   ▼                 ▼                 ▼               ▼
prices.py     news_ingestion.py   state.py (SQLite)   prices.py + state.py
(yfinance)    (Google News RSS +  dedupe / historial   snapshots + historial
              SEC EDGAR)                                       │
   │                 │                                         ▼
   │                 ▼                                 portfolio_summary_text
   │        ┌──────────────────┐                        (holdings, sectores,
   │        │  llm_pipeline.py │                         concentración)
   │        │ ───────────────  │                                │
   │        │ Tier 1: Triaje   │ (modelo barato, ej.              ▼
   │        │  descarta ruido  │  gpt-4.1-mini)          llm_pipeline.py
   │        │        │         │                        weekly_report()
   │        │        ▼         │                        (modelo capaz,
   │        │ Tier 2: Análisis │ (modelo capaz, ej.       ej. gpt-5-mini)
   │        │  riesgo/oport./  │  gpt-5-mini)                    │
   │        │  ruido + severi- │                                 │
   │        │  dad + tesis     │                                 │
   │        └────────┬─────────┘                                 │
   │                 │ persiste prompt/response en state.py       │
   │                 ▼          (tabla llm_signals, backtesting) │
   │        reports.py: build_daily_report()             reports.py:
   │        (2 secciones: riesgo / oportunidad)           build_weekly_report()
   │                 │                                             │
   └─────────────────┴──────────────────┬──────────────────────────┘
                                         ▼
                              notifier.py (Notifier ABC)
               ┌─────────────────────┬───────────────────┐
               ▼                     ▼                   ▼
     WhatsAppNotifier (ACS)  EmailNotifier (ACS)   TelegramNotifier
               └─────────────────────┴───────────────────┘
                                     ▼
                         Usuario recibe el mensaje
                     (nunca se ejecuta ninguna orden)
```

### Flujo diario
1. `news_ingestion.py` trae titulares (RSS Google News) y filings SEC EDGAR
   (8-K/10-Q/10-K) de las últimas 24h por cada ticker del portafolio.
2. `state.py` filtra lo ya visto (dedupe por `guid`).
3. `llm_pipeline.py` corre el triaje barato (deployment `openai_triage_deployment_name`,
   ej. `gpt-4.1-mini`) sobre cada item nuevo; solo lo que sobrevive pasa al
   análisis (deployment `openai_analysis_deployment_name`, ej. `gpt-5-mini`), que
   clasifica en `riesgo | oportunidad | ruido`, asigna severidad y redacta una
   tesis corta. Cada prompt/response se guarda en `llm_signals` (SQLite) para
   backtesting.
4. `reports.py` arma el mensaje de 2 secciones y `notifier.py` lo envía por
   los canales de `PORTFOLIOWATCHER_NOTIFIERS` (WhatsApp, correo o Telegram).
   El destino se resuelve con la precedencia `--notify-to` > variables del
   proceso (`WHATSAPP_TO`/`EMAIL_TO`) > `.env` — ver el contrato al inicio de
   `notifier.py`.

### Flujo semanal (cada `analysis_interval_days`)
1. `prices.py` trae precio actual, cierre anterior y sector por ticker.
2. Los snapshots se guardan en `state.py` para poder calcular variaciones
   entre corridas.
3. `reports.portfolio_summary_text` arma el resumen (holdings, pesos,
   concentración sectorial) que se pasa al modelo de análisis para redactar
   el informe ejecutivo semanal.
4. Se envía por el mismo canal de notificación.

### Nota sobre los modelos usados en producción
Los nombres de deployment (`openai_triage_deployment_name` /
`openai_analysis_deployment_name`, Terraform en `infra/`) están desacoplados
del modelo real que apuntan (`openai_triage_model` /
`openai_analysis_model`), justamente para poder cambiarlos sin renombrar
recursos. En este despliegue se usan `gpt-4.1-mini` (triaje) y `gpt-5-mini`
(análisis) porque la suscripción de Azure no tenía cupo (quota) para la
familia `gpt-5.x`/`gpt-4o`/`o1`-`o3` en `eastus` — pedir más cupo requiere un
ticket de soporte a Azure, no es algo que Terraform pueda resolver. `gpt-5-mini`
es un modelo de razonamiento: **no acepta `temperature` distinto del default
(1)**, por eso `llm_pipeline.py` no manda ese parámetro en las llamadas.

### Servicios compartidos en la misma VM
Esta VM (`homelab-vm`, nombres genéricos vía `project_name`) también aloja
[HomelabDashboard](https://github.com/nicolasdcubillos/HomelabDashboard): un
panel web (Caddy + FastAPI, HTTPS con Basic Auth) para ver/editar
`config/portfolio.yaml` y disparar `daily`/`weekly`/`analyze` manualmente
desde el celular sin SSH. La NSG (`infra/main.tf`) abre los puertos 80/443
para ese dashboard (regla `AllowWebDashboard`, variable
`allowed_web_source_address`) además del 22 para SSH. Ver el repo de
HomelabDashboard (`docs/deployment.md`) para el runbook completo.

### Principio de diseño no negociable
En ningún punto del pipeline se genera ni se permite generar una instrucción
de compra/venta ejecutable. El system prompt de ambos niveles del LLM lo deja
explícito, y `reports.py` añade el mismo disclaimer a todo mensaje enviado.
