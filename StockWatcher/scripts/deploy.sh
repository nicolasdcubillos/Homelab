#!/usr/bin/env bash
#
# Build -> push to ACR -> deploy the Container Apps Job.
#
#   ./scripts/deploy.sh
#   RESOURCE_GROUP=my-rg LOCATION=westus3 ./scripts/deploy.sh
#
# Safe to re-run: the first pass creates the registry, subsequent passes just
# push a new image tag and update the job.

set -euo pipefail

RESOURCE_GROUP="${RESOURCE_GROUP:-stockwatcher-rg}"
LOCATION="${LOCATION:-eastus}"
NAME="${NAME:-stockwatcher}"
IMAGE_TAG="${IMAGE_TAG:-$(date -u +%Y%m%d%H%M%S)}"
PARAMETERS_FILE="${PARAMETERS_FILE:-infra/main.parameters.json}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$REPO_ROOT"

log() { printf '\n\033[1;34m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

command -v az >/dev/null || die "azure-cli is not installed (https://aka.ms/azure-cli)"
command -v docker >/dev/null || die "docker is not installed"
az account show >/dev/null 2>&1 || die "not logged in; run 'az login'"

log "Resource group ${RESOURCE_GROUP} (${LOCATION})"
az group create --name "$RESOURCE_GROUP" --location "$LOCATION" --output none

# Pass 1 provisions the registry and everything else.  The image does not exist
# yet, so the job is created pointing at a tag we are about to push; Container
# Apps only pulls when the schedule fires, so this ordering is fine.
log "Deploying infrastructure (this creates the ACR on first run)"
az deployment group create \
  --resource-group "$RESOURCE_GROUP" \
  --template-file infra/main.bicep \
  --parameters "@${PARAMETERS_FILE}" \
  --parameters name="$NAME" imageTag="$IMAGE_TAG" \
  --output none

REGISTRY_NAME=$(az deployment group show \
  --resource-group "$RESOURCE_GROUP" --name main \
  --query properties.outputs.registryName.value --output tsv)
LOGIN_SERVER=$(az deployment group show \
  --resource-group "$RESOURCE_GROUP" --name main \
  --query properties.outputs.registryLoginServer.value --output tsv)
JOB_NAME=$(az deployment group show \
  --resource-group "$RESOURCE_GROUP" --name main \
  --query properties.outputs.jobName.value --output tsv)

IMAGE="${LOGIN_SERVER}/${NAME}:${IMAGE_TAG}"

log "Building ${IMAGE}"
# --platform matters: Container Apps is amd64 and an Apple Silicon build would
# produce an image the job cannot start.
docker build --platform linux/amd64 -t "$IMAGE" .

log "Pushing to ${LOGIN_SERVER}"
az acr login --name "$REGISTRY_NAME" --output none
docker push "$IMAGE"

# Pass 2 points the job at the image that now actually exists.
log "Pointing job at the new image"
az deployment group create \
  --resource-group "$RESOURCE_GROUP" \
  --template-file infra/main.bicep \
  --parameters "@${PARAMETERS_FILE}" \
  --parameters name="$NAME" imageTag="$IMAGE_TAG" \
  --output none

log "Deployed."
cat <<EOF

  Job:      ${JOB_NAME}
  Image:    ${IMAGE}

  Run it now:      az containerapp job start -g ${RESOURCE_GROUP} -n ${JOB_NAME}
  Watch logs:      az containerapp job execution list -g ${RESOURCE_GROUP} -n ${JOB_NAME} -o table
  Change cadence:  edit cronExpression in ${PARAMETERS_FILE} and re-run this script

  Still to do by hand (needs interactive Meta consent, no ARM equivalent):
    1. Portal -> Communication Services -> Advanced Messaging -> connect WhatsApp
    2. Put the channel GUID in whatsappChannelRegistrationId in ${PARAMETERS_FILE}
    3. Submit the template in docs/whatsapp-template.md, then re-run this script
EOF
