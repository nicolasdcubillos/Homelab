#!/usr/bin/env bash
# Despliegue del dashboard completo; no modifica el checkout compartido.
set -Eeuo pipefail
umask 077

if [ "$(id -u)" -ne 0 ]; then
  echo "Ejecuta este script con sudo." >&2
  exit 1
fi
source_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
repo_dir="$(dirname "$source_dir")"
revision="${1:?Uso: deploy-market-regime.sh <SHA completo> [--prepare-only] [--recover]}"
[[ "$revision" =~ ^[0-9a-f]{40}$ ]] || { echo "SHA no valido." >&2; exit 1; }
shift
prepare_only=0
recover=0
for option in "$@"; do
  case "$option" in
    --prepare-only) prepare_only=1 ;;
    --recover) recover=1 ;;
    *) echo "Opcion no admitida." >&2; exit 1 ;;
  esac
done
actual="$(git -c safe.directory="$repo_dir" -C "$repo_dir" rev-parse HEAD)"
test "$actual" = "$revision"
python="${DASHBOARD_DEPLOY_PYTHON:-python3}"
"$python" -c 'import sys; assert sys.version_info >= (3, 10)'

base=/opt/services/homelab-dashboard
current="$base/current"
db=/opt/services/homelab/HomelabFrontend/dashboard.db
unit=/etc/systemd/system/homelab-dashboard.service
caddy=/etc/caddy/Caddyfile
service=homelab-dashboard.service
recovery_marker="$base/recovery-required"
install -d -m 0755 "$base/releases"
exec 9>"$base/deploy.lock"
flock -n 9 || { echo "Otro despliegue del dashboard esta en curso." >&2; exit 1; }
test -f "$db"
test -f "$unit"
test -f "$caddy"
if [ -e "$current" ] && [ ! -L "$current" ]; then
  echo "$current debe ser un enlace de despliegue." >&2
  exit 1
fi
if [ -L "$current" ]; then test -d "$current"; fi
"$python" "$source_dir/scripts/comprobar_despliegue.py" \
  environment /etc/homelab/market-regime.env
was_active=0
if systemctl is-active --quiet "$service"; then
  was_active=1
  pid="$(systemctl show "$service" -p MainPID --value)"
  "$python" "$source_dir/scripts/comprobar_despliegue.py" runtime --pid "$pid" --db "$db"
elif [ "$recover" = 1 ]; then
  state="$(systemctl show "$service" -p ActiveState --value)"
  [[ "$state" = inactive || "$state" = failed ]]
  test -f "$recovery_marker"
  mapfile -t recorded < "$recovery_marker"
  test "${#recorded[@]}" = 3
  test "${recorded[0]}" = "$db"
  test "${recorded[1]}" = "$(readlink -f "$current")"
  unit_hash="$(systemctl cat "$service" | sha256sum | cut -d ' ' -f 1)"
  test "${recorded[2]}" = "$unit_hash"
else
  echo "Servicio inactivo. Para recuperar un fallo registrado usa --recover." >&2
  exit 1
fi
previous=""
if [ -L "$current" ]; then previous="$(readlink -f "$current")"; fi
work="$(mktemp -d "$base/.build.XXXXXX")"
release="$(mktemp -d "$base/releases/${revision}.XXXXXX")"
install -d -m 0700 /var/backups/homelab
backup="$(mktemp -d "/var/backups/homelab/dashboard-$(date -u +%Y%m%dT%H%M%SZ).XXXXXX")"
cp -p "$unit" "$backup/unit"
cp -p "$caddy" "$backup/Caddyfile"
if [ -f "$recovery_marker" ]; then cp -p "$recovery_marker" "$backup/recovery-required"; fi
printf '%s\n' "$revision" > "$backup/revision"
stopped=0
switched=0
migration_started=0
migration_needed=1
caddy_changed=0

cleanup() {
  rm -rf -- "$work"
}
trap cleanup EXIT

rollback() {
  status="$1"
  trap - ERR INT TERM
  set +e
  echo "Despliegue fallido; copia y diagnostico: $backup" >&2
  if [ "$migration_started" = 1 ] && { [ "$migration_needed" = 1 ] || [ "$recover" = 1 ]; }; then
    systemctl stop "$service"
    echo "Se intento migrar: NO se restaura DB ni codigo incompatible automaticamente." >&2
    echo "Candidato conservado en $release. Se requiere recuperacion explicita." >&2
    exit "$status"
  fi
  if [ "$switched" = 1 ]; then
    systemctl stop "$service"
    if [ -n "$previous" ] && [ -d "$previous" ]; then
      ln -sfn "$previous" "$base/current.rollback"
      mv -Tf "$base/current.rollback" "$current"
    else
      rm -f "$current"
    fi
    cp -p "$backup/unit" "$unit"
    systemctl daemon-reload
    if [ -f "$backup/recovery-required" ]; then
      cp -p "$backup/recovery-required" "$recovery_marker"
    else
      rm -f "$recovery_marker"
    fi
  fi
  if [ "$caddy_changed" = 1 ]; then
    cp -p "$backup/Caddyfile" "$caddy"
    systemctl reload caddy || echo "No se pudo recuperar Caddy." >&2
  fi
  if [ "$stopped" = 1 ] && [ "$was_active" = 1 ]; then
    systemctl start "$service" || echo "No se pudo recuperar el servicio anterior." >&2
  fi
  echo "No se han restaurado ni eliminado datos de usuarios." >&2
  exit "$status"
}
trap 'rollback $?' ERR
trap 'rollback 130' INT
trap 'rollback 143' TERM

# Construir exactamente el commit, no los archivos editados del checkout.
git -c safe.directory="$repo_dir" -C "$repo_dir" archive "$revision" HomelabFrontend \
  | tar -x -C "$work"
package="$work/HomelabFrontend"
chmod 0755 "$work" "$release"
chown -R azureuser:azureuser "$work" "$release"
runuser -u azureuser -- "$python" -m venv "$release/.venv"
runuser -u azureuser -- "$release/.venv/bin/python" -m pip install --quiet \
  "$package[regime-notifications]"
runuser -u azureuser -- "$release/.venv/bin/python" -m pip list \
  --disable-pip-version-check --format=json > "$release/packages.json"
(
  cd "$package/frontend"
  runuser -u azureuser -- npm ci --no-audit --no-fund
  runuser -u azureuser -- npm run build
)
test -s "$package/frontend/dist/index.html"
install -d -m 0755 "$release/frontend"
cp -a "$package/frontend/dist" "$release/frontend/dist"
install -m 0644 "$package/scripts/comprobar_despliegue.py" "$release/comprobar_despliegue.py"
printf '%s\n' "$revision" > "$release/REVISION"
chown -R root:root "$release"
chmod -R go-w "$release"
helper="$release/comprobar_despliegue.py"
candidate_python="$release/.venv/bin/python"

# Nunca ejecutar migraciones/HTTP de prueba sobre rutas productivas.
source_schema="$("$candidate_python" "$helper" fingerprint "$db")"
"$candidate_python" "$helper" preflight --db "$db" --work "$work/preflight" \
  --dist "$release/frontend/dist" --require-regime
caddy validate --config "$package/Caddyfile" --adapter caddyfile
sed "s|$current|$release|g" "$package/systemd/homelab-dashboard.service" \
  > "$work/homelab-dashboard.service"
systemd-analyze verify "$work/homelab-dashboard.service"
target_revision="$("$candidate_python" -c 'from homelab_dashboard.migrate import head_revision; print(head_revision())')"
test -n "$target_revision"
test "$target_revision" != None

if [ "$prepare_only" = 1 ]; then
  trap - ERR INT TERM
  printf 'PREPARE_OK\nRevision: %s\nCandidato: %s\nSin cambios del servicio ni de su DB.\n' \
    "$revision" "$release"
  exit 0
fi
if [ "$was_active" = 1 ]; then
  pid="$(systemctl show "$service" -p MainPID --value)"
  "$candidate_python" "$helper" runtime --pid "$pid" --db "$db"
fi
test "$("$candidate_python" "$helper" fingerprint "$db")" = "$source_schema"
stopped=1
systemctl stop "$service"
"$candidate_python" "$helper" backup "$db" "$backup/dashboard.db"
before="$("$candidate_python" "$helper" fingerprint "$db")"
db_revision="$("$candidate_python" -c 'import sqlite3,sys; db=sqlite3.connect("file:"+sys.argv[1]+"?mode=ro",uri=True); print(",".join(row[0] for row in db.execute("SELECT version_num FROM alembic_version ORDER BY version_num"))); db.close()' "$db")"
if [ "$db_revision" = "$target_revision" ]; then migration_needed=0; fi
printf '%s\n' "$before" > "$backup/schema-before"
printf '%s\n' "$db_revision" > "$backup/database-revision"

switched=1
ln -sfn "$release" "$base/current.next"
mv -Tf "$base/current.next" "$current"
install -m 0644 "$package/systemd/homelab-dashboard.service" "$unit"
systemctl daemon-reload
unit_hash="$(systemctl cat "$service" | sha256sum | cut -d ' ' -f 1)"
printf '%s\n%s\n%s\n' "$db" "$release" "$unit_hash" > "$base/recovery.next"
mv -f "$base/recovery.next" "$recovery_marker"
migration_started=1
systemctl start "$service"
for attempt in $(seq 1 30); do
  if curl --max-time 2 --fail --silent http://127.0.0.1:8000/ -o "$work/index"; then break; fi
  sleep 1
done
systemctl is-active --quiet "$service"
pid="$(systemctl show "$service" -p MainPID --value)"
"$candidate_python" "$helper" runtime --pid "$pid" --db "$db"
curl --max-time 5 --fail --silent --show-error http://127.0.0.1:8000/ -o "$work/index"
cmp "$work/index" "$release/frontend/dist/index.html"
code="$(curl --max-time 5 --silent --show-error -o /dev/null -w '%{http_code}' \
  http://127.0.0.1:8000/api/v1/auth/me)"
test "$code" = 401

caddy_changed=1
install -m 0644 "$package/Caddyfile" "$caddy"
systemctl reload caddy
host="$(awk '/cloudapp.azure.com \{/ {print $1}' "$package/Caddyfile")"
[[ "$host" =~ ^[a-zA-Z0-9.-]+\.cloudapp\.azure\.com$ ]]
for path in / /trading /regimen; do
  curl --max-time 15 --fail --silent --show-error "https://$host$path" -o "$work/public"
  cmp "$work/public" "$release/frontend/dist/index.html"
done
for path in /api/v1/auth/me /api/v1/trading/bots; do
  code="$(curl --max-time 15 --silent --show-error -o /dev/null -w '%{http_code}' "https://$host$path")"
  test "$code" = 401
done
rm -f "$recovery_marker"
trap - ERR INT TERM
printf 'DEPLOY_OK\nRevision: %s\nRelease: %s\nBackup: %s\n' "$revision" "$release" "$backup"
echo "No se cambiaron configuraciones, permisos, consentimientos ni claves."
