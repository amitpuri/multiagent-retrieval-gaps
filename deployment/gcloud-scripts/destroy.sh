#!/usr/bin/env bash
# ==============================================================================
# Teardown Script for Google Cloud Agent Platform Deployment
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "${SCRIPT_DIR}/config.env" ]]; then
  # shellcheck disable=SC1091
  source "${SCRIPT_DIR}/config.env"
fi

PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null || true)}"
REGION="${REGION:-europe-west1}"
SERVICE_NAME="${SERVICE_NAME:-clinical-adk-agent}"
REPO_NAME="${REPO_NAME:-clinical-agents}"
FORCE="${FORCE:-false}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project|-p) PROJECT_ID="$2"; shift 2 ;;
    --region|-r) REGION="$2"; shift 2 ;;
    --service-name) SERVICE_NAME="$2"; shift 2 ;;
    --force|-f) FORCE=true; shift ;;
    *) shift ;;
  esac
done

echo "=============================================================================="
echo " TEARDOWN: Google Cloud Agent Platform [${SERVICE_NAME}] in [${REGION}]"
echo " Project: ${PROJECT_ID}"
echo "=============================================================================="

# 1. Delete Cloud Run Service(s)
for svc in "${SERVICE_NAME}" "clinical-agent-harness"; do
  if gcloud run services describe "${svc}" --region="${REGION}" --project="${PROJECT_ID}" &>/dev/null; then
    echo "Deleting Cloud Run service ${svc}..."
    gcloud run services delete "${svc}" --region="${REGION}" --project="${PROJECT_ID}" --quiet || true
    echo "[+] Service ${svc} deleted."
  fi
done

# 2. Optionally delete Artifact Registry
DELETE_REPO=false
if [[ "${FORCE}" == "true" ]]; then
  DELETE_REPO=true
else
  read -rp "Do you also want to delete the Artifact Registry repository '${REPO_NAME}'? (y/N) " confirm_repo
  if [[ "${confirm_repo}" =~ ^[Yy]$ ]]; then
    DELETE_REPO=true
  fi
fi

if [[ "${DELETE_REPO}" == "true" ]]; then
  echo "Deleting Artifact Registry ${REPO_NAME}..."
  gcloud artifacts repositories delete "${REPO_NAME}" \
    --location="${REGION}" \
    --project="${PROJECT_ID}" \
    --quiet || true
  echo "[+] Artifact Registry deleted."
fi

# 3. Optionally delete Secret Manager secret
DELETE_SEC=false
if [[ "${FORCE}" == "true" ]]; then
  DELETE_SEC=true
else
  read -rp "Do you also want to delete the Secret Manager secret 'clinical-gemini-api-key'? (y/N) " confirm_sec
  if [[ "${confirm_sec}" =~ ^[Yy]$ ]]; then
    DELETE_SEC=true
  fi
fi

if [[ "${DELETE_SEC}" == "true" ]]; then
  echo "Deleting Secret Manager secret clinical-gemini-api-key..."
  gcloud secrets delete "clinical-gemini-api-key" \
    --project="${PROJECT_ID}" \
    --quiet || true
  echo "[+] Secret deleted."
fi

echo "[+] GCP Teardown completed."
