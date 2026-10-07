#!/usr/bin/env bash
# ==============================================================================
# Service Health & Scenario Verification for Google Cloud Agent Platform
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

SERVICE_URL="${1:-}"
if [[ -z "${SERVICE_URL}" ]]; then
  for svc in "${SERVICE_NAME}" "clinical-agent-harness"; do
    URL="$(gcloud run services describe "${svc}" --platform=managed --region="${REGION}" --project="${PROJECT_ID}" --format="value(status.url)" 2>/dev/null || true)"
    if [[ -n "${URL}" ]]; then
      SERVICE_URL="${URL}"
      break
    fi
  done
fi

if [[ -z "${SERVICE_URL}" ]]; then
  echo "[-] ERROR: Could not determine Cloud Run service URL."
  echo "    Usage: $0 [SERVICE_URL]"
  exit 1
fi

echo "=============================================================================="
echo " Testing Clinical Agent Platform at: ${SERVICE_URL}"
echo "=============================================================================="

echo -e "\n[1/4] Testing Liveness (/healthz)..."
curl -sS -f "${SERVICE_URL}/healthz" | jq . 2>/dev/null || curl -sS "${SERVICE_URL}/healthz"

echo -e "\n[2/4] Testing Readiness & MCP Discovery (/readyz)..."
curl -sS -f "${SERVICE_URL}/readyz" | jq . 2>/dev/null || curl -sS "${SERVICE_URL}/readyz"

echo -e "\n[3/4] Creating Turn Session (/api/v1/sessions)..."
SESSION_RESP="$(curl -sS -X POST "${SERVICE_URL}/api/v1/sessions")"
echo "${SESSION_RESP}"
SESSION_ID="$(echo "${SESSION_RESP}" | grep -o '"session_id":"[^"]*' | cut -d'"' -f4 || true)"

echo -e "\n[4/4] Sending Scenario A Clinician Turn: 'Hb 13.5 | g/dL'..."
QUERY_PAYLOAD='{"prompt": "Hb 13.5 | g/dL", "user_id": "dr_puri"}'
if [[ -n "${SESSION_ID}" ]]; then
  QUERY_PAYLOAD="{\"prompt\": \"Hb 13.5 | g/dL\", \"session_id\": \"${SESSION_ID}\", \"user_id\": \"dr_puri\"}"
fi

curl -sS -X POST "${SERVICE_URL}/api/v1/query" \
  -H "Content-Type: application/json" \
  -d "${QUERY_PAYLOAD}" | jq . 2>/dev/null || curl -sS -X POST "${SERVICE_URL}/api/v1/query" -H "Content-Type: application/json" -d "${QUERY_PAYLOAD}"

echo -e "\n[+] Tests completed successfully."
