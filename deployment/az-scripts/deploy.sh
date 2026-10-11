#!/usr/bin/env bash
# ==============================================================================
# Azure Container Apps & Azure AI Foundry Deployment Script for Multi-Agent CDS
# Deploys continuous FastAPI harness to Azure Container Apps with Azure AI Foundry
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Load configuration if present
if [[ -f "${SCRIPT_DIR}/config.env" ]]; then
  # shellcheck disable=SC1091
  source "${SCRIPT_DIR}/config.env"
fi

RESOURCE_GROUP="${RESOURCE_GROUP:-rg-clinical-agents}"
LOCATION="${LOCATION:-eastus}"
ENVIRONMENT_NAME="${ENVIRONMENT_NAME:-cae-clinical-agents}"
APP_NAME="${APP_NAME:-maf-clinical-agents}"
IMAGE_NAME="${IMAGE_NAME:-agent-framework}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
ACR_NAME="${ACR_NAME:-}"
AI_FOUNDRY_ACCOUNT_NAME="${AI_FOUNDRY_ACCOUNT_NAME:-ais-clinical-agents}"
AI_FOUNDRY_PROJECT_NAME="${AI_FOUNDRY_PROJECT_NAME:-aiproj-clinical-agents}"
AI_FOUNDRY_RESOURCE_GROUP="${AI_FOUNDRY_RESOURCE_GROUP:-rg-clinical-agents}"
FOUNDRY_MODEL="${FOUNDRY_MODEL:-gpt-6.1-sol}"          # config/models.yaml → deployments.azure.default
FOUNDRY_MODEL_VERSION="${FOUNDRY_MODEL_VERSION:-2026-09-29}"
FOUNDRY_SKU="${FOUNDRY_SKU:-GlobalStandard}"
PORT="${PORT:-8000}"
CPU="${CPU:-1.0}"
MEMORY="${MEMORY:-2.0Gi}"
MIN_REPLICAS="${MIN_REPLICAS:-0}"
MAX_REPLICAS="${MAX_REPLICAS:-5}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --resource-group|-g) RESOURCE_GROUP="$2"; shift 2 ;;
    --location|-l) LOCATION="$2"; shift 2 ;;
    --app-name) APP_NAME="$2"; shift 2 ;;
    --acr-name) ACR_NAME="$2"; shift 2 ;;
    --foundry-account) AI_FOUNDRY_ACCOUNT_NAME="$2"; shift 2 ;;
    --foundry-project) AI_FOUNDRY_PROJECT_NAME="$2"; shift 2 ;;
    --foundry-model) FOUNDRY_MODEL="$2"; shift 2 ;;
    *) shift ;;
  esac
done

echo "=============================================================================="
echo " Azure AI Foundry & Container Apps Deployment: ${APP_NAME}"
echo " Resource Group:     ${RESOURCE_GROUP}"
echo " Location:           ${LOCATION}"
echo " AI Foundry Account: ${AI_FOUNDRY_ACCOUNT_NAME} (${AI_FOUNDRY_RESOURCE_GROUP})"
echo " AI Foundry Project: ${AI_FOUNDRY_PROJECT_NAME}"
echo " Foundation Model:   ${FOUNDRY_MODEL}"
echo " Repo:               ${REPO_ROOT}"
echo "=============================================================================="

# 1. Verify Azure Authentication
echo "[1/7] Verifying Azure authentication..."
SUB_ID="$(az account show --query "id" -o tsv 2>/dev/null || true)"
SUB_NAME="$(az account show --query "name" -o tsv 2>/dev/null || true)"

if [[ -z "${SUB_ID}" ]]; then
  echo "[-] ERROR: Azure CLI is not authenticated. Please run 'az login' first."
  exit 1
fi
echo "[+] Active Subscription: ${SUB_NAME} (${SUB_ID})"

# 2. Create Resource Group
echo "[2/7] Ensuring Resource Group '${RESOURCE_GROUP}' exists..."
if ! az group show --name "${RESOURCE_GROUP}" &>/dev/null; then
  echo "    Creating Resource Group ${RESOURCE_GROUP} in ${LOCATION}..."
  az group create --name "${RESOURCE_GROUP}" --location "${LOCATION}" -o none
else
  echo "    Resource Group ${RESOURCE_GROUP} exists."
fi

# 3. Setup Azure Container Registry (ACR)
echo "[3/7] Setting up Azure Container Registry..."
if [[ -z "${ACR_NAME}" ]]; then
  UNIQUE_HASH="$(printf "%s" "${SUB_ID}" | md5sum | cut -c1-6)"
  ACR_NAME="acrclinagents${UNIQUE_HASH}"
fi

if ! az acr show --name "${ACR_NAME}" --resource-group "${RESOURCE_GROUP}" &>/dev/null; then
  echo "    Creating ACR '${ACR_NAME}' in ${RESOURCE_GROUP} (${LOCATION})..."
  if ! az acr create \
    --resource-group "${RESOURCE_GROUP}" \
    --name "${ACR_NAME}" \
    --sku Basic \
    --admin-enabled true \
    -o none; then
    echo "[-] ERROR: ACR creation failed in '${LOCATION}'."
    echo "    Try re-running with: --location eastus --resource-group rg-clinical-agents-eastus"
    exit 1
  fi
else
  echo "    ACR '${ACR_NAME}' exists."
fi

ACR_LOGIN_SERVER="$(az acr show --name "${ACR_NAME}" --query "loginServer" -o tsv)"
FULL_IMAGE_URI="${ACR_LOGIN_SERVER}/${IMAGE_NAME}:${IMAGE_TAG}"

# 4. Build and Push Container
echo "[4/7] Building and pushing container image: ${FULL_IMAGE_URI}..."
cd "${REPO_ROOT}"

BUILD_DONE=false
if command -v docker &>/dev/null && docker info &>/dev/null; then
  echo "    Local Docker daemon detected. Building locally and pushing to ACR..."
  az acr login --name "${ACR_NAME}"
  docker build -f agent-framework/Dockerfile -t "${FULL_IMAGE_URI}" .
  docker push "${FULL_IMAGE_URI}"
  BUILD_DONE=true
fi

if [[ "${BUILD_DONE}" != "true" ]]; then
  echo "    Building remotely using Azure Container Registry Tasks (az acr build)..."
  az acr build \
    --registry "${ACR_NAME}" \
    --image "${IMAGE_NAME}:${IMAGE_TAG}" \
    --file "agent-framework/Dockerfile" \
    .
fi
echo "[+] Image ready: ${FULL_IMAGE_URI}"

# 5. Azure AI Foundry Service & Project Discovery / Setup
echo "[5/7] Configuring Azure AI Foundry service and project..."
FOUNDRY_PROJECT_ENDPOINT=""
AZURE_OPENAI_ENDPOINT=""
AI_ACCOUNT_ID=""

TARGET_AI_RG="${AI_FOUNDRY_RESOURCE_GROUP:-${RESOURCE_GROUP}}"

if az cognitiveservices account show --name "${AI_FOUNDRY_ACCOUNT_NAME}" --resource-group "${TARGET_AI_RG}" &>/dev/null; then
  AI_ACCOUNT_ID="$(az cognitiveservices account show --name "${AI_FOUNDRY_ACCOUNT_NAME}" --resource-group "${TARGET_AI_RG}" --query "id" -o tsv)"
  AZURE_OPENAI_ENDPOINT="$(az cognitiveservices account show --name "${AI_FOUNDRY_ACCOUNT_NAME}" --resource-group "${TARGET_AI_RG}" --query "properties.endpoint" -o tsv)"
  echo "    Found Azure AI Services account: ${AI_FOUNDRY_ACCOUNT_NAME}"

  # Check project
  if az cognitiveservices account project show --name "${AI_FOUNDRY_ACCOUNT_NAME}" --resource-group "${TARGET_AI_RG}" --project-name "${AI_FOUNDRY_PROJECT_NAME}" &>/dev/null; then
    PROJ_JSON="$(az cognitiveservices account project show --name "${AI_FOUNDRY_ACCOUNT_NAME}" --resource-group "${TARGET_AI_RG}" --project-name "${AI_FOUNDRY_PROJECT_NAME}" -o json)"
    FOUNDRY_PROJECT_ENDPOINT="$(echo "${PROJ_JSON}" | grep -o 'https://[^"]*services.ai.azure.com/api/projects/[^"]*' | head -n1 || true)"
    echo "[+] Azure AI Foundry Project: ${AI_FOUNDRY_PROJECT_NAME}"
    echo "    Endpoint: ${FOUNDRY_PROJECT_ENDPOINT}"
  else
    echo "    Creating Azure AI Foundry Project '${AI_FOUNDRY_PROJECT_NAME}'..."
    AI_LOC="$(az cognitiveservices account show --name "${AI_FOUNDRY_ACCOUNT_NAME}" --resource-group "${TARGET_AI_RG}" --query "location" -o tsv)"
    az cognitiveservices account project create \
      --name "${AI_FOUNDRY_ACCOUNT_NAME}" \
      --resource-group "${TARGET_AI_RG}" \
      --project-name "${AI_FOUNDRY_PROJECT_NAME}" \
      --location "${AI_LOC}" \
      --description "Clinical Decision Support multi-agent project for Microsoft Agent Framework" \
      -o none
    PROJ_JSON="$(az cognitiveservices account project show --name "${AI_FOUNDRY_ACCOUNT_NAME}" --resource-group "${TARGET_AI_RG}" --project-name "${AI_FOUNDRY_PROJECT_NAME}" -o json)"
    FOUNDRY_PROJECT_ENDPOINT="$(echo "${PROJ_JSON}" | grep -o 'https://[^"]*services.ai.azure.com/api/projects/[^"]*' | head -n1 || true)"
  fi
else
  echo "    AI Foundry account '${AI_FOUNDRY_ACCOUNT_NAME}' not found. Creating in ${RESOURCE_GROUP} (${LOCATION})..."
  az cognitiveservices account create \
    --name "${AI_FOUNDRY_ACCOUNT_NAME}" \
    --resource-group "${RESOURCE_GROUP}" \
    --kind AIServices \
    --sku S0 \
    --location "${LOCATION}" \
    --yes -o none

  AI_ACCOUNT_ID="$(az cognitiveservices account show --name "${AI_FOUNDRY_ACCOUNT_NAME}" --resource-group "${RESOURCE_GROUP}" --query "id" -o tsv)"
  AZURE_OPENAI_ENDPOINT="$(az cognitiveservices account show --name "${AI_FOUNDRY_ACCOUNT_NAME}" --resource-group "${RESOURCE_GROUP}" --query "properties.endpoint" -o tsv)"

  echo "    Creating Azure AI Foundry Project '${AI_FOUNDRY_PROJECT_NAME}'..."
  az cognitiveservices account project create \
    --name "${AI_FOUNDRY_ACCOUNT_NAME}" \
    --resource-group "${RESOURCE_GROUP}" \
    --project-name "${AI_FOUNDRY_PROJECT_NAME}" \
    --location "${LOCATION}" \
    -o none

  echo "    Deploying foundation model '${FOUNDRY_MODEL}'..."
  az cognitiveservices account deployment create \
    --name "${AI_FOUNDRY_ACCOUNT_NAME}" \
    --resource-group "${RESOURCE_GROUP}" \
    --deployment-name "${FOUNDRY_MODEL}" \
    --model-name "${FOUNDRY_MODEL}" \
    --model-version "${FOUNDRY_MODEL_VERSION}" \
    --model-format OpenAI \
    --sku-capacity 10 \
    --sku-name "${FOUNDRY_SKU}" \
    -o none || {
      echo "[-] WARNING: model deployment '${FOUNDRY_MODEL}' (${FOUNDRY_MODEL_VERSION}, ${FOUNDRY_SKU}) failed."
      echo "    Check regional availability in '${LOCATION}' or set FOUNDRY_SKU / LOCATION (deployment/README.md)."
    }

  PROJ_JSON="$(az cognitiveservices account project show --name "${AI_FOUNDRY_ACCOUNT_NAME}" --resource-group "${RESOURCE_GROUP}" --project-name "${AI_FOUNDRY_PROJECT_NAME}" -o json)"
  FOUNDRY_PROJECT_ENDPOINT="$(echo "${PROJ_JSON}" | grep -o 'https://[^"]*services.ai.azure.com/api/projects/[^"]*' | head -n1 || true)"
fi

if [[ -z "${FOUNDRY_PROJECT_ENDPOINT}" ]]; then
  FOUNDRY_PROJECT_ENDPOINT="${AZURE_OPENAI_ENDPOINT}"
fi
echo "[+] AI Foundry Endpoint active: ${FOUNDRY_PROJECT_ENDPOINT}"

# 6. Create Container Apps Managed Environment
echo "[6/7] Ensuring Container Apps Environment '${ENVIRONMENT_NAME}' exists..."
if ! az containerapp env show --name "${ENVIRONMENT_NAME}" --resource-group "${RESOURCE_GROUP}" &>/dev/null; then
  echo "    Creating Container Apps Environment..."
  if ! az containerapp env create \
    --name "${ENVIRONMENT_NAME}" \
    --resource-group "${RESOURCE_GROUP}" \
    --location "${LOCATION}" \
    -o none; then
    echo "[-] ERROR: Container Apps Environment creation failed in '${LOCATION}'."
    echo "    Try re-running with: --location eastus"
    exit 1
  fi
else
  echo "    Environment '${ENVIRONMENT_NAME}' exists."
fi

# 7. Deploy Container App with Managed Identity & RBAC
echo "[7/7] Deploying Azure Container App '${APP_NAME}' with Managed Identity..."
ACR_PASS="$(az acr credential show --name "${ACR_NAME}" --query "passwords[0].value" -o tsv)"
ACR_USER="$(az acr credential show --name "${ACR_NAME}" --query "username" -o tsv)"

ENV_VARS_LIST=(
  "ALLOWED_ORIGINS=*"
  "MAX_SESSIONS=1000"
  "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT=${FOUNDRY_PROJECT_ENDPOINT}"
  "FOUNDRY_MODEL=${FOUNDRY_MODEL}"
  "AZURE_OPENAI_ENDPOINT=${AZURE_OPENAI_ENDPOINT}"
  "AZURE_SUBSCRIPTION_ID=${SUB_ID}"
)
if [[ -n "${OPENAI_API_KEY:-}" ]]; then ENV_VARS_LIST+=("OPENAI_API_KEY=${OPENAI_API_KEY}"); fi

if ! az containerapp show --name "${APP_NAME}" --resource-group "${RESOURCE_GROUP}" &>/dev/null; then
  echo "    Creating new Container App '${APP_NAME}' with System-Assigned Identity..."
  az containerapp create \
    --name "${APP_NAME}" \
    --resource-group "${RESOURCE_GROUP}" \
    --environment "${ENVIRONMENT_NAME}" \
    --image "${FULL_IMAGE_URI}" \
    --target-port "${PORT}" \
    --ingress external \
    --registry-server "${ACR_LOGIN_SERVER}" \
    --registry-username "${ACR_USER}" \
    --registry-password "${ACR_PASS}" \
    --system-assigned \
    --cpu "${CPU}" \
    --memory "${MEMORY}" \
    --min-replicas "${MIN_REPLICAS}" \
    --max-replicas "${MAX_REPLICAS}" \
    --env-vars "${ENV_VARS_LIST[@]}" \
    -o none
else
  echo "    Container App exists. Updating revision..."
  az containerapp update \
    --name "${APP_NAME}" \
    --resource-group "${RESOURCE_GROUP}" \
    --image "${FULL_IMAGE_URI}" \
    --set-env-vars "${ENV_VARS_LIST[@]}" \
    -o none
  az containerapp identity assign --name "${APP_NAME}" --resource-group "${RESOURCE_GROUP}" --system-assigned -o none 2>/dev/null || true
fi

APP_PRINCIPAL_ID="$(az containerapp show --name "${APP_NAME}" --resource-group "${RESOURCE_GROUP}" --query "identity.principalId" -o tsv 2>/dev/null || true)"
if [[ -n "${APP_PRINCIPAL_ID}" && -n "${AI_ACCOUNT_ID}" ]]; then
  echo "    Assigning RBAC: 'Cognitive Services OpenAI User' to Container App Identity (${APP_PRINCIPAL_ID})..."
  az role assignment create \
    --assignee-object-id "${APP_PRINCIPAL_ID}" \
    --assignee-principal-type "ServicePrincipal" \
    --role "Cognitive Services OpenAI User" \
    --scope "${AI_ACCOUNT_ID}" \
    -o none 2>/dev/null || true
  echo "[+] Keyless RBAC granted for Azure AI Foundry access."
fi

APP_FQDN="$(az containerapp show --name "${APP_NAME}" --resource-group "${RESOURCE_GROUP}" --query "properties.configuration.ingress.fqdn" -o tsv 2>/dev/null || true)"
APP_URL="https://${APP_FQDN}"

echo ""
echo "=============================================================================="
echo " AZURE AI FOUNDRY DEPLOYMENT SUCCESSFUL!"
echo " App Name:            ${APP_NAME}"
echo " AI Foundry Project:  ${AI_FOUNDRY_PROJECT_NAME} (${AI_FOUNDRY_ACCOUNT_NAME})"
echo " AI Foundry Endpoint: ${FOUNDRY_PROJECT_ENDPOINT}"
echo " Model:               ${FOUNDRY_MODEL}"
echo " Service URL:         ${APP_URL}"
echo " Liveness:            ${APP_URL}/healthz"
echo " Readiness:           ${APP_URL}/readyz"
echo " Docs:                ${APP_URL}/docs"
echo " Managed Identity:    ${APP_PRINCIPAL_ID}"
echo "=============================================================================="
