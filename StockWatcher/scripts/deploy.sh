#!/usr/bin/env bash
#
# Build -> push to ACR -> apply the Terraform.
#
#   ./scripts/deploy.sh
#   IMAGE_TAG=v2 ./scripts/deploy.sh
#
# Safe to re-run: the first pass creates the resource group and registry, later
# passes just push a new image tag and update the job.
#
# Everything except the image tag is configured in infra/terraform.tfvars --
# this script deliberately does not pass -var for name/location/etc, so your
# tfvars stays the single source of truth.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INFRA_DIR="$REPO_ROOT/infra"
IMAGE_TAG="${IMAGE_TAG:-$(date -u +%Y%m%d%H%M%S)}"

cd "$REPO_ROOT"

log() { printf '\n\033[1;34m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

command -v az >/dev/null || die "azure-cli is not installed (https://aka.ms/azure-cli)"
command -v terraform >/dev/null || die "terraform is not installed (https://developer.hashicorp.com/terraform/install)"
az account show >/dev/null 2>&1 || die "not logged in; run 'az login'"

[ -f "$INFRA_DIR/terraform.tfvars" ] || die \
  "infra/terraform.tfvars not found; copy infra/terraform.tfvars.example and edit it"

tf() { terraform -chdir="$INFRA_DIR" "$@"; }

log "terraform init"
tf init -input=false

# The image does not exist yet on the very first run, so we cannot apply the
# whole config in one go and then build -- the registry has to exist first.
# -target is normally a smell, but this is exactly the bootstrap case it is for,
# and it is a no-op on every subsequent run.
log "Ensuring the registry exists"
tf apply -input=false -auto-approve \
  -target=azurerm_container_registry.this \
  -var "image_tag=${IMAGE_TAG}"

REGISTRY_NAME=$(tf output -raw registry_name)
IMAGE=$(tf output -raw image)
[ -n "$REGISTRY_NAME" ] && [ -n "$IMAGE" ] || die \
  "the bootstrap apply did not produce registry outputs; run 'terraform -chdir=infra apply' by hand to see why"
# Strip the login server: `az acr build --image` wants "repo:tag".
REPO_AND_TAG="${IMAGE#*/}"

# az acr build builds server-side, which avoids needing docker locally and
# sidesteps the Apple Silicon problem -- Container Apps is amd64 only, and an
# arm64 image would produce a job that cannot start.
log "Building ${IMAGE} in ACR"
az acr build \
  --registry "$REGISTRY_NAME" \
  --image "$REPO_AND_TAG" \
  --platform linux/amd64 \
  --file Dockerfile \
  .

log "terraform apply"
tf apply -input=false -auto-approve -var "image_tag=${IMAGE_TAG}"

RESOURCE_GROUP=$(tf output -raw resource_group_name)
JOB_NAME=$(tf output -raw job_name)

log "Deployed."
cat <<EOF

  Job:      ${JOB_NAME}
  Image:    ${IMAGE}

  Run it now:      az containerapp job start -g ${RESOURCE_GROUP} -n ${JOB_NAME}
  Watch logs:      az containerapp job execution list -g ${RESOURCE_GROUP} -n ${JOB_NAME} -o table
  Change cadence:  edit cron_expression in infra/terraform.tfvars and re-run this script

  Still to do by hand (needs interactive Meta consent, no API equivalent):
    1. Portal -> Communication Services -> Advanced Messaging -> connect WhatsApp
    2. Put the channel GUID in whatsapp_channel_registration_id in
       infra/terraform.tfvars
    3. Submit the template in docs/whatsapp-template.md, then re-run this script
EOF
