# CI/CD: self-hosted runner en `homelab-vm`

## Por qué self-hosted en vez de SSH desde Actions

Intentamos usar `az vm run-command` y SSH normal desde un workflow hospedado
por GitHub, pero:

- El acceso SSH a `homelab-vm` está roto (`kex_exchange_identification: read:
  Connection reset by peer`) por una causa nunca identificada (NSG, sshd y
  firewall se ven correctos).
- `az vm run-command invoke` serializa por VM: solo una invocación a la vez, y
  si el proceso del lado que la invoca muere o se corta, la ejecución sigue
  corriendo en el lado de Azure de todas formas — puede dejar la VM
  "bloqueada" para nuevos `run-command` por varios minutos sin ningún proceso
  real corriendo.

La solución fue instalar un **runner de GitHub Actions self-hosted
directamente en la VM**. Esto evita ambos problemas: no depende del puerto 22
ni del límite de una-invocación-a-la-vez de `run-command`, y da logs
estructurados vía `gh run view --log` / la UI de Actions.

## Instalación (ya hecha, referencia para reinstalar si hace falta)

```bash
# En homelab-vm, como azureuser
mkdir -p /opt/actions-runner && cd /opt/actions-runner
curl -o actions-runner-linux-x64-2.321.0.tar.gz -L \
  https://github.com/actions/runner/releases/download/v2.321.0/actions-runner-linux-x64-2.321.0.tar.gz
tar xzf actions-runner-linux-x64-2.321.0.tar.gz

# Token de registro (expira rápido, generar justo antes de usarlo):
# gh api -X POST repos/nicolasdcubillos/Homelab/actions/runners/registration-token --jq .token

./config.sh --url https://github.com/nicolasdcubillos/Homelab \
  --token <TOKEN> --name homelab-vm-runner --labels self-hosted,homelab-vm \
  --unattended

sudo ./svc.sh install azureuser
sudo ./svc.sh start
```

Corre como servicio systemd
(`actions.runner.nicolasdcubillos-Homelab.homelab-vm-runner.service`), así que
sobrevive reinicios de la VM automáticamente.

Verificar que esté online:

```bash
gh api repos/nicolasdcubillos/Homelab/actions/runners --jq '.runners[] | {name,status}'
```

## Workflows de deploy

Cada proyecto tiene su propio workflow, filtrado por path, para que un cambio
en `StockWatcher/` no dispare un redeploy de `PortfolioWatcher` ni de
`HomelabFrontend`:

| Workflow | Dispara con cambios en | Qué hace |
|---|---|---|
| `deploy-stockwatcher.yml` | `StockWatcher/**` | git pull, reinstala venv, reinicia `stockwatcher-run.service` de inmediato (no espera al timer horario), imprime el último resumen |
| `deploy-portfoliowatcher.yml` | `PortfolioWatcher/**` | git pull, reinstala venv, smoke-check de import, verifica que los timers `daily`/`weekly` sigan activos |
| `deploy-homelabfrontend.yml` | `HomelabFrontend/**` | git pull, reinstala venv, reinicia `homelab-dashboard.service` (proceso long-running), verifica `curl` 200 |

Todos corren en `runs-on: [self-hosted, homelab-vm]`.

### Patrón para agregar un 4to proyecto

1. Agregar la carpeta nueva bajo la raíz del monorepo (ej. `NuevoProyecto/`).
2. Copiar uno de los 3 workflows existentes, ajustar el filtro `paths:` y los
   comandos de reinstalación/reinicio según el gestor de dependencias y el
   nombre del servicio systemd.
3. Si el proyecto necesita un servicio nuevo, crear su unit file en
   `/etc/systemd/system/` apuntando a `/opt/services/homelab/NuevoProyecto`,
   habilitarlo con `systemctl enable --now`.
4. Actualizar `apps.yaml` de HomelabFrontend si el dashboard debe mostrarlo.

## Incidente resuelto durante la migración de rutas

Al mover los 3 proyectos a `/opt/services/homelab/...`, `homelab-dashboard.service`
quedó en estado `activating (auto-restart)` en loop porque un proceso viejo
(`homelab-dashboard --help`, lanzado sin querer durante una verificación previa
de que el venv funcionara, pero sin ese flag real terminó arrancando el
servidor de verdad) seguía escuchando en el puerto 8000. Se identificó con
`lsof -i :8000`, se mató el proceso huérfano, y el servicio arrancó
normalmente (`systemctl is-active` → `active`, `curl` → `200`).

También se corrigieron rutas obsoletas en los `.env` de StockWatcher y
PortfolioWatcher (`STOCKWATCHER_STATE_PATH` seguía apuntando a
`/opt/services/stockwatcher`, la carpeta vieja ya borrada) — sin eso,
`sqlite_store.py` fallaba con `PermissionError` al intentar crear el
directorio padre inexistente.

## Runner: renovación de token

El token de registro (`config.sh --token ...`) es solo para el registro
inicial y expira en ~1 hora; no se guarda ni se necesita de nuevo salvo que
haya que reinstalar o re-registrar el runner (ej. si se borra por accidente
o se mueve a otra VM).
