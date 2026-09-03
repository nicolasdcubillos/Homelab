# HomelabDashboard

Panel de control web multiusuario (FastAPI + SPA React) para administrar,
desde el celular y sin SSH, varios servicios que corren en la misma VM Linux:
[PortfolioWatcher](https://github.com/nicolasdcubillos/PortfolioWatcher) y
[StockWatcher](https://github.com/nicolasdcubillos/StockWatcher).

El dashboard **no modifica** los repos de esas apps: se integra con ellas vía
su CLI (subprocess), generando la configuración de cada usuario al vuelo en un
workspace aislado. Cada usuario tiene su propia cuenta, su propia
configuración (vigilancias, portafolio, notificaciones), su propia
programación automática y su propio historial de ejecuciones — nadie ve ni
toca los datos de otro.

## ¿Qué hace?

- **Cuentas y roles**: registro, login, cambio de contraseña, roles `user` y
  `admin`. Las cuentas nuevas nacen `pending` hasta que un admin las activa.
- **Configuración desde formularios**, no YAML a mano:
  - **StockWatcher**: vigilancias (nombre, términos de match/exclusión,
    tallas, género, colores, precio máximo, países, canales).
  - **PortfolioWatcher**: holdings, posiciones cerradas, perfil de riesgo.
  - **Notificaciones**: correo y WhatsApp por usuario, canales activos por
    app.
- **Automatización**: cada usuario define cada cuánto corre cada app
  (intervalo o cron), con un scheduler in-process que respeta esa
  programación, evita solapamientos y sobrevive a reinicios.
- **Ejecución bajo demanda**: "ejecutar ahora" y "probar sin enviar"
  (dry-run) por app, con historial y log en vivo.
- **Panel de administración**: lista de usuarios con búsqueda/orden, ficha de
  cada uno (qué tiene configurado, sus ejecuciones), acciones (activar,
  suspender, cambiar contraseña, promover, eliminar) y métricas globales.

## Arquitectura

- **Backend**: FastAPI, API JSON versionada en `/api/v1/...`. SQLite (WAL)
  como única fuente de verdad, con migraciones de Alembic. Sesiones por
  cookie `httpOnly` + CSRF de doble envío; sin JWT ni claves de aplicación que
  rotar (el token de sesión es aleatorio, solo se guarda su hash).
- **Frontend**: SPA en `frontend/` (Vite + React + TypeScript + Tailwind v4),
  con tipos generados del esquema OpenAPI del backend. En producción, FastAPI
  sirve el `dist/` compilado directamente; `/api/*` tiene prioridad sobre el
  fallback SPA. Ver `docs/deployment.md` para el flujo de build.
- **Aislamiento por usuario en disco**: `data/users/<user_id>/<app>/config/`
  (YAML generado en cada corrida) y `.../state/` (base de estado propia).
  Los `config/*.yaml` de los repos administrados **nunca** se escriben.
- **Scheduler**: un tick cada 30s revisa `schedules` en SQLite y despacha lo
  que ya venció (con claim atómico, para que no se duplique ni con más de un
  worker). Los watchers propiamente dichos siguen ejecutándose por subprocess,
  igual que antes.

## Seguridad

- Autenticación propia (argon2id para contraseñas), rate limiting en login
  (backoff tras fallos repetidos), CSRF en toda mutación con cookies.
- Aislamiento estricto entre usuarios: todo endpoint deriva el `user_id` de la
  sesión, nunca de la URL o el body; un recurso ajeno responde 404, no 403.
- Los comandos ejecutables son **únicamente** los declarados en `apps.yaml`;
  el dashboard nunca acepta comandos arbitrarios.
- Path traversal bloqueado tanto en el registro de apps (`apps.yaml`) como en
  los workspaces generados por usuario.
- `.env` de las apps administradas nunca se muestra, edita ni versiona desde
  aquí; solo aporta secretos compartidos (ver `docs/watchers-contract.md`
  sobre la precedencia de variables de entorno).
- Caddy delante solo termina TLS — ya no hace Basic Auth (ver
  `docs/deployment.md`).

## Instalación (desarrollo)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
alembic upgrade head          # o: homelab-dashboard migrate

cd frontend
npm install
npm run gen:api               # tipos TS desde el OpenAPI del backend
```

## Configuración: `apps.yaml`

Copia `apps.yaml.example` a `apps.yaml` (este archivo **no se versiona**, ver
`.gitignore`) y ajústalo a tu VM real:

```bash
cp apps.yaml.example apps.yaml
# edita apps.yaml con las rutas reales de tu VM
```

Puedes indicar una ruta distinta con `DASHBOARD_APPS_FILE`.

## Correr localmente

Backend (API + SPA compilado, si existe `frontend/dist`):

```bash
homelab-dashboard          # equivale a `homelab-dashboard serve`
```

En desarrollo del frontend, con recarga en caliente y proxy a la API:

```bash
# Terminal 1
uvicorn homelab_dashboard.app:create_app --factory --reload

# Terminal 2
cd frontend && npm run dev   # sirve en :5173 con proxy a :8000
```

Crear el primer administrador:

```bash
homelab-dashboard create-admin --email tu-correo@ejemplo.com
```

### Variables de entorno soportadas

| Variable                           | Default                   | Descripción                                                           |
|-------------------------------------|----------------------------|------------------------------------------------------------------------|
| `DASHBOARD_HOST`                    | `127.0.0.1`                | Host donde escucha uvicorn                                              |
| `DASHBOARD_PORT`                    | `8000`                      | Puerto donde escucha uvicorn                                            |
| `DASHBOARD_APPS_FILE`               | `apps.yaml`                 | Ruta al registro declarativo de apps                                    |
| `DASHBOARD_DATA_DIR`                | `data`                      | Base de datos, workspaces y estado por usuario                          |
| `DASHBOARD_DB_FILE`                 | `<data_dir>/dashboard.db`   | Ruta explícita del SQLite (compatibilidad)                              |
| `DASHBOARD_LOGS_DIR`                | `logs`                      | Directorio de logs de ejecuciones                                       |
| `DASHBOARD_FRONTEND_DIST`           | `frontend/dist`             | Build de Vite que sirve FastAPI en `/`                                  |
| `DASHBOARD_SECURE_COOKIES`          | `true`                      | Marca `Secure` en la cookie de sesión (desactivar solo en HTTP local)   |
| `DASHBOARD_SESSION_TTL_HOURS`       | `720`                       | Vigencia de una sesión (horas)                                          |
| `DASHBOARD_LOGIN_MAX_ATTEMPTS`      | `5`                         | Intentos de login antes de bloquear                                     |
| `DASHBOARD_LOGIN_WINDOW_MINUTES`    | `15`                        | Ventana deslizante de conteo de intentos                                |
| `DASHBOARD_LOGIN_LOCKOUT_MINUTES`   | `15`                        | Duración del bloqueo tras exceder los intentos                          |
| `DASHBOARD_SCHEDULER_ENABLED`       | `true`                      | Enciende/apaga el scheduler in-process                                  |
| `DASHBOARD_SCHEDULER_TICK_SECONDS`  | `30`                        | Frecuencia con la que el scheduler revisa programaciones                |
| `DASHBOARD_MAX_CONCURRENT_JOBS`     | `4`                         | Tope global de subprocess simultáneos                                   |
| `DASHBOARD_DEFAULT_TIMEZONE`        | `America/Bogota`            | Zona horaria por defecto para usuarios nuevos                          |

## Tests y lint

```bash
pytest
ruff check .

cd frontend
npm run typecheck
npm run lint
npm run test -- --run
npm run build
```

Los tests de backend usan un "entrypoint" falso en vez de
`portfoliowatcher`/`stockwatcher` reales, y cubren: auth y roles, aislamiento
de datos entre usuarios, CRUD de configuración y su generación a YAML,
scheduler (con reloj falso), y endpoints de admin. No se hacen llamadas
reales a Azure ni SSH a ninguna VM.

## Documentación relacionada

- [`docs/deployment.md`](docs/deployment.md) — runbook completo de despliegue
  (dominio, Caddy, systemd, build del frontend, migraciones, bootstrap del
  primer admin).
- [`docs/watchers-contract.md`](docs/watchers-contract.md) — contrato vigente
  entre el dashboard y los repos hermanos: qué acepta cada CLI, la
  precedencia de destinos de notificación, y el historial de los seis
  hallazgos que motivaron cambios en esos repos (ya resueltos).
