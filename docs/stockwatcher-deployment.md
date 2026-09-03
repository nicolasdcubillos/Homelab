# Cómo se desplegó StockWatcher en `homelab-vm`

Runbook real (no genérico) de cómo StockWatcher pasó de "corre local en dry-run"
a "corre cada hora en producción", reusando la VM ya provisionada por
PortfolioWatcher en lugar de crear infraestructura nueva.

## 0. Contexto y decisión

El plan original (ver `StockWatcher/infra/`) era un Azure Container Apps Job
con cron trigger. Se probó de punta a punta con una suscripción real
(Terraform: resource group, ACR, Storage+Table, Log Analytics, ACS,
Container Apps Environment + Job — 12 recursos), incluyendo un build de
imagen con `az acr build` y una ejecución manual del job. Una ejecución real
falló (nunca se diagnosticó la causa raíz vía Log Analytics) y, en paralelo,
se decidió que el costo/complejidad no se justificaba: PortfolioWatcher ya
tiene una VM corriendo 24/7 con ~98% de CPU y ~90% de RAM libres, suficiente
para un scan de StockWatcher de ~40s cada hora. Se destruyó toda la
infraestructura de Container Apps (`terraform destroy`, 12/12 recursos) y se
migró al patrón de PortfolioWatcher: `systemd timer` sobre la VM compartida.

## 1. Prerrequisitos ya cumplidos por PortfolioWatcher

- VM Ubuntu 22.04 con Python 3.11 ya instalado en `/usr/bin/python3.11`
  (el `pyproject.toml` de StockWatcher requiere `>=3.11`; el `python3`
  default de Ubuntu 22.04 es 3.10).
- `git`, `sudo`, acceso a internet saliente.
- Un recurso Communication Services (`homelab-acs-3nob7f`) ya existente,
  reusado para el canal de email de StockWatcher (ver sección 4).

## 2. Acceso a la VM: SSH roto, se usó `az vm run-command`

El SSH directo (`ssh azureuser@<ip>`) falla consistentemente con
`kex_exchange_identification: read: Connection reset by peer`, pese a que el
NSG permite explícitamente la IP pública actual, `sshd` está activo y
escuchando, no hay `fail2ban`/`ufw`/`hosts.deny` bloqueando nada, y la
conexión TCP cruda (`nc -zv`) sí funciona. La causa nunca se identificó (no
es un problema de configuración de la VM que se haya podido reproducir de
forma determinística). **Workaround**: todo el despliegue se hizo vía
`az vm run-command invoke --command-id RunShellScript`, que no depende del
puerto 22 en absoluto. Dos particularidades de esto:

- Los scripts corren como **root**, no como `azureuser` — hubo que
  `chown -R azureuser:azureuser` después de cada instalación para que los
  archivos quedaran con el dueño correcto (en particular el caché de
  Playwright, ver sección 3).
- Cada invocación es un script de una sola vez (no hay sesión interactiva
  persistente), más lento para iterar que SSH pero suficiente para un
  despliegue de una vez.

## 3. Instalación del runtime

```bash
sudo mkdir -p /opt/services && cd /opt/services
sudo git clone https://github.com/nicolasdcubillos/Homelab.git homelab
# (o, antes de la fusión al monorepo: git clone .../StockWatcher.git stockwatcher)
sudo chown -R azureuser:azureuser homelab
cd homelab/StockWatcher

python3.11 -m venv .venv
.venv/bin/pip install -U pip
.venv/bin/pip install -e '.[azure,browser]'

# Playwright (para los providers que necesitan JS, ej. Nike):
.venv/bin/pip install playwright
sudo .venv/bin/playwright install-deps chromium   # deps de sistema, requiere root
.venv/bin/playwright install chromium              # descarga el browser

# El run-command anterior corrió como root, así que el caché de Playwright
# quedó en /root/.cache/ms-playwright. Copiarlo a azureuser y fijar el env var:
sudo cp -r /root/.cache/ms-playwright /home/azureuser/.cache/
sudo chown -R azureuser:azureuser /home/azureuser/.cache /opt/services/homelab
```

`PLAYWRIGHT_BROWSERS_PATH=/home/azureuser/.cache/ms-playwright` se fija en el
`.env` (sección 4) para que el proceso systemd (que sí corre como
`azureuser`) encuentre el browser.

Verificación (corrida real, no dry-run, hecha durante el despliegue):
34 tiendas escaneadas, 0 fallos, ~40s, mismo resultado que en Mac local —
confirma que no hay diferencias de comportamiento entre el Mac de desarrollo
y la VM Ubuntu para este código.

## 4. Notificaciones: por qué email y no WhatsApp

El plan original era WhatsApp vía ACS (como PortfolioWatcher). Al revisar,
**PortfolioWatcher tampoco tenía WhatsApp realmente conectado** — solo el
recurso ACS existía, sin el canal de WhatsApp Business vinculado. Conectar
WhatsApp requiere:

1. Vincular una cuenta de WhatsApp Business (Meta) al ACS desde el
   **portal de Azure** (Advanced Messaging → embedded signup de Meta) — no
   hay comando `az` para esto.
2. Verificación del negocio en Meta Business Manager (puede tardar días).
3. Aprobación de una plantilla de mensaje por Meta.

Como alternativa de cero-fricción se implementó un **`EmailNotifier`** nuevo
(`StockWatcher/src/stockwatcher/notifiers/email.py`) sobre **Azure
Communication Services Email**, usando un dominio administrado por Azure
(`*.azurecomm.net`) que se verifica solo, sin DNS propio ni aprobación de
Meta:

```bash
az communication email create -g HOMELAB-RG -n homelab-email \
  --location global --data-location "United States"

az communication email domain create -g HOMELAB-RG \
  --email-service-name homelab-email --domain-name AzureManagedDomain \
  --domain-management AzureManaged --location global
# Queda verificado (DKIM/DKIM2/DMARC/SPF/Domain) en el mismo comando, sin
# esperar propagación DNS -- a diferencia de un dominio propio.

# Vincular el dominio de email al Communication Service ya existente
# (el mismo que usa/usará WhatsApp), para reusar su connection string:
az communication update -g HOMELAB-RG -n homelab-acs-3nob7f \
  --linked-domains "/subscriptions/<sub>/resourceGroups/HOMELAB-RG/providers/Microsoft.Communication/emailServices/homelab-email/domains/AzureManagedDomain"
```

El sender resultante quedó como
`DoNotReply@<guid>.azurecomm.net`. `watches.yaml` usa `notify: [email]` por
defecto. WhatsApp queda completamente implementado en código
(`whatsapp.py`) para activarse más adelante sin tocar el runner — solo
falta rellenar `ACS_CHANNEL_REGISTRATION_ID`/`WHATSAPP_TO` en el `.env` una
vez exista el canal de Meta.

## 5. `systemd`: timer horario

Mismo patrón que PortfolioWatcher, con nombres de unidad distintos para no
chocar:

```ini
# /etc/systemd/system/stockwatcher-run.service
[Unit]
Description=StockWatcher hourly availability scan
After=network-online.target

[Service]
Type=oneshot
User=azureuser
WorkingDirectory=/opt/services/homelab/StockWatcher
EnvironmentFile=/opt/services/homelab/StockWatcher/.env
ExecStart=/opt/services/homelab/StockWatcher/.venv/bin/stockwatcher run
```

```ini
# /etc/systemd/system/stockwatcher-run.timer
[Unit]
Description=Run stockwatcher-run.service roughly every hour

[Timer]
OnCalendar=*-*-* *:07:00
RandomizedDelaySec=120
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now stockwatcher-run.timer
```

El estado (qué ya se notificó, para no repetir alertas) se guarda en sqlite
local (`data/stockwatcher.db`), no en Azure Table — no hace falta una cuenta
de Storage dedicada ya que corre en una VM con disco persistente.

## 6. Incidente de seguridad y su resolución

Ver la sección "Incidente de seguridad resuelto" en el `README.md` raíz de
este monorepo — los archivos `tfplan*` de PortfolioWatcher (creados antes de
esta migración) tenían el connection string real del ACS compartido
trackeado en git público. Se rotaron las llaves y se reescribió el
historial antes de terminar de documentar este despliegue.

## Verificación end-to-end realizada

- Corrida manual (`systemctl start stockwatcher-run.service`): 34 tiendas,
  12 hits, 1 email enviado (agrupa todos los hits en un solo correo),
  0 errores, ~42s de duración.
- Email de prueba y el de la corrida real confirmados recibidos en
  `nicolasdavidcubillos@gmail.com`.
- Segunda corrida consecutiva (verificación de supresión de repetidos):
  mismos hits, `new_hits: 0` esperado — el mismo mecanismo de sqlite que ya
  estaba probado en 202 tests y en las corridas locales previas.

## Pendiente / siguiente paso natural

- Activar WhatsApp cuando se complete el setup de Meta Business Manager
  (needs: `ACS_CHANNEL_REGISTRATION_ID`, número destino, plantilla
  aprobada — texto ya redactado en `StockWatcher/docs/whatsapp-template.md`).
- Decidir si `StockWatcher/infra/` (Container Apps Job) se elimina o se deja
  documentado como alternativa descartada — hoy queda como referencia
  histórica sin desplegar.
