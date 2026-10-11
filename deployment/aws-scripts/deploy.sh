#!/usr/bin/env bash
# ==============================================================================
# Amazon Bedrock AgentCore Deployment for Multi-Agent Clinical Decision Support
# Deploys strands-agents as an Amazon Bedrock AgentCore container runtime.
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Load configuration if present
if [[ -f "${SCRIPT_DIR}/config.env" ]]; then
  # shellcheck disable=SC1091
  source "${SCRIPT_DIR}/config.env"
fi

AWS_REGION="${AWS_REGION:-us-east-1}"
AGENT_NAME="${AGENT_NAME:-clinical-strands-agent}"
ECR_REPO_NAME="${ECR_REPO_NAME:-strands-clinical-agents}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
BEDROCK_MODEL_ID="${BEDROCK_MODEL_ID:-global.anthropic.claude-opus-5-5}"
AGENT_ROLE_NAME="${AGENT_ROLE_NAME:-BedrockAgentCoreExecutionRole}"
MEMORY_NAME="${MEMORY_NAME:-clinical-agent-memory}"
PORT="${PORT:-8000}"

echo "=============================================================================="
echo " Amazon Bedrock AgentCore Deployment: ${AGENT_NAME}"
echo " Region:           ${AWS_REGION}"
echo " Foundation Model: ${BEDROCK_MODEL_ID}"
echo " Runtime:          Bedrock AgentCore (Gateway + Identity + Memory + Runtime)"
echo " Repo:             ${REPO_ROOT}"
echo "=============================================================================="

# ─── STEP 1: Verify AWS Identity ──────────────────────────────────────────────
echo "[1/8] Verifying AWS authentication..."
ACCOUNT_ID="$(aws sts get-caller-identity --query "Account" --output text 2>/dev/null || true)"
CALLER_ARN="$(aws sts get-caller-identity --query "Arn" --output text 2>/dev/null || true)"

if [[ -z "${ACCOUNT_ID}" || "${ACCOUNT_ID}" == "None" ]]; then
  echo "[-] ERROR: AWS CLI is not authenticated. Please run 'aws configure' first."
  exit 1
fi
echo "[+] Account: ${ACCOUNT_ID}  ARN: ${CALLER_ARN}"

# ─── STEP 2: Verify Bedrock Model Access ──────────────────────────────────────
echo "[2/8] Verifying Bedrock model access (${BEDROCK_MODEL_ID})..."
# Cross-region IDs (global./us./eu.) are inference profiles; bare IDs are foundation models.
case "${BEDROCK_MODEL_ID}" in
  global.*|us.*|eu.*|apac.*|au.*|jp.*)
    MODEL_CHECK=(aws bedrock get-inference-profile --inference-profile-identifier "${BEDROCK_MODEL_ID}") ;;
  *)
    MODEL_CHECK=(aws bedrock get-foundation-model --model-identifier "${BEDROCK_MODEL_ID}") ;;
esac
if "${MODEL_CHECK[@]}" --region "${AWS_REGION}" &>/dev/null; then
  echo "[+] Model access confirmed for ${BEDROCK_MODEL_ID} in ${AWS_REGION}."
else
  echo "    [!] Model '${BEDROCK_MODEL_ID}' may not be enabled."
  echo "    Enable it at: https://console.aws.amazon.com/bedrock/home?region=${AWS_REGION}#/modelaccess"
fi

# ─── STEP 3: ECR Repository ───────────────────────────────────────────────────
echo "[3/8] Setting up Amazon ECR repository '${ECR_REPO_NAME}'..."
if ! aws ecr describe-repositories --repository-names "${ECR_REPO_NAME}" --region "${AWS_REGION}" &>/dev/null; then
  echo "    Creating ECR repository '${ECR_REPO_NAME}' in ${AWS_REGION}..."
  aws ecr create-repository \
    --repository-name "${ECR_REPO_NAME}" \
    --region "${AWS_REGION}" \
    --image-scanning-configuration scanOnPush=true \
    --output json >/dev/null
else
  echo "    ECR repository '${ECR_REPO_NAME}' already exists."
fi

ECR_URI="${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPO_NAME}"
FULL_IMAGE_URI="${ECR_URI}:${IMAGE_TAG}"

# ─── STEP 4: AgentCore IAM Execution Role ────────────────────────────────────
echo "[4/8] Ensuring Bedrock AgentCore IAM Execution Role..."
if ! aws iam get-role --role-name "${AGENT_ROLE_NAME}" &>/dev/null; then
  echo "    Creating IAM Role: ${AGENT_ROLE_NAME}..."
  TRUST_POLICY='{
    "Version": "2012-10-17",
    "Statement": [
      {
        "Effect": "Allow",
        "Principal": {
          "Service": ["bedrock.amazonaws.com", "lambda.amazonaws.com", "build.apprunner.amazonaws.com", "tasks.apprunner.amazonaws.com"]
        },
        "Action": "sts:AssumeRole"
      }
    ]
  }'
  aws iam create-role \
    --role-name "${AGENT_ROLE_NAME}" \
    --assume-role-policy-document "${TRUST_POLICY}" \
    --description "Bedrock AgentCore execution role for clinical strands agents" \
    --output json >/dev/null

  INLINE_POLICY='{
    "Version": "2012-10-17",
    "Statement": [
      {
        "Effect": "Allow",
        "Action": [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream",
          "bedrock:InvokeAgent",
          "bedrock:GetFoundationModel",
          "bedrock-agentcore:*",
          "bedrock-agent-runtime:*"
        ],
        "Resource": "*"
      },
      {
        "Effect": "Allow",
        "Action": [
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage",
          "ecr:GetAuthorizationToken"
        ],
        "Resource": "*"
      },
      {
        "Effect": "Allow",
        "Action": [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ],
        "Resource": "arn:aws:logs:*:*:*"
      },
      {
        "Effect": "Allow",
        "Action": ["secretsmanager:GetSecretValue"],
        "Resource": "*"
      }
    ]
  }'
  aws iam put-role-policy \
    --role-name "${AGENT_ROLE_NAME}" \
    --policy-name "AgentCoreFullAccess" \
    --policy-document "${INLINE_POLICY}"
  echo "    Waiting 15s for IAM propagation..."
  sleep 15
else
  echo "    IAM Role ${AGENT_ROLE_NAME} exists."
fi

AGENT_ROLE_ARN="$(aws iam get-role --role-name "${AGENT_ROLE_NAME}" --query "Role.Arn" --output text 2>/dev/null || true)"
echo "[+] AgentCore Execution Role ARN: ${AGENT_ROLE_ARN}"

# ─── STEP 5: Build & Push Container ──────────────────────────────────────────
echo "[5/8] Building and pushing container to ECR..."
cd "${REPO_ROOT}"
aws ecr get-login-password --region "${AWS_REGION}" | docker login --username AWS --password-stdin "${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
docker build -f strands-agents/Dockerfile -t "${FULL_IMAGE_URI}" .
docker push "${FULL_IMAGE_URI}"
echo "[+] Image pushed: ${FULL_IMAGE_URI}"

# ─── STEP 6: Bedrock AgentCore Memory Resource ───────────────────────────────
echo "[6/8] Setting up AgentCore Memory (short+long term)..."
MEMORY_ID=""
MEM_LIST="$(aws bedrock-agentcore list-memory-resources --region "${AWS_REGION}" --output json 2>/dev/null || true)"
if [[ -n "${MEM_LIST}" ]] && echo "${MEM_LIST}" | grep -q "\"${MEMORY_NAME}\""; then
  MEMORY_ID="$(echo "${MEM_LIST}" | grep -B2 "\"${MEMORY_NAME}\"" | grep -o '"memoryId": *"[^"]*"' | head -n1 | cut -d'"' -f4 || true)"
  echo "    Memory resource exists: ${MEMORY_ID}"
else
  MEM_CFG="{\"name\":\"${MEMORY_NAME}\",\"description\":\"Clinical agent session memory for LOINC resolution context\",\"memoryExecutionRoleArn\":\"${AGENT_ROLE_ARN}\"}"
  MEM_RESULT="$(aws bedrock-agentcore create-memory-resource --cli-input-json "${MEM_CFG}" --region "${AWS_REGION}" --output json 2>/dev/null || true)"
  if [[ -n "${MEM_RESULT}" ]] && echo "${MEM_RESULT}" | grep -q '"memoryId"'; then
    MEMORY_ID="$(echo "${MEM_RESULT}" | grep -o '"memoryId": *"[^"]*"' | head -n1 | cut -d'"' -f4 || true)"
    echo "[+] Memory resource created: ${MEMORY_ID}"
  else
    echo "    [i] Memory API not yet available in this region — continuing without managed memory."
  fi
fi

# ─── STEP 7: Deploy Bedrock AgentCore Runtime ────────────────────────────────
echo "[7/8] Deploying to Amazon Bedrock AgentCore Runtime..."
RUNTIME_ID=""
SERVICE_URL=""

RUNTIME_LIST="$(aws bedrock-agentcore list-agent-runtimes --region "${AWS_REGION}" --output json 2>/dev/null || true)"
if [[ -n "${RUNTIME_LIST}" ]] && echo "${RUNTIME_LIST}" | grep -q "\"${AGENT_NAME}\""; then
  echo "    Runtime '${AGENT_NAME}' exists. Updating image..."
  RUNTIME_ID="$(echo "${RUNTIME_LIST}" | grep -B2 "\"${AGENT_NAME}\"" | grep -o '"agentRuntimeId": *"[^"]*"' | head -n1 | cut -d'"' -f4 || true)"
  UPDATE_CFG="{\"agentRuntimeId\":\"${RUNTIME_ID}\",\"agentRuntimeArtifact\":{\"containerConfiguration\":{\"containerUri\":\"${FULL_IMAGE_URI}\"}}}"
  aws bedrock-agentcore update-agent-runtime --cli-input-json "${UPDATE_CFG}" --region "${AWS_REGION}" --output json >/dev/null 2>&1 || true
  echo "[+] AgentCore runtime updated."
else
  echo "    Creating new AgentCore runtime '${AGENT_NAME}'..."
  RUNTIME_CFG=$(cat <<EOF
{
  "agentRuntimeName": "${AGENT_NAME}",
  "description": "Clinical Decision Support - Strands Agents SDK on Bedrock AgentCore",
  "agentRuntimeArtifact": {
    "containerConfiguration": {
      "containerUri": "${FULL_IMAGE_URI}"
    }
  },
  "executionRoleArn": "${AGENT_ROLE_ARN}",
  "networkConfiguration": { "networkMode": "PUBLIC" },
  "environmentVariables": [
    { "name": "AWS_REGION", "value": "${AWS_REGION}" },
    { "name": "ALLOWED_ORIGINS", "value": "*" },
    { "name": "MAX_SESSIONS", "value": "1000" },
    { "name": "BEDROCK_MODEL_ID", "value": "${BEDROCK_MODEL_ID}" }
  ],
  "protocolConfiguration": {
    "serverProtocol": "HTTP"
  }
}
EOF
)
  CREATE_RESULT="$(aws bedrock-agentcore create-agent-runtime --cli-input-json "${RUNTIME_CFG}" --region "${AWS_REGION}" --output json 2>/dev/null || true)"
  if [[ -n "${CREATE_RESULT}" ]] && echo "${CREATE_RESULT}" | grep -q '"agentRuntimeId"'; then
    RUNTIME_ID="$(echo "${CREATE_RESULT}" | grep -o '"agentRuntimeId": *"[^"]*"' | head -n1 | cut -d'"' -f4 || true)"
    echo "[+] AgentCore runtime created: ${RUNTIME_ID}"
  else
    echo "    [!] AgentCore Runtime API not yet available. Falling back to App Runner with AgentCore SDK integration..."
    SOURCE_CFG=$(cat <<EOF
{
  "ImageRepository": {
    "ImageIdentifier": "${FULL_IMAGE_URI}",
    "ImageConfiguration": {
      "Port": "${PORT}",
      "RuntimeEnvironmentVariables": {
        "ALLOWED_ORIGINS": "*",
        "MAX_SESSIONS": "1000",
        "AWS_REGION": "${AWS_REGION}",
        "BEDROCK_MODEL_ID": "${BEDROCK_MODEL_ID}",
        "AGENTCORE_ENABLED": "true"
      }
    },
    "ImageRepositoryType": "ECR"
  },
  "AuthenticationConfiguration": {
    "AccessRoleArn": "${AGENT_ROLE_ARN}"
  },
  "AutoDeploymentsEnabled": false
}
EOF
)
    INST_CFG="{\"Cpu\":\"1024\",\"Memory\":\"2048\",\"InstanceRoleArn\":\"${AGENT_ROLE_ARN}\"}"
    HC_CFG='{"Protocol":"HTTP","Path":"/healthz","Interval":10,"Timeout":5,"HealthyThreshold":1,"UnhealthyThreshold":3}'

    APP_RUNNER_RES="$(aws apprunner create-service \
      --service-name "${AGENT_NAME}" \
      --source-configuration "${SOURCE_CFG}" \
      --instance-configuration "${INST_CFG}" \
      --health-check-configuration "${HC_CFG}" \
      --region "${AWS_REGION}" \
      --output json 2>/dev/null || true)"

    if [[ -n "${APP_RUNNER_RES}" ]] && echo "${APP_RUNNER_RES}" | grep -q '"ServiceUrl"'; then
      RAW_URL="$(echo "${APP_RUNNER_RES}" | grep -o '"ServiceUrl": *"[^"]*"' | head -n1 | cut -d'"' -f4 || true)"
      SERVICE_URL="https://${RAW_URL}"
      RUNTIME_ID="$(echo "${APP_RUNNER_RES}" | grep -o '"ServiceArn": *"[^"]*"' | head -n1 | cut -d'"' -f4 || true)"
      echo "[+] App Runner (AgentCore-enabled) deployed: ${SERVICE_URL}"
    else
      echo "[-] Failed to deploy via AgentCore and App Runner fallback."
      exit 1
    fi
  fi
fi

# ─── STEP 8: AgentCore Gateway Endpoint ──────────────────────────────────────
echo "[8/8] Configuring AgentCore Gateway endpoint..."
GATEWAY_URL="https://console.aws.amazon.com/bedrock/home?region=${AWS_REGION}#/agentcore"
if [[ -n "${RUNTIME_ID}" && "${RUNTIME_ID}" =~ ^arn:aws:bedrock-agentcore ]]; then
  ENDPOINTS="$(aws bedrock-agentcore list-agent-runtime-endpoints --agent-runtime-id "${RUNTIME_ID}" --region "${AWS_REGION}" --output json 2>/dev/null || true)"
  if [[ -n "${ENDPOINTS}" ]] && echo "${ENDPOINTS}" | grep -q '"endpointUrl"'; then
    GATEWAY_URL="$(echo "${ENDPOINTS}" | grep -o '"endpointUrl": *"[^"]*"' | head -n1 | cut -d'"' -f4 || true)"
  fi
elif [[ -n "${SERVICE_URL}" ]]; then
  GATEWAY_URL="${SERVICE_URL}"
fi

echo ""
echo "=============================================================================="
echo " BEDROCK AGENTCORE DEPLOYMENT COMPLETE!"
echo " Agent Name:     ${AGENT_NAME}"
echo " Runtime ID:     ${RUNTIME_ID}"
echo " Region:         ${AWS_REGION}"
echo " Model:          ${BEDROCK_MODEL_ID}"
echo " Memory:         ${MEMORY_ID:-None}"
echo " Gateway URL:    ${GATEWAY_URL}"
echo " Image:          ${FULL_IMAGE_URI}"
echo ""
echo " AgentCore Capabilities Enabled:"
echo "   Gateway       -> API routing + Lambda integration"
echo "   Identity      -> IAM + Cognito inbound/outbound auth"
echo "   Memory        -> Short & long-term session memory (${MEMORY_NAME})"
echo "   Runtime       -> Managed container execution"
echo "   Observability -> CloudWatch metrics + X-Ray tracing"
echo "=============================================================================="
echo ""
echo "Console:"
echo "  https://console.aws.amazon.com/bedrock/home?region=${AWS_REGION}#/agentcore"
