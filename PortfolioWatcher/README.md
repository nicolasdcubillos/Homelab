# PortfolioWatcher

Sistema de análisis de portafolio de acciones **para inversión a largo plazo**,
con dos features:

1. **Análisis completo del portafolio** cada `analysis_interval_days` días
   (default 7): correlación/concentración sectorial, fundamentales recientes
   (10-Q/10-K/8-K vía SEC EDGAR) e informe ejecutivo.
2. **Suscripción diaria** (2x/día, mañana pre-apertura y tarde post-cierre,
   hora NY) con dos secciones: **alertas de riesgo** y **recomendaciones
   fuertes**, generadas por un pipeline LLM de dos niveles sobre Azure OpenAI.

> ⚠️ **Disclaimer**: PortfolioWatcher **nunca** recomienda comprar/vender de
> forma directa ni ejecuta órdenes de ningún tipo. Solo produce señales
> informativas (riesgo/oportunidad) con contexto para que un humano decida.
> No es asesoría financiera.

## Arquitectura

- **Runtime**: Python 3.11 en una Azure VM (Ubuntu B2s), disparado por
  `cron`/`systemd timers` — sin Container Apps ni GitHub Actions como
  scheduler.
- **Precios**: [`yfinance`](https://github.com/ranaroussi/yfinance) (gratis).
- **Noticias**: RSS de Google News por ticker (búsqueda acotada, sin API key)
  + SEC EDGAR `submissions` API (gratis, requiere solo un `User-Agent`
  descriptivo).
  > Nota histórica: originalmente se usaba el RSS clásico de Yahoo Finance
  > (`feeds.finance.yahoo.com/rss/2.0/headline`), pero Yahoo lo deprecó y
  > devuelve 404 para todos los tickers — se reemplazó por Google News RSS
  > (`news.google.com/rss/search`), que sigue vigente y gratis.
- **LLM (Azure OpenAI / Azure AI Foundry), pipeline de 2 niveles**:
  - Triaje barato (`gpt-5-6-luna` por defecto) descarta ruido.
  - Análisis (`gpt-5-6-sol` por defecto) clasifica en `riesgo | oportunidad |
    ruido`, asigna severidad y redacta una tesis corta.
  - Todo prompt/response se guarda en SQLite para backtesting futuro
    (`outcome_30d`/`outcome_90d` quedan vacíos para completarse manualmente).
- **Estado**: SQLite local (`data/portfoliowatcher.db`) — dedupe de noticias,
  historial de señales, snapshots de precio.
- **Notificación**: WhatsApp y correo vía Azure Communication Services (mismo
  recurso ACS y mismo patrón que el proyecto hermano StockWatcher), con una
  interfaz `Notifier` que también admite Telegram como alternativa. El canal
  se elige con `PORTFOLIOWATCHER_NOTIFIERS` (`whatsapp`, `email`, `telegram`,
  `console`) y el destino puede fijarse por invocación con `--notify-to`.

Ver `docs/architecture.md` para un diagrama del flujo completo.

## Setup local

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,azure]"
cp .env.example .env   # completa tus credenciales (ver abajo)
```

### Actualizar el portafolio

`config/portfolio.yaml` contiene tus posiciones reales y **no se versiona**
(está en `.gitignore`) para no exponer cantidades ni precios de compra en el
repo. Cópialo desde la plantilla de ejemplo la primera vez:

```bash
cp config/portfolio.example.yaml config/portfolio.yaml
```

Luego edítalo con tus datos: cada holding necesita `ticker`, `quantity`
(cantidad neta = compras - ventas) y `avg_cost` (costo promedio ponderado).
Posiciones cerradas (cantidad neta ~0) van en `closed_positions` solo como
referencia — no generan señales. Si despliegas en la VM, copia tu
`portfolio.yaml` real por separado (scp, no por git) — ver `scripts/deploy.sh`.

### Variables de entorno (`.env`)

Ver comentarios en `.env.example`. Resumen:

- `AZURE_OPENAI_*`: endpoint, key, y nombres de los 2 deployments (triaje y
  análisis).
- `ACS_CONNECTION_STRING`, `ACS_CHANNEL_REGISTRATION_ID`, `WHATSAPP_TO`, etc.:
  notificación WhatsApp.
- `ACS_EMAIL_SENDER`, `EMAIL_TO`, `EMAIL_SUBJECT`: notificación por correo
  (mismo recurso ACS que WhatsApp, capacidad Email enlazada aparte).
- `PORTFOLIOWATCHER_NOTIFIERS`: canales a usar, separados por coma.
- `SEC_EDGAR_USER_AGENT`: identifícate ante SEC EDGAR (política de acceso
  justo — ver https://www.sec.gov/os/webmaster-faq#developers).
- `PORTFOLIOWATCHER_STATE_PATH`: ruta del archivo SQLite.

### Ejecutar localmente (sin enviar nada real)

```bash
portfoliowatcher daily --dry-run
portfoliowatcher weekly --dry-run --force
```

`--dry-run` imprime el mensaje en consola en vez de enviarlo por WhatsApp.
`--force` en `weekly` ignora el chequeo de intervalo (`analysis_interval_days`).
`analyze --interval-days N` corre el análisis completo forzando otro intervalo.

### Destino de la notificación

El destino se resuelve con esta precedencia, de mayor a menor:

1. `--notify-to` (explícito, por invocación):
   ```bash
   portfoliowatcher --notify-to "usuario@example.com" daily
   ```
2. Variables del entorno del proceso (`WHATSAPP_TO` / `EMAIL_TO`).
3. Lo que traiga el archivo `.env`.

Que el punto 2 gane sobre el 3 es lo que permite invocar PortfolioWatcher una
vez por usuario (inyectando su destino por `env=`) compartiendo un mismo `.env`
con solo los secretos comunes. Por eso `cli.py` usa `load_dotenv()` con su
`override=False` por defecto: **cambiarlo a `override=True` redirigiría las
alertas de todos los usuarios al destino del archivo compartido.** El contrato
está documentado al inicio de `notifier.py` y fijado por `tests/test_cli.py`.

Un `config/portfolio.yaml` sin holdings no es un error: se registra una
advertencia y la corrida termina limpiamente sin analizar nada.

## Tests

```bash
pytest
ruff check .
```

Todos los tests usan mocks para Azure OpenAI, Azure Communication Services y
SEC EDGAR — no requieren credenciales ni acceso de red.

## Despliegue en Azure (VM + cron)

La infraestructura vive en `infra/` (Terraform) y usa un nombre de proyecto
**genérico** (`homelab` por defecto, variable `project_name`) porque la
misma VM está pensada para alojar más servicios personales a futuro, no solo
PortfolioWatcher. El código de la app en la VM vive en su propio
subdirectorio: `/opt/services/portfoliowatcher/`.

1. Autentícate con Azure: `az login`.
2. Revisa/edita `infra/terraform.tfvars.example` → cópialo a
   `infra/terraform.tfvars` con tus valores (tu IP pública para el NSG, etc.).
3. Aplica la infraestructura:
   ```bash
   cd infra
   terraform init
   terraform plan
   terraform apply
   ```
   Esto crea: resource group, VM Ubuntu B2s + disco + IP pública (con DNS
   label gratuito `*.cloudapp.azure.com`, ver output `vm_fqdn`) + NSG
   (puerto 22 restringido a tu IP; puertos 80/443 abiertos para el reverse
   proxy del dashboard compartido, ver más abajo), una cuenta de Azure
   OpenAI con los 2 deployments (triaje/análisis — en este despliegue
   `gpt-4.1-mini`/`gpt-5-mini` por límites de cupo, ver
   `docs/architecture.md`), y un recurso de Communication Services con canal
   WhatsApp (la conexión con Meta/WhatsApp Manager requiere un paso manual
   fuera de Terraform — ver `docs/architecture.md`).
4. Copia el código y arranca los timers:
   ```bash
   ./scripts/bootstrap_vm.sh <ip-de-la-vm>   # instala python3.11 y deps en la VM
   ./scripts/deploy.sh <ip-de-la-vm>         # sincroniza código + instala systemd timers
   ```
5. Los timers `portfoliowatcher-daily.timer` (2x/día) y
   `portfoliowatcher-weekly.timer` (cada N días) quedan activos vía
   `systemd`; revisa logs con `journalctl -u portfoliowatcher-daily.service`.
6. (Opcional pero recomendado) Despliega
   [HomelabDashboard](https://github.com/nicolasdcubillos/HomelabDashboard)
   en la misma VM para poder editar `config/portfolio.yaml` y disparar
   `daily`/`weekly`/`analyze` manualmente desde el celular, sin SSH — es el
   consumidor de las reglas NSG 80/443 y del `vm_fqdn` mencionados arriba.
   Ver `docs/deployment.md` en ese repo para el runbook completo.

**Este entorno de desarrollo no tiene credenciales de Azure configuradas** —
`terraform apply` debe correrlo el usuario manualmente después de `az login`.

## Backtesting de señales

Cada señal generada por el pipeline LLM queda en la tabla `llm_signals` de
`data/portfoliowatcher.db`, con `outcome_30d`/`outcome_90d` vacíos. Puedes
completarlos manualmente (o escribir un script de seguimiento futuro) para
medir qué tan acertadas fueron las señales de riesgo/oportunidad.
