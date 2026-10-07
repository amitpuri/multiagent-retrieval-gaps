#!/usr/bin/env bash
# ==============================================================================
# Service Health & Scenario Verification for AWS Agent Deployment
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "${SCRIPT_DIR}/config.env" ]]; then
  # shellcheck disable=SC1091
  source "${SCRIPT_DIR}/config.env"
fi

AWS_REGION="${AWS_REGION:-us-east-1}"
SERVICE_NAME="${SERVICE_NAME:-clinical-strands-agent}"

SERVICE_URL="${1:-}"
if [[ -z "${SERVICE_URL}" ]]; then
  for name in "${SERVICE_NAME}" "strands-clinical-agents" "clinical-agent-harness"; do
    SERVICE_ARN="$(aws apprunner list-services --region "${AWS_REGION}" --query "ServiceSummaryList[?ServiceName=='${name}'].ServiceArn" --output text 2>/dev/null || true)"
    if [[ -n "${SERVICE_ARN}" && "${SERVICE_ARN}" != "None" ]]; then
      SERVICE_URL="https://$(aws apprunner describe-service --service-arn "${SERVICE_ARN}" --region "${AWS_REGION}" --query "Service.ServiceUrl" --output text 2>/dev/null || true)"
      break
    fi
  done
fi

if [[ -z "${SERVICE_URL}" || "${SERVICE_URL}" == "https://" ]]; then
  echo "[-] ERROR: Could not determine App Runner service URL."
  echo "    Usage: $0 [SERVICE_URL]"
  exit 1
fi

echo "=============================================================================="
echo " Testing Clinical Agent Harness at: ${SERVICE_URL}"
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
