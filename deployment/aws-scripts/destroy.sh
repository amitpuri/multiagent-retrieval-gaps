#!/usr/bin/env bash
# ==============================================================================
# Teardown Script for AWS Bedrock AgentCore Deployment
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "${SCRIPT_DIR}/config.env" ]]; then
  # shellcheck disable=SC1091
  source "${SCRIPT_DIR}/config.env"
fi

AWS_REGION="${AWS_REGION:-us-east-1}"
AGENT_NAME="${AGENT_NAME:-clinical-strands-agent}"
ECR_REPO_NAME="${ECR_REPO_NAME:-strands-clinical-agents}"
AGENT_ROLE_NAME="${AGENT_ROLE_NAME:-BedrockAgentCoreExecutionRole}"
MEMORY_NAME="${MEMORY_NAME:-clinical-agent-memory}"
FORCE="${FORCE:-false}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --region) AWS_REGION="$2"; shift 2 ;;
    --agent-name) AGENT_NAME="$2"; shift 2 ;;
    --force|-f) FORCE=true; shift ;;
    *) shift ;;
  esac
done

echo "=============================================================================="
echo " TEARDOWN: AWS Bedrock AgentCore [${AGENT_NAME}] in [${AWS_REGION}]"
echo "=============================================================================="

# 1. Delete AgentCore Runtime
RUNTIMES="$(aws bedrock-agentcore list-agent-runtimes --region "${AWS_REGION}" --output json 2>/dev/null || true)"
if [[ -n "${RUNTIMES}" ]] && echo "${RUNTIMES}" | grep -q "\"${AGENT_NAME}\""; then
  RUNTIME_ID="$(echo "${RUNTIMES}" | grep -B2 "\"${AGENT_NAME}\"" | grep -o '"agentRuntimeId": *"[^"]*"' | head -n1 | cut -d'"' -f4 || true)"
  if [[ -n "${RUNTIME_ID}" ]]; then
    echo "Deleting AgentCore runtime: ${RUNTIME_ID}..."
    aws bedrock-agentcore delete-agent-runtime --agent-runtime-id "${RUNTIME_ID}" --region "${AWS_REGION}" || true
    echo "[+] AgentCore runtime deleted."
  fi
else
  echo "AgentCore runtime '${AGENT_NAME}' not found."
fi

# 2. Delete App Runner fallback service (if exists)
SERVICE_ARN="$(aws apprunner list-services --region "${AWS_REGION}" --query "ServiceSummaryList[?ServiceName=='${AGENT_NAME}'].ServiceArn" --output text 2>/dev/null || true)"
if [[ -n "${SERVICE_ARN}" && "${SERVICE_ARN}" != "None" ]]; then
  echo "Deleting App Runner fallback service ${AGENT_NAME}..."
  aws apprunner delete-service --service-arn "${SERVICE_ARN}" --region "${AWS_REGION}" --output json >/dev/null || true
  echo "[+] App Runner service deleted."
fi

# 3. Delete AgentCore Memory Resource
MEMORIES="$(aws bedrock-agentcore list-memory-resources --region "${AWS_REGION}" --output json 2>/dev/null || true)"
if [[ -n "${MEMORIES}" ]] && echo "${MEMORIES}" | grep -q "\"${MEMORY_NAME}\""; then
  MEM_ID="$(echo "${MEMORIES}" | grep -B2 "\"${MEMORY_NAME}\"" | grep -o '"memoryId": *"[^"]*"' | head -n1 | cut -d'"' -f4 || true)"
  if [[ -n "${MEM_ID}" ]]; then
    echo "Deleting AgentCore memory resource: ${MEM_ID}..."
    aws bedrock-agentcore delete-memory-resource --memory-id "${MEM_ID}" --region "${AWS_REGION}" || true
    echo "[+] Memory resource deleted."
  fi
fi

# 4. Delete ECR repository
DELETE_ECR=false
if [[ "${FORCE}" == "true" ]]; then
  DELETE_ECR=true
else
  read -rp "Delete ECR repository '${ECR_REPO_NAME}'? (y/N) " confirm_ecr
  if [[ "${confirm_ecr}" =~ ^[Yy]$ ]]; then
    DELETE_ECR=true
  fi
fi

if [[ "${DELETE_ECR}" == "true" ]]; then
  echo "Deleting ECR repository ${ECR_REPO_NAME}..."
  aws ecr delete-repository --repository-name "${ECR_REPO_NAME}" --region "${AWS_REGION}" --force --output json >/dev/null 2>&1 || true
  echo "[+] ECR repository deleted."
fi

# 5. Delete IAM role
DELETE_ROLE=false
if [[ "${FORCE}" == "true" ]]; then
  DELETE_ROLE=true
else
  read -rp "Delete IAM role '${AGENT_ROLE_NAME}'? (y/N) " confirm_role
  if [[ "${confirm_role}" =~ ^[Yy]$ ]]; then
    DELETE_ROLE=true
  fi
fi

if [[ "${DELETE_ROLE}" == "true" ]]; then
  echo "Deleting IAM role ${AGENT_ROLE_NAME}..."
  aws iam delete-role-policy --role-name "${AGENT_ROLE_NAME}" --policy-name "AgentCoreFullAccess" 2>/dev/null || true
  aws iam delete-role --role-name "${AGENT_ROLE_NAME}" 2>/dev/null || true
  echo "[+] IAM role deleted."
fi

echo "[+] AWS AgentCore Teardown complete."
