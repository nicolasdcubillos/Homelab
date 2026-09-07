# Despliegue en producción

Este documento describe cómo se despliega el dashboard en la VM `homelab-vm`
(la misma VM Linux donde corren PortfolioWatcher y StockWatcher). Es la
referencia real usada en producción — no un tutorial genérico — así que incluye
las decisiones concretas que se tomaron y por qué.

**El despliegue es automático.** Los tres componentes viven en el monorepo
[`nicolasdcubillos/Homelab`](https://github.com/nicolasdcubillos/Homelab), y un
*runner* self-hosted instalado en la propia VM ejecuta los workflows de
`.github/workflows/`. Cada push a `main` que toque `HomelabFrontend/**` dispara
`deploy-homelabfrontend.yml`, que actualiza el código, compila el SPA, instala
el unit de systemd y reinicia el servicio. **En condiciones normales no hay que
tocar la VM a mano**; los pasos manuales de este documento están para entender
qué hace el workflow, para el primer arranque y para diagnosticar.

El código y el SPA se instalan en releases aislados bajo
`/opt/services/homelab-dashboard/releases/<SHA>.<sufijo>`, con el enlace atómico
`current` apuntando al activo. La base, `apps.yaml`, `data/` y `logs/` conservan
sus rutas bajo `/opt/services/homelab/HomelabFrontend`; no se copian entre releases.
El workflow ya no resetea el checkout compartido ni actualiza su venv en caliente.

Desde la migración a multiusuario, el dashboard tiene su **propia
autenticación** (registro, login, roles, sesiones), su **propia base de
datos** (SQLite + Alembic) y un **frontend compilado** (React/Vite) que
FastAPI sirve como estático. Caddy deja de hacer Basic Auth: solo termina TLS.

## 0. Prerrequisitos

- La VM ya existe (provisionada vía Terraform, carpeta `PortfolioWatcher/infra`
  del monorepo), con Python 3.10+, Node 20.19+ o 22.12+, `git` y acceso `sudo`.
- Un runner self-hosted de GitHub Actions corriendo en la VM con las etiquetas
  `self-hosted` y `homelab-vm` (servicio
  `actions.runner.nicolasdcubillos-Homelab.homelab-vm-runner`). Es lo que
  ejecuta los despliegues.
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

## 4. Actualizar mediante un release aislado

El instalador actual actualiza una instalación existente: exige servicio activo,
base, unit y Caddyfile previos. No es un bootstrap de una VM vacía. El clon y los
datos persistentes existentes no se modifican durante la construcción.
Un fallo registrado de despliegue admite recuperación con el servicio detenido.

El workflow hace checkout del SHA exacto en su workspace e invoca:

```bash
sudo bash HomelabFrontend/scripts/deploy-market-regime.sh "$(git rev-parse HEAD)"
```

Para probar un candidato antes de publicarlo, añadir `--prepare-only`: instala
y valida el release sobre una copia, pero no detiene el servicio, no modifica su
base ni cambia el enlace activo. El candidato queda conservado para inspección.

El script toma un lock, construye el paquete no editable y el SPA como
`azureuser`, y deja el release final propiedad de root. Antes de detener el
servicio, migra una copia privada de SQLite y comprueba la API sin iniciar
scheduler, workers, proveedores ni envíos. Después de detenerlo guarda otra
copia consistente en `/var/backups/homelab/dashboard-<fecha>.<sufijo>/dashboard.db`
(directorio 0700, archivo 0600), cambia el enlace y arranca la nueva versión.
SQLite backup incorpora el WAL: no sustituirlo por un `cp` del archivo abierto.

Se instala el extra `regime-notifications` para disponer de los SDK de ACS,
sin cargar credenciales ni habilitar envíos. `REVISION` identifica el código y
`packages.json` registra las versiones resueltas de cada release.

Los cambios de permisos, consentimientos, claves y configuración operativa
quedan fuera del instalador. El drop-in de TradingLab se conserva.

**Recuperación:** un fallo previo a la migración permite recuperar código/unit.
Si se intentó una nueva migración, no se vuelve al paquete anterior: su Alembic
podría desconocer el nuevo head. Se conservan candidato y respaldo, se detiene
el servicio y el workflow falla para una recuperación explícita. No se hace
downgrade ni restauración automática de la base, pues perdería escrituras.
Diagnosticar con `journalctl -u homelab-dashboard.service`, corregir el candidato
y ejecutar el instalador con `--recover` (también admite `--prepare-only`).
Este modo exige un fallo registrado y que la DB, el enlace y la configuración
systemd sigan siendo los registrados; no adopta cualquier servicio detenido.
Rechaza un servicio todavía activo. También puede seleccionarse `recover` al
ejecutar manualmente el workflow desde Actions, o con
`gh workflow run deploy-homelabfrontend.yml --ref main -f recover=true`.
Repite preflight y backup, sin restaurar el paquete que ya falló. Restaurar una
base requiere una decisión operativa
separada y conservar antes el estado fallido para no perder datos.

Las copias y releases se conservan; revisar espacio y retirar manualmente
solamente históricos que ya no se necesiten. Nunca borrar `current`, su destino
ni el último respaldo necesario para recuperar una migración.

También puedes relanzar el despliegue sin cambiar código desde la pestaña
Actions del repo (`workflow_dispatch`), o con
`gh workflow run deploy-homelabfrontend.yml --repo nicolasdcubillos/Homelab`.

## 5. Frontend: compilar el `dist` en la VM

El servidor sirve `frontend/dist` como estático (con fallback SPA para
cualquier ruta que no sea `/api/*`). Como el `dist/` no se versiona (ver
`.gitignore`), hay que compilarlo en la VM tras cada cambio del frontend —
**esto lo hace el script de despliegue en su directorio temporal**, no tú.

Node se instala una sola vez con NodeSource (Ubuntu):

```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y -qq nodejs
node -v   # v20.x
```

Una compilación manual en un checkout sirve para desarrollo, no cambia el SPA
productivo:

```bash
cd /opt/services/homelab/HomelabFrontend/frontend
npm ci        # respeta package-lock.json, así que es reproducible
npm run build # genera frontend/dist/
```

Se usa `npm ci` y no `npm install` a propósito: `ci` instala exactamente las
versiones del lockfile y falla si el lockfile y el `package.json` no coinciden,
que es lo que quieres en un despliegue.

## 6. `apps.yaml` real

Copia `apps.yaml.example` a `apps.yaml` **en la VM** (este archivo nunca se
versiona, ver `.gitignore`) y ajusta las rutas si difieren de
`/opt/services/<app>`:

```bash
cp apps.yaml.example apps.yaml
```

## 7. Servicio systemd

El unit **vive en el repo**, en `systemd/homelab-dashboard.service`, y el
workflow lo copia a `/etc/systemd/system/` en cada despliegue. Esa es la fuente
de verdad: si necesitas cambiar una ruta o una variable de entorno, cámbiala
ahí y haz push. **No edites el archivo en la VM**, porque el siguiente
despliegue lo sobrescribe.

(El archivo `systemd/homelab-dashboard.service.example` sigue ahí como
plantilla para quien despliegue esto fuera del monorepo, con rutas genéricas.)

Variables que conviene conocer: `DASHBOARD_DATA_DIR` (workspaces por usuario),
`DASHBOARD_DB_FILE` (la base heredada, que se conserva para no perder el
histórico de `job_runs`), `DASHBOARD_FRONTEND_DIST` (el `dist/` del paso 5) y
`ExecStartPre=... migrate`, que aplica las migraciones de Alembic antes de
arrancar, en cada reinicio.

El unit usa el binario y el SPA de `current`, conservando el directorio de
trabajo y todas las rutas persistentes. No instalar este unit antes de que
exista un release. El instalador hace el cambio coordinado.

El archivo opcional `/etc/homelab/market-regime.env` admite únicamente claves
`DASHBOARD_REGIME_*`, una por línea; debe ser de root y modo 0600. No puede
cambiar la DB, el puerto ni el scheduler global. No se copian claves de otros
servicios. Los envíos del módulo permanecen desactivados por defecto.
Los booleanos y límites numéricos inválidos provocan un error explícito de
configuración; no se sustituyen silenciosamente por valores predeterminados.

Diagnóstico:

```bash
systemctl is-active homelab-dashboard.service
sudo cat /opt/services/homelab-dashboard/current/REVISION
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/   # 200 esperado
```

## 8. Sembrar el primer administrador

La primera vez (o tras una base nueva), crea la cuenta admin desde la propia
VM — la contraseña se pide de forma interactiva, nunca por argumento:

```bash
cd /opt/services/homelab/HomelabFrontend
sudo env DASHBOARD_DB_FILE=/opt/services/homelab/HomelabFrontend/dashboard.db \
  DASHBOARD_DATA_DIR=/opt/services/homelab/HomelabFrontend/data \
  /opt/services/homelab-dashboard/current/.venv/bin/homelab-dashboard \
  create-admin --email tu-correo@ejemplo.com
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
