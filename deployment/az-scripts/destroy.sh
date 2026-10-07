#!/usr/bin/env bash
# ==============================================================================
# Teardown Script for Azure Deployment
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "${SCRIPT_DIR}/config.env" ]]; then
  # shellcheck disable=SC1091
  source "${SCRIPT_DIR}/config.env"
fi

RESOURCE_GROUP="${RESOURCE_GROUP:-rg-clinical-agents}"
APP_NAME="${APP_NAME:-maf-clinical-agents}"
FORCE="${FORCE:-false}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --resource-group|-g) RESOURCE_GROUP="$2"; shift 2 ;;
    --app-name) APP_NAME="$2"; shift 2 ;;
    --force|-f) FORCE=true; shift ;;
    *) shift ;;
  esac
done

echo "=============================================================================="
echo " TEARDOWN: Azure Resources in Resource Group [${RESOURCE_GROUP}]"
echo "=============================================================================="

DELETE_RG=false
if [[ "${FORCE}" == "true" ]]; then
  DELETE_RG=true
else
  echo "Option 1: Delete only the Container App '${APP_NAME}'."
  echo "Option 2: Delete the entire Resource Group '${RESOURCE_GROUP}' (App, Registry, Environment)."
  echo ""
  read -rp "Delete the entire Resource Group '${RESOURCE_GROUP}'? (y/N) " confirm_rg
  if [[ "${confirm_rg}" =~ ^[Yy]$ ]]; then
    DELETE_RG=true
  fi
fi

if [[ "${DELETE_RG}" == "true" ]]; then
  echo "Deleting Resource Group ${RESOURCE_GROUP} (this may take 2-3 minutes)..."
  az group delete --name "${RESOURCE_GROUP}" --yes --no-wait
  echo "[+] Resource group deletion initiated."
else
  for app in "${APP_NAME}" "clinical-agent-harness"; do
    if az containerapp show --name "${app}" --resource-group "${RESOURCE_GROUP}" &>/dev/null; then
      echo "Deleting Container App ${app}..."
      az containerapp delete --name "${app}" --resource-group "${RESOURCE_GROUP}" --yes || true
      echo "[+] Container App ${app} deleted."
    fi
  done
fi

echo "[+] Azure Teardown complete."
