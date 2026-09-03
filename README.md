# Homelab

Monorepo de todo lo que corre en `homelab-vm` (Azure, Ubuntu, `Standard_B2s`,
eastus, resource group `HOMELAB-RG`). Antes eran 3 repos separados
(`StockWatcher`, `PortfolioWatcher`, `HomelabDashboard`); se fusionaron aquí
—conservando el historial de commits de cada uno vía `git filter-repo`— para
poder gestionar infraestructura, CI/CD y documentación desde un solo lugar,
ya que las 3 apps comparten la misma VM y (parcialmente) el mismo recurso de
Azure Communication Services.

## Proyectos

| Carpeta | Qué hace | Notifica por | Corre como |
|---|---|---|---|
| [`StockWatcher/`](StockWatcher/) | Vigila stock/talla/color de productos (Nike Mind, Yeezy, etc.) en decenas de tiendas y avisa cuando hay restock al precio correcto. | Email (ACS), WhatsApp listo en código pero sin activar | `systemd` timer horario |
| [`PortfolioWatcher/`](PortfolioWatcher/) | Analiza el portafolio de inversión (riesgo/oportunidad) con un pipeline LLM de 2 niveles sobre Azure OpenAI; nunca ejecuta órdenes. | WhatsApp (ACS) | `systemd` timers 2x/día + semanal |
| [`HomelabFrontend/`](HomelabFrontend/) *(antes `HomelabDashboard`)* | Panel web (FastAPI) para editar configs y disparar corridas manuales de las otras 2 apps desde el celular, sin SSH. | — | `systemd` service detrás de Caddy (HTTPS + Basic Auth) |

Cada carpeta tiene su propio `README.md`, `docs/`, tests y `pyproject.toml` —
son paquetes Python independientes que solo comparten la VM y (donde aplica)
el recurso ACS `homelab-acs-3nob7f`.

## Por qué una sola VM y no Container Apps / Functions

Ver `PortfolioWatcher/docs/architecture.md` para el razonamiento original.
En resumen: las 3 cargas son ligeras (segundos a ~40s por corrida, 1-2x/hora
como mucho), la VM ya existe y tiene de sobra CPU/RAM libre (~2% CPU, ~3.6GB
RAM libres de 4GB), y `systemd timers` es más simple de operar que
Container Apps Jobs para este volumen — se evaluó Container Apps Job para
StockWatcher (ver `StockWatcher/infra/`, hoy sin desplegar) pero se descartó
por costo/complejidad frente a reusar la VM que PortfolioWatcher ya paga.

## Infraestructura (Terraform)

Solo `PortfolioWatcher/infra/` despliega infraestructura real hoy (la VM, su
NSG, IP pública con DNS label, y el Communication Service compartido). Los
otros dos proyectos se instalan **sobre** esa VM ya provisionada (rsync/git
clone + venv + unidades `systemd`), no crean sus propios recursos de Azure.
`StockWatcher/infra/` (Container Apps Job) existe pero no está desplegado —
se documenta como alternativa histórica, no como el método actual.

## CI/CD

Ver [`docs/ci-cd.md`](docs/ci-cd.md). Runner self-hosted de GitHub Actions
instalado directamente en `homelab-vm` (sin necesitar SSH entrante ni
credenciales de Azure en GitHub): cada push a `main` que toque una carpeta
dispara el workflow de esa carpeta, que hace `git pull` + reinstala el venv +
reinicia el `systemd` unit correspondiente.

## Incidente de seguridad resuelto (2026-09-03)

Al fusionar los repos se encontraron archivos `PortfolioWatcher/infra/tfplan*`
—planes de Terraform guardados, trackeados en git por error— con el
connection string real (incluyendo access keys) del recurso ACS compartido,
expuesto en el repo público de GitHub. Se resolvió así:

1. Se rotaron ambas access keys (`primary` y `secondary`) del recurso
   `homelab-acs-3nob7f` inmediatamente.
2. Se actualizaron los `.env` de StockWatcher y PortfolioWatcher en la VM con
   la connection string nueva.
3. Se reescribió el historial de PortfolioWatcher con `git filter-repo`
   eliminando esos 4 archivos de **todos** los commits, y se forzó el push.
4. Se agregó `tfplan*` a `.gitignore` (ya lo tenía StockWatcher; a
   PortfolioWatcher le faltaba).

Las llaves viejas quedaron inválidas antes de que el historial reescrito
terminara de propagarse, así que aunque GitHub cachee el commit huérfano por
un tiempo, el secreto en sí ya no sirve.

## Documentación por proyecto

- `PortfolioWatcher/docs/architecture.md` — arquitectura completa, pipeline LLM.
- `StockWatcher/docs/` — providers, WhatsApp template, discovery.
- `HomelabFrontend/docs/deployment.md` — Caddy, DNS, systemd del dashboard.
- `docs/ci-cd.md` (raíz) — runner self-hosted + workflows.
- `docs/stockwatcher-deployment.md` (raíz) — cómo se desplegó StockWatcher
  sobre la VM compartida (paso a paso real, incluye decisiones tomadas).
