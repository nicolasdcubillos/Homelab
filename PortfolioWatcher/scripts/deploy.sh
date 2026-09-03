#!/usr/bin/env bash
# Syncs PortfolioWatcher's code to the VM, installs it into its venv, and
# installs/enables the systemd timers that drive the daily and weekly runs.
#
# Usage: ./scripts/deploy.sh <vm-ip-or-host> [ssh-user]
#
# Requires scripts/bootstrap_vm.sh to have been run once already, and a
# populated .env in the repo root (it is copied to the VM but never
# committed to git -- see .gitignore).
set -euo pipefail

VM_HOST="${1:?usage: deploy.sh <vm-ip-or-host> [ssh-user]}"
SSH_USER="${2:-azureuser}"
SERVICE_DIR="/opt/services/portfoliowatcher"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "== Syncing code to ${VM_HOST}:${SERVICE_DIR} =="
rsync -az --delete \
  --exclude ".venv" --exclude ".git" --exclude "data" --exclude "__pycache__" \
  --exclude ".pytest_cache" --exclude ".ruff_cache" \
  "${REPO_ROOT}/" "${SSH_USER}@${VM_HOST}:${SERVICE_DIR}/"

if [ -f "${REPO_ROOT}/.env" ]; then
  echo "== Copying .env (not tracked in git) =="
  scp "${REPO_ROOT}/.env" "${SSH_USER}@${VM_HOST}:${SERVICE_DIR}/.env"
else
  echo "WARNING: no local .env found; the VM's existing .env (if any) is left untouched."
fi

ssh "${SSH_USER}@${VM_HOST}" bash -s <<REMOTE
set -euo pipefail
cd "${SERVICE_DIR}"

echo "== Installing/upgrading the package into the venv =="
"${SERVICE_DIR}/.venv/bin/pip" install -q -U pip
"${SERVICE_DIR}/.venv/bin/pip" install -q -e ".[azure]"

echo "== Writing systemd units (service-specific names to avoid clashing with other services on this VM) =="

sudo tee /etc/systemd/system/portfoliowatcher-daily.service > /dev/null <<'UNIT'
[Unit]
Description=PortfolioWatcher daily risk/opportunity subscription

[Service]
Type=oneshot
WorkingDirectory=/opt/services/portfoliowatcher
EnvironmentFile=/opt/services/portfoliowatcher/.env
ExecStart=/opt/services/portfoliowatcher/.venv/bin/portfoliowatcher daily
UNIT

# Runs twice a day: ~08:45 and ~16:15 America/New_York (pre-open / post-close).
sudo tee /etc/systemd/system/portfoliowatcher-daily.timer > /dev/null <<'UNIT'
[Unit]
Description=Run portfoliowatcher-daily.service twice a day (NY pre-open/post-close)

[Timer]
OnCalendar=*-*-* 08:45:00 America/New_York
OnCalendar=*-*-* 16:15:00 America/New_York
Persistent=true

[Install]
WantedBy=timers.target
UNIT

sudo tee /etc/systemd/system/portfoliowatcher-weekly.service > /dev/null <<'UNIT'
[Unit]
Description=PortfolioWatcher full portfolio analysis

[Service]
Type=oneshot
WorkingDirectory=/opt/services/portfoliowatcher
EnvironmentFile=/opt/services/portfoliowatcher/.env
ExecStart=/opt/services/portfoliowatcher/.venv/bin/portfoliowatcher weekly
UNIT

# The service itself checks analysis_interval_days (default 7) and skips if
# not due yet, so this timer can simply run daily and let the app decide.
sudo tee /etc/systemd/system/portfoliowatcher-weekly.timer > /dev/null <<'UNIT'
[Unit]
Description=Check daily whether a full portfolio analysis is due

[Timer]
OnCalendar=*-*-* 09:00:00 America/New_York
Persistent=true

[Install]
WantedBy=timers.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable --now portfoliowatcher-daily.timer
sudo systemctl enable --now portfoliowatcher-weekly.timer

echo "Deployed. Check status with:"
echo "  systemctl list-timers | grep portfoliowatcher"
echo "  journalctl -u portfoliowatcher-daily.service"
REMOTE
