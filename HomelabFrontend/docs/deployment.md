# Despliegue en producción

Este documento describe, paso a paso, cómo se desplegó HomelabDashboard en la
VM `homelab-vm` (la misma VM Linux donde corre PortfolioWatcher, y donde
correrá StockWatcher). Es la referencia real usada en producción — no un
tutorial genérico — así que incluye las decisiones concretas que se tomaron
y por qué.

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
  internet a propósito — el dashboard se protege con TLS + Basic Auth, no
  con restricción de IP, porque se accede desde un celular en redes que
  cambian de IP constantemente).

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

Genera el hash de tu contraseña y escribe el Caddyfile real (ver
`Caddyfile.example` en este repo para la plantilla sin credenciales):

```bash
caddy hash-password --plaintext 'TU_CONTRASEÑA_FUERTE'
```

```caddyfile
# /etc/caddy/Caddyfile
homelab-3nob7f.eastus.cloudapp.azure.com {
    basic_auth {
        nicolas <hash-bcrypt-generado-arriba>
    }
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
mkdir -p logs
```

Para actualizaciones posteriores:

```bash
cd /opt/services/homelab-dashboard
git fetch origin && git reset --hard origin/main
./.venv/bin/pip install -e .
systemctl restart homelab-dashboard
```

## 5. `apps.yaml` real

Copia `apps.yaml.example` a `apps.yaml` **en la VM** (este archivo nunca se
versiona, ver `.gitignore`) y ajusta las rutas si difieren de
`/opt/services/<app>`:

```bash
cp apps.yaml.example apps.yaml
```

## 6. Servicio systemd

Usa `systemd/homelab-dashboard.service.example` como plantilla: cópialo a
`/etc/systemd/system/homelab-dashboard.service` y luego:

```bash
systemctl daemon-reload
systemctl enable --now homelab-dashboard.service
systemctl is-active homelab-dashboard.service
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/   # 200 esperado
```

## 7. Verificación end-to-end

Desde cualquier máquina (celular, laptop):

```bash
# Sin credenciales -> 401
curl -s -o /dev/null -w '%{http_code}\n' https://homelab-3nob7f.eastus.cloudapp.azure.com/

# Con credenciales -> 200
curl -s -o /dev/null -w '%{http_code}\n' -u 'nicolas:TU_CONTRASEÑA' \
  https://homelab-3nob7f.eastus.cloudapp.azure.com/
```

O simplemente abre la URL en el navegador — el certificado debe verse válido
(sin advertencias) y el navegador debe pedir usuario/contraseña.

## Notas y decisiones de diseño

- **Por qué Caddy y no Nginx/Certbot**: Caddy obtiene y renueva certificados
  Let's Encrypt automáticamente sin configuración adicional ni cronjobs de
  renovación, y su sintaxis de `basic_auth` + `reverse_proxy` es mínima.
- **Por qué el dashboard solo escucha en 127.0.0.1**: toda la superficie de
  ataque pública (TLS, auth, parsing HTTP crudo) queda concentrada en Caddy,
  que es software maduro y de un solo propósito; la app Python nunca recibe
  tráfico no autenticado directamente.
- **Por qué `domain_name_label` de Azure en vez de una Dynamic DNS externa
  (DuckDNS, No-IP, etc.)**: es gratis, no depende de un servicio de terceros
  adicional, y Microsoft lo mantiene como parte del propio recurso de IP
  pública — se actualiza solo si la IP cambia.
- **Regenerar la contraseña**: `caddy hash-password --plaintext 'nueva'`,
  reemplaza el hash en `/etc/caddy/Caddyfile`, y `systemctl reload caddy`.
