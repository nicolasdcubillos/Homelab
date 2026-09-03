# HomelabDashboard

Panel de control web ligero (FastAPI + Uvicorn) para administrar, desde el
celular y sin SSH, varios servicios que corren en la misma VM Linux:
actualmente [PortfolioWatcher](https://github.com/nicolasdcubillos/PortfolioWatcher)
y, próximamente, [StockWatcher](https://github.com/nicolasdcubillos/StockWatcher).

El dashboard **no modifica** los repos de esas apps: se integra con ellas vía
su CLI (subprocess) y sus archivos de configuración YAML, descritos
declarativamente en un archivo `apps.yaml` que vive fuera de este repo.

## ¿Qué hace?

Por cada app configurada en `apps.yaml`:

- Muestra si está instalada en esta máquina (si el `path` no existe, se
  muestra como "no instalado" sin romper el resto de la página).
- Permite ver y editar sus archivos de configuración YAML como texto plano,
  validando que sea YAML parseable antes de guardar, y haciendo un backup con
  timestamp (`archivo.yaml.bak.AAAAMMDD-HHMMSS`) antes de sobreescribir.
- Permite disparar cualquiera de los comandos predefinidos en `apps.yaml`
  (ej. `daily`, `--dry-run weekly --force`), ejecutados en segundo plano
  contra el `venv` de esa app, con logs redirigidos a `logs/<app>/` dentro de
  **este** repo (no en el repo de la app administrada).
- Evita que la misma app corra dos comandos en simultáneo (los botones se
  deshabilitan mientras hay un job corriendo), pero permite que **distintas**
  apps corran jobs en paralelo.
- Muestra el estado del último job (corriendo/éxito/error), las últimas ~200
  líneas de su log (con botón de refrescar y auto-poll cada 3s vía JS
  vanilla), y un historial de las últimas 15 ejecuciones (persistido en
  SQLite, tabla `job_runs`).

## Seguridad

- **No implementa autenticación.** Se asume que corre detrás de un reverse
  proxy (Caddy) que hace HTTP Basic Auth + TLS. Ver `Caddyfile.example`.
- Por defecto solo escucha en `127.0.0.1` (configurable, ver abajo).
- Todas las rutas de archivos de configuración se resuelven y validan contra
  el `path` base de cada app — no es posible salirse de ese directorio
  (protección contra path traversal), incluso si alguien intenta mandar un
  `rel_path` manipulado por HTTP.
- Los comandos ejecutables son **únicamente** los declarados en `apps.yaml`;
  el dashboard nunca acepta comandos arbitrarios del usuario.
- `.env` de las apps administradas nunca se muestra ni se edita desde aquí.

## Instalación

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Configuración: `apps.yaml`

Copia `apps.yaml.example` a `apps.yaml` (este archivo **no se versiona**, ver
`.gitignore`) y ajústalo a tu VM real:

```bash
cp apps.yaml.example apps.yaml
# edita apps.yaml con las rutas reales de tu VM
```

Puedes indicar una ruta distinta con la variable de entorno
`DASHBOARD_APPS_FILE` (por defecto busca `apps.yaml` en el directorio de
trabajo actual).

## Correr localmente

Con el CLI (arranca uvicorn programáticamente):

```bash
homelab-dashboard
```

O directamente con uvicorn (útil en desarrollo, con recarga automática):

```bash
uvicorn homelab_dashboard.app:create_app --factory --reload
```

Variables de entorno soportadas:

| Variable              | Default        | Descripción                                   |
|-----------------------|----------------|------------------------------------------------|
| `DASHBOARD_HOST`      | `127.0.0.1`    | Host donde escucha uvicorn                     |
| `DASHBOARD_PORT`      | `8000`         | Puerto donde escucha uvicorn                   |
| `DASHBOARD_APPS_FILE` | `apps.yaml`    | Ruta al registro declarativo de apps            |
| `DASHBOARD_DB_FILE`   | `dashboard.db` | Ruta al SQLite de historial de jobs             |
| `DASHBOARD_LOGS_DIR`  | `logs`         | Directorio donde se guardan los logs de jobs    |

Abre `http://127.0.0.1:8000` en el navegador (o vía el reverse proxy en
producción).

## Tests y lint

```bash
pytest
ruff check .
```

Los tests usan un "entrypoint" falso (script Python simple) en vez de
`portfoliowatcher`/`stockwatcher` reales, y cubren: parseo/validación de
`apps.yaml`, bloqueo de path traversal, ejecución de comandos mockeados
(éxito, error, concurrencia por app, paralelismo entre apps distintas), y el
editor de configuración (rechazo de YAML inválido + backup antes de
escribir). No se hacen llamadas reales a Azure ni SSH a ninguna VM.

## Notas de producción

- `apps.yaml` real, `dashboard.db`, y `logs/` deben vivir en la VM pero
  **fuera de git** (ya están en `.gitignore`).
- La autenticación y TLS se manejan con **Caddy** como reverse proxy delante
  del dashboard (que solo escucha en `127.0.0.1`). Ver `Caddyfile.example`
  para una plantilla de referencia — el `Caddyfile` real con dominio y
  credenciales reales se configura fuera de este repo.
- Se recomienda correr el dashboard como un servicio systemd (`ExecStart=
  /opt/services/homelabdashboard/.venv/bin/homelab-dashboard`,
  `WorkingDirectory=/opt/services/homelabdashboard`) para que
  `apps.yaml`/`dashboard.db`/`logs/` relativos apunten al lugar correcto.
