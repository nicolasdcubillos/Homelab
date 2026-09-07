#!/usr/bin/env bash
# Instala una version aislada sin modificar el checkout ni el venv del dashboard.
set -Eeuo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "Ejecuta este script con sudo." >&2
  exit 1
fi

source_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
repo_dir="$(dirname "$source_dir")"
revision="${1:?Uso: deploy.sh <commit SHA completo>}"
if [[ ! "$revision" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Se requiere un SHA completo." >&2
  exit 1
fi
actual="$(git -c safe.directory="$repo_dir" -C "$repo_dir" rev-parse HEAD)"
if [ "$actual" != "$revision" ]; then
  echo "El checkout no corresponde al SHA solicitado." >&2
  exit 1
fi
python="${TRADINGLAB_PYTHON:-python3}"
"$python" -c 'import sys; assert sys.version_info >= (3, 10), "Se necesita Python >= 3.10"'
systemctl is-active --quiet homelab-dashboard.service
test -f /opt/services/homelab/HomelabFrontend/dashboard.db

base=/opt/services/tradinglab
current="$base/current"
unit=/etc/systemd/system/tradinglab.service
dropin=/etc/systemd/system/homelab-dashboard.service.d/tradinglab.conf
install -d -m 0755 "$base/releases"
exec 9>"$base/deploy.lock"
if ! flock -n 9; then
  echo "Ya hay otro despliegue de TradingLab en curso." >&2
  exit 1
fi
install -d -m 0700 /var/lib/tradinglab /etc/tradinglab
if [ -e "$current" ] && [ ! -L "$current" ]; then
  echo "$current debe ser un enlace de despliegue, no un directorio." >&2
  exit 1
fi
previous="$(readlink -f "$current" || true)"
release="$(mktemp -d "$base/releases/${revision}.XXXXXX")"
chmod 0755 "$release"
backup="$(mktemp -d)"
if [ -f "$unit" ]; then cp -p "$unit" "$backup/unit"; fi
if [ -f "$dropin" ]; then cp -p "$dropin" "$backup/dropin"; fi
switched=0
dashboard_changed=0

rollback() {
  status=$?
  trap - ERR
  set +e
  echo "Fallo de despliegue; restaurando la version anterior (codigo $status)." >&2
  if [ "$switched" = 1 ]; then
    systemctl stop tradinglab.service
    if [ -n "$previous" ] && [ -d "$previous" ]; then
      ln -sfn "$previous" "$base/current.rollback"
      mv -Tf "$base/current.rollback" "$current"
    else
      rm -f "$current"
      systemctl disable tradinglab.service
    fi
    if [ -f "$backup/unit" ]; then cp -p "$backup/unit" "$unit"; else rm -f "$unit"; fi
    if [ -f "$backup/dropin" ]; then cp -p "$backup/dropin" "$dropin"; else rm -f "$dropin"; fi
    systemctl daemon-reload
    if [ -n "$previous" ] && [ -f "$unit" ]; then systemctl start tradinglab.service; fi
    if [ "$dashboard_changed" = 1 ]; then systemctl restart homelab-dashboard.service; fi
  fi
  echo "La base de datos se conserva. Inspecciona journalctl -u tradinglab.service." >&2
  rm -rf "$backup"
  exit "$status"
}
trap rollback ERR

"$python" -m venv "$release/.venv"
# Solo el nucleo: no descargar SDKs pesados para un adaptador aun bloqueado.
"$release/.venv/bin/python" -m pip install --quiet "$source_dir"
install -m 0644 "$source_dir/scripts/comprobar_despliegue.py" "$release/comprobar_despliegue.py"
"$release/.venv/bin/tradinglab" --version

ln -sfn "$release" "$base/current.next"
mv -Tf "$base/current.next" "$current"
switched=1
install -m 0644 "$source_dir/systemd/tradinglab.service" "$unit"
systemd-analyze verify "$unit"
systemctl daemon-reload
desde="$(date +%s)"
systemctl restart tradinglab.service
"$release/.venv/bin/python" "$release/comprobar_despliegue.py" \
  --db /var/lib/tradinglab/tradinglab.db --desde "$desde"
systemctl is-active --quiet tradinglab.service

install -d -m 0755 "$(dirname "$dropin")"
install -m 0644 "$source_dir/systemd/dashboard-tradinglab.conf" "$dropin"
dashboard_changed=1
systemctl daemon-reload
systemctl restart homelab-dashboard.service
for intento in $(seq 1 30); do
  if curl --max-time 3 --fail --silent http://127.0.0.1:8000/ -o /dev/null; then break; fi
  sleep 2
done
curl --max-time 5 --fail --silent http://127.0.0.1:8000/ -o /dev/null
code="$(curl --max-time 5 --silent -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/api/v1/auth/me)"
test "$code" = 401
systemctl enable tradinglab.service
trap - ERR
rm -rf "$backup"
printf 'Version instalada: %s\nAnterior: %s\n' "$release" "${previous:-ninguna}"
echo "No se han cambiado instrumentos, capital ni la intencion de encendido."
