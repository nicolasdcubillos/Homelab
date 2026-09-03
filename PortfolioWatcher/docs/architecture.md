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
   │        │ Tier 1: Triaje   │ (gpt-5-6-luna, barato)          ▼
   │        │  descarta ruido  │                        llm_pipeline.py
   │        │        │         │                        weekly_report()
   │        │        ▼         │                        (gpt-5-6-sol)
   │        │ Tier 2: Análisis │ (gpt-5-6-sol, capaz)            │
   │        │  riesgo/oport./  │                                 │
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
                          ┌──────────────┴───────────────┐
                          ▼                               ▼
                 WhatsAppNotifier (ACS)           TelegramNotifier (stub)
                          │
                          ▼
                 Usuario recibe el mensaje
             (nunca se ejecuta ninguna orden)
```

### Flujo diario
1. `news_ingestion.py` trae titulares (RSS Google News) y filings SEC EDGAR
   (8-K/10-Q/10-K) de las últimas 24h por cada ticker del portafolio.
2. `state.py` filtra lo ya visto (dedupe por `guid`).
3. `llm_pipeline.py` corre el triaje barato (Luna) sobre cada item nuevo; solo
   lo que sobrevive pasa al análisis (Sol), que clasifica en
   `riesgo | oportunidad | ruido`, asigna severidad y redacta una tesis corta.
   Cada prompt/response se guarda en `llm_signals` (SQLite) para backtesting.
4. `reports.py` arma el mensaje de 2 secciones y `notifier.py` lo envía por
   WhatsApp (o Telegram cuando se implemente).

### Flujo semanal (cada `analysis_interval_days`)
1. `prices.py` trae precio actual, cierre anterior y sector por ticker.
2. Los snapshots se guardan en `state.py` para poder calcular variaciones
   entre corridas.
3. `reports.portfolio_summary_text` arma el resumen (holdings, pesos,
   concentración sectorial) que se pasa al modelo de análisis (Sol) para
   redactar el informe ejecutivo semanal.
4. Se envía por el mismo canal de notificación.

### Principio de diseño no negociable
En ningún punto del pipeline se genera ni se permite generar una instrucción
de compra/venta ejecutable. El system prompt de ambos niveles del LLM lo deja
explícito, y `reports.py` añade el mismo disclaimer a todo mensaje enviado.
