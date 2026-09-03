# Despliegue en producción

Este documento describe, paso a paso, cómo se despliega HomelabDashboard en la
VM `homelab-vm` (la misma VM Linux donde corren PortfolioWatcher y
StockWatcher). Es la referencia real usada en producción — no un tutorial
genérico — así que incluye las decisiones concretas que se tomaron y por qué.

Desde la migración a multiusuario, el dashboard tiene su **propia
autenticación** (registro, login, roles, sesiones), su **propia base de
datos** (SQLite + Alembic) y un **frontend compilado** (React/Vite) que
FastAPI sirve como estático. Caddy deja de hacer Basic Auth: solo termina TLS.

## 0. Prerrequisitos

- La VM ya existe (provisionada vía Terraform en el repo de
  [PortfolioWatcher](https://github.com/nicolasdcubillos/PortfolioWatcher),
  carpeta `infra/`), con Python 3.11+, `git`, y acceso `sudo`.
- Acceso a la VM: por SSH normal (`ssh azureuser@<ip-o-fqdn>`) si tu red lo
  permite, o vía `az vm run-command invoke` si estás en un entorno que
  bloquea el handshake SSH (ver nota de PortfolioWatcher `README.md`).
- El Network Security Group de la VM debe permitir tráfico entrante en los
  puertos **80** y **443** (usados por Caddy para ACME/HTTP→HTTPS redirect y
  HTTPS respectivamente). En el Terraform de PortfolioWatcher esto es la
  regla `AllowWebDashboard` en `infra/main.tf`, controlada por la variable
  `allowed_web_source_address` (por defecto `"*"`, es decir, abierta a
  internet a propósito — el dashboard se protege con TLS + su propia
  autenticación, no con restricción de IP, porque se accede desde un celular
  en redes que cambian de IP constantemente).

## 1. Dominio para HTTPS: usa el DNS gratuito de Azure, no nip.io

Para que Caddy pueda emitir un certificado real de Let's Encrypt necesitas un
nombre de dominio público que resuelva a la IP de la VM (Let's Encrypt no
emite certificados para IPs sueltas).

**Evita servicios de "wildcard DNS" genéricos como `nip.io`, `sslip.io` o
`xip.io`**: varias VPNs y filtros DNS los bloquean por defecto porque se usan
también en ataques de DNS rebinding.

En su lugar, usa el **DNS label gratuito que Azure asigna a cualquier IP
pública** — es un dominio real bajo `*.cloudapp.azure.com`, propiedad de
Microsoft, que ninguna VPN normal bloquea. Se configura con el atributo
`domain_name_label` del recurso `azurerm_public_ip` (ver
`infra/main.tf` de PortfolioWatcher):

```hcl
resource "azurerm_public_ip" "this" {
  # ...
  domain_name_label = "${var.project_name}-${local.suffix}"
}
```

Tras `terraform apply`, el FQDN resultante queda en el output `vm_fqdn`
(ej. `homelab-3nob7f.eastus.cloudapp.azure.com`). Verifica que resuelve:

```bash
terraform output -raw vm_fqdn
nslookup "$(terraform output -raw vm_fqdn)"
```

## 2. Instalar Caddy en la VM

```bash
apt-get update -qq
apt-get install -y -qq debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
  | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
  | tee /etc/apt/sources.list.d/caddy-stable.list
apt-get update -qq
apt-get install -y -qq caddy
```

Esto instala y habilita el servicio `caddy.service` automáticamente.

## 3. Configurar `/etc/caddy/Caddyfile`

Ver `Caddyfile.example` en este repo para la plantilla. **Ya no lleva
`basic_auth`** — la autenticación la hace el propio dashboard:

```caddyfile
# /etc/caddy/Caddyfile
homelab-3nob7f.eastus.cloudapp.azure.com {
    reverse_proxy 127.0.0.1:8000
}
```

```bash
systemctl reload caddy || systemctl restart caddy
systemctl is-active caddy
```

Caddy emite y renueva el certificado TLS automáticamente (Let's Encrypt) la
primera vez que recibe tráfico para ese dominio — no hace falta ningún paso
manual adicional.

## 4. Clonar y preparar el dashboard

```bash
mkdir -p /opt/services
git clone https://github.com/nicolasdcubillos/HomelabDashboard.git \
  /opt/services/homelab-dashboard
cd /opt/services/homelab-dashboard
python3.11 -m venv .venv
./.venv/bin/pip install -e .
```

Para actualizaciones posteriores:

```bash
cd /opt/services/homelab-dashboard
git fetch origin && git reset --hard origin/main
./.venv/bin/pip install -e .
./.venv/bin/homelab-dashboard migrate   # también corre solo, vía ExecStartPre
systemctl restart homelab-dashboard
```

## 5. Frontend: compilar el `dist` en la VM

El servidor sirve `frontend/dist` como estático (con fallback SPA para
cualquier ruta que no sea `/api/*`). Hay que compilarlo tras cada
`git pull` que toque `frontend/`.

**Opción A — Node en la VM (recomendada, sin dependencias externas).** Se
instala una sola vez con NodeSource (Ubuntu):

```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt-get install -y -qq nodejs
node -v   # v20.x
```

Y se compila:

```bash
cd /opt/services/homelab-dashboard/frontend
npm ci
npm run build      # genera frontend/dist/
```

Repite `npm ci && npm run build` cada vez que actualices el código (el
`dist/` no se versiona, ver `.gitignore`).

**Opción B — artefacto precompilado desde CI, sin instalar Node en la VM.**
El workflow `.github/workflows/ci.yml` compila el frontend en cada push a
`main` y sube el resultado como artefacto (`frontend-dist`, 30 días de
retención). Para desplegarlo sin Node local:

```bash
# Requiere gh CLI autenticado en la VM (gh auth login), una sola vez.
cd /opt/services/homelab-dashboard
gh run download --repo nicolasdcubillos/HomelabDashboard \
  --name frontend-dist --dir frontend/dist -R nicolasdcubillos/HomelabDashboard
```

Ambas opciones son válidas; la A es más simple de automatizar en un script de
despliegue propio, la B evita instalar Node en la VM a costa de depender de
`gh` autenticado. El despliegue de referencia usa la opción A.

## 6. `apps.yaml` real

Copia `apps.yaml.example` a `apps.yaml` **en la VM** (este archivo nunca se
versiona, ver `.gitignore`) y ajusta las rutas si difieren de
`/opt/services/<app>`:

```bash
cp apps.yaml.example apps.yaml
```

## 7. Servicio systemd

Usa `systemd/homelab-dashboard.service.example` como plantilla: cópialo a
`/etc/systemd/system/homelab-dashboard.service` y ajusta las rutas si tu
instalación no vive en `/opt/services/homelab-dashboard`. Nota las variables
nuevas: `DASHBOARD_DATA_DIR` (base de datos + workspaces por usuario),
`DASHBOARD_FRONTEND_DIST` (el `dist/` compilado en el paso 5), y
`ExecStartPre=... migrate` (aplica las migraciones de Alembic antes de
arrancar, en cada reinicio del servicio).

```bash
systemctl daemon-reload
systemctl enable --now homelab-dashboard.service
systemctl is-active homelab-dashboard.service
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/   # 200 esperado
```

## 8. Sembrar el primer administrador

La primera vez (o tras una base nueva), crea la cuenta admin desde la propia
VM — la contraseña se pide de forma interactiva, nunca por argumento:

```bash
cd /opt/services/homelab-dashboard
./.venv/bin/homelab-dashboard create-admin --email tu-correo@ejemplo.com
```

Entra a `https://tu-dominio/` y usa ese correo y contraseña para iniciar
sesión. Desde ahí puedes reconstruir tu configuración (watches, holdings,
notificaciones, programación) directamente en la UI.

## 9. Verificación end-to-end

Desde cualquier máquina (celular, laptop), abre la URL del dominio en el
navegador — el certificado debe verse válido (sin advertencias), la pantalla
de login debe cargar, y tras autenticarte debes ver el panel.

```bash
# Sin sesión, la API rechaza con 401 (no 200): confirma que no hay acceso
# anónimo a datos.
curl -s -o /dev/null -w '%{http_code}\n' https://tu-dominio/api/v1/auth/me
```

## Notas y decisiones de diseño

- **Por qué Caddy y no Nginx/Certbot**: Caddy obtiene y renueva certificados
  Let's Encrypt automáticamente sin configuración adicional ni cronjobs de
  renovación, y su sintaxis de `reverse_proxy` es mínima.
- **Por qué el dashboard solo escucha en 127.0.0.1**: toda la superficie de
  ataque pública (TLS, parsing HTTP crudo) queda concentrada en Caddy, que es
  software maduro y de un solo propósito; la app Python nunca recibe tráfico
  no autenticado directamente desde internet.
- **Por qué Caddy ya no hace Basic Auth**: el modelo pasó de single-user a
  multiusuario con roles; Basic Auth solo soporta una identidad compartida y
  no puede expresar "usuario X ve solo sus datos". La autenticación ahora vive
  en el dashboard (sesiones httpOnly + CSRF, rate limiting en login).
- **Por qué compilar el frontend en la VM en vez de versionar `dist/`**:
  versionar un build generado duplica la fuente de verdad y ensucia el
  historial de git con binarios. Compilar en CI y en la VM (opción A) o
  descargar el artefacto de CI (opción B) mantiene el repo limpio; ver
  `.github/workflows/ci.yml`.
- **Por qué `domain_name_label` de Azure en vez de una Dynamic DNS externa
  (DuckDNS, No-IP, etc.)**: es gratis, no depende de un servicio de terceros
  adicional, y Microsoft lo mantiene como parte del propio recurso de IP
  pública — se actualiza solo si la IP cambia.
- **Migraciones**: `ExecStartPre` corre `homelab-dashboard migrate` en cada
  arranque del servicio; es idempotente (no hace nada si ya está al día), así
  que no hay riesgo de aplicarla dos veces.
