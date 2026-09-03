#!/usr/bin/env bash
# Bootstraps a fresh Ubuntu VM with Python 3.11 and the OS packages
# PortfolioWatcher needs. Safe to re-run.
#
# Usage: ./scripts/bootstrap_vm.sh <vm-ip-or-host> [ssh-user]
#
# This only prepares the machine (python, venv, service directory). It does
# NOT copy code or start any timers -- run scripts/deploy.sh afterwards for
# that.
set -euo pipefail

VM_HOST="${1:?usage: bootstrap_vm.sh <vm-ip-or-host> [ssh-user]}"
SSH_USER="${2:-azureuser}"

# PortfolioWatcher lives in its own subdirectory under /opt/services/ because
# this VM is meant to host more personal services over time, not just this
# one project.
SERVICE_DIR="/opt/services/portfoliowatcher"

ssh "${SSH_USER}@${VM_HOST}" bash -s <<REMOTE
set -euo pipefail

echo "== Updating apt and installing Python 3.11 + build deps =="
sudo apt-get update -y
sudo apt-get install -y \\
  software-properties-common \\
  python3.11 python3.11-venv python3.11-dev \\
  git rsync

echo "== Creating service directory ${SERVICE_DIR} =="
sudo mkdir -p ${SERVICE_DIR}
sudo chown "\$(whoami)":"\$(whoami)" ${SERVICE_DIR}

echo "== Creating Python virtualenv =="
if [ ! -d "${SERVICE_DIR}/.venv" ]; then
  python3.11 -m venv "${SERVICE_DIR}/.venv"
fi

echo "Bootstrap complete. Next: run scripts/deploy.sh to sync code and enable timers."
REMOTE
