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

# Every resource this script CREATES is appended to the ledger; destroy.sh deletes
# exactly those (deployment/teardown.py). Reused, pre-existing resources are not recorded.
LEDGER="${SCRIPT_DIR}/.deployed/ledger.tsv"
record_created() {  # kind name [key=value;key=value]
  mkdir -p "$(dirname "${LEDGER}")"
  printf '%s\t%s\t%s\n' "$1" "$2" "${3:-}" >> "${LEDGER}"
}

AWS_REGION="${AWS_REGION:-us-east-1}"
# AgentCore names must match [a-zA-Z][a-zA-Z0-9_]{0,47} (no hyphens).
AGENT_NAME="${AGENT_NAME:-clinical_strands_agent}"
APP_RUNNER_NAME="${APP_RUNNER_NAME:-clinical-strands-agent}"
# App Runner bills for provisioned instances around the clock: opt in explicitly.
APP_RUNNER_FALLBACK="${APP_RUNNER_FALLBACK:-false}"
ECR_REPO_NAME="${ECR_REPO_NAME:-strands-clinical-agents}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
BEDROCK_MODEL_ID="${BEDROCK_MODEL_ID:-global.anthropic.claude-opus-5-5}"
AGENT_ROLE_NAME="${AGENT_ROLE_NAME:-BedrockAgentCoreExecutionRole}"
MEMORY_NAME="${MEMORY_NAME:-clinical_agent_memory}"
MEMORY_EXPIRY_DAYS="${MEMORY_EXPIRY_DAYS:-30}"
PORT="${PORT:-8080}"   # AgentCore Runtime contract (/ping, /invocations on 8080)

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
  record_created ecr-repository "${ECR_REPO_NAME}" "region=${AWS_REGION}"
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
          "Service": ["bedrock-agentcore.amazonaws.com", "build.apprunner.amazonaws.com", "tasks.apprunner.amazonaws.com"]
        },
        "Action": "sts:AssumeRole",
        "Condition": { "StringEquals": { "aws:SourceAccount": "'"${ACCOUNT_ID}"'" } }
      }
    ]
  }'
  aws iam create-role \
    --role-name "${AGENT_ROLE_NAME}" \
    --assume-role-policy-document "${TRUST_POLICY}" \
    --description "Bedrock AgentCore execution role for clinical strands agents" \
    --output json >/dev/null
  record_created iam-role "${AGENT_ROLE_NAME}" "region=${AWS_REGION}"

  # Least privilege: invoke models, pull this repository, write runtime logs/traces, use this memory.
  INLINE_POLICY='{
    "Version": "2012-10-17",
    "Statement": [
      { "Effect": "Allow",
        "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream", "bedrock:GetInferenceProfile"],
        "Resource": ["arn:aws:bedrock:*::foundation-model/*", "arn:aws:bedrock:*:'"${ACCOUNT_ID}"':inference-profile/*"] },
      { "Effect": "Allow", "Action": ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"],
        "Resource": "arn:aws:ecr:'"${AWS_REGION}"':'"${ACCOUNT_ID}"':repository/'"${ECR_REPO_NAME}"'" },
      { "Effect": "Allow", "Action": "ecr:GetAuthorizationToken", "Resource": "*" },
      { "Effect": "Allow", "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogStreams"],
        "Resource": "arn:aws:logs:'"${AWS_REGION}"':'"${ACCOUNT_ID}"':log-group:/aws/bedrock-agentcore/*" },
      { "Effect": "Allow", "Action": ["xray:PutTraceSegments", "xray:PutTelemetryRecords"], "Resource": "*" },
      { "Effect": "Allow",
        "Action": ["bedrock-agentcore:CreateEvent", "bedrock-agentcore:GetEvent", "bedrock-agentcore:ListEvents",
                   "bedrock-agentcore:ListSessions", "bedrock-agentcore:RetrieveMemoryRecords"],
        "Resource": "arn:aws:bedrock-agentcore:'"${AWS_REGION}"':'"${ACCOUNT_ID}"':memory/*" }
    ]
  }'
  aws iam put-role-policy \
    --role-name "${AGENT_ROLE_NAME}" \
    --policy-name "ClinicalAgentRuntimeAccess" \
    --policy-document "${INLINE_POLICY}"
  echo "    Waiting 15s for IAM propagation..."
  sleep 15
else
  echo "    IAM Role ${AGENT_ROLE_NAME} exists."
fi

AGENT_ROLE_ARN="$(aws iam get-role --role-name "${AGENT_ROLE_NAME}" --query "Role.Arn" --output text 2>/dev/null || true)"
echo "[+] AgentCore Execution Role ARN: ${AGENT_ROLE_ARN}"

# ─── STEP 4b: Knowledge release + S3 skill store ──────────────────────────────
# `ontogate build` fails closed on any integrity, skill-lint or SHACL error.
echo "[4b/9] Building the knowledge release and publishing locked skills..."
cd "${REPO_ROOT}"
export PYTHONPATH="${REPO_ROOT}/shared${PYTHONPATH:+:${PYTHONPATH}}"
python -m ontogate build
SKILLS_BUCKET="${SKILLS_BUCKET:-${PROJECT_NAME}-${ENVIRONMENT}-skills}"
if aws s3api head-bucket --bucket "${SKILLS_BUCKET}" &>/dev/null; then
  python -m ontogate skills publish "s3://${SKILLS_BUCKET}/skills"
  echo "[+] Skills published to s3://${SKILLS_BUCKET}/skills (content-addressed, immutable)."
else
  echo "    [i] S3 bucket ${SKILLS_BUCKET} not found; skills ship inside the image only."
fi

# ─── STEP 5: Build & Push Container ──────────────────────────────────────────
echo "[5/9] Building and pushing container to ECR..."
cd "${REPO_ROOT}"
aws ecr get-login-password --region "${AWS_REGION}" | docker login --username AWS --password-stdin "${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
# AgentCore Runtime needs linux/arm64; the opt-in App Runner fallback needs linux/amd64.
docker buildx build --platform linux/arm64,linux/amd64 -f strands-agents/Dockerfile -t "${FULL_IMAGE_URI}" --push .
echo "[+] Image pushed: ${FULL_IMAGE_URI}"

# ─── STEP 6: Bedrock AgentCore Memory ────────────────────────────────────────
echo "[6/8] Setting up AgentCore Memory..."
# Memory ids are "<name>-<suffix>"; list-memories returns ids, not names.
MEMORY_ID="$(aws bedrock-agentcore-control list-memories --region "${AWS_REGION}" \
  --query "memories[?starts_with(id, '${MEMORY_NAME}-')].id | [0]" --output text 2>/dev/null || true)"
if [[ -n "${MEMORY_ID}" && "${MEMORY_ID}" != "None" ]]; then
  echo "    Memory exists: ${MEMORY_ID}"
else
  MEMORY_ID="$(aws bedrock-agentcore-control create-memory \
    --name "${MEMORY_NAME}" \
    --description "Clinical agent session memory (no PHI in long-term records)" \
    --event-expiry-duration "${MEMORY_EXPIRY_DAYS}" \
    --memory-execution-role-arn "${AGENT_ROLE_ARN}" \
    --region "${AWS_REGION}" --query "memory.id" --output text || true)"
  if [[ -n "${MEMORY_ID}" && "${MEMORY_ID}" != "None" ]]; then
    record_created agentcore-memory "${MEMORY_ID}" "region=${AWS_REGION}"
    echo "[+] Memory created: ${MEMORY_ID}"
  else
    MEMORY_ID=""
    echo "    [i] AgentCore Memory unavailable (see the error above); continuing without managed memory."
  fi
fi

# ─── STEP 7: Deploy Bedrock AgentCore Runtime ────────────────────────────────
echo "[7/8] Deploying to Amazon Bedrock AgentCore Runtime..."
ARTIFACT="{\"containerConfiguration\":{\"containerUri\":\"${FULL_IMAGE_URI}\"}}"
NETWORK='{"networkMode":"PUBLIC"}'
ENV_VARS="{\"AWS_REGION\":\"${AWS_REGION}\",\"BEDROCK_MODEL_ID\":\"${BEDROCK_MODEL_ID}\",\"AGENTCORE_MEMORY_ID\":\"${MEMORY_ID}\",\"ALLOWED_ORIGINS\":\"*\",\"MAX_SESSIONS\":\"1000\"}"
SERVICE_URL=""
RUNTIME_ID="$(aws bedrock-agentcore-control list-agent-runtimes --region "${AWS_REGION}" \
  --query "agentRuntimes[?agentRuntimeName=='${AGENT_NAME}'].agentRuntimeId | [0]" --output text 2>/dev/null || true)"
if [[ -n "${RUNTIME_ID}" && "${RUNTIME_ID}" != "None" ]]; then
  echo "    Runtime '${AGENT_NAME}' exists (${RUNTIME_ID}). Updating image..."
  aws bedrock-agentcore-control update-agent-runtime --agent-runtime-id "${RUNTIME_ID}" \
    --agent-runtime-artifact "${ARTIFACT}" --role-arn "${AGENT_ROLE_ARN}" \
    --network-configuration "${NETWORK}" --environment-variables "${ENV_VARS}" \
    --region "${AWS_REGION}" --output json >/dev/null
  echo "[+] AgentCore runtime updated."
elif RUNTIME_ID="$(aws bedrock-agentcore-control create-agent-runtime \
    --agent-runtime-name "${AGENT_NAME}" \
    --description "Clinical Decision Support - Strands Agents SDK on Bedrock AgentCore" \
    --agent-runtime-artifact "${ARTIFACT}" --role-arn "${AGENT_ROLE_ARN}" \
    --network-configuration "${NETWORK}" --environment-variables "${ENV_VARS}" \
    --region "${AWS_REGION}" --query "agentRuntimeId" --output text)"; then
  record_created agentcore-runtime "${RUNTIME_ID}" "region=${AWS_REGION}"
  echo "[+] AgentCore runtime created: ${RUNTIME_ID}"
elif [[ "${APP_RUNNER_FALLBACK}" == "true" ]]; then
  echo "    [!] AgentCore Runtime creation failed. APP_RUNNER_FALLBACK=true: deploying to App Runner (billed while running)..."
  SOURCE_CFG="{\"ImageRepository\":{\"ImageIdentifier\":\"${FULL_IMAGE_URI}\",\"ImageConfiguration\":{\"Port\":\"${PORT}\",\"RuntimeEnvironmentVariables\":{\"AWS_REGION\":\"${AWS_REGION}\",\"BEDROCK_MODEL_ID\":\"${BEDROCK_MODEL_ID}\",\"ALLOWED_ORIGINS\":\"*\"}},\"ImageRepositoryType\":\"ECR\"},\"AuthenticationConfiguration\":{\"AccessRoleArn\":\"${AGENT_ROLE_ARN}\"},\"AutoDeploymentsEnabled\":false}"
  SERVICE_ARN="$(aws apprunner create-service --service-name "${APP_RUNNER_NAME}" \
    --source-configuration "${SOURCE_CFG}" \
    --instance-configuration "{\"Cpu\":\"1024\",\"Memory\":\"2048\",\"InstanceRoleArn\":\"${AGENT_ROLE_ARN}\"}" \
    --health-check-configuration '{"Protocol":"HTTP","Path":"/healthz","Interval":10,"Timeout":5,"HealthyThreshold":1,"UnhealthyThreshold":3}' \
    --region "${AWS_REGION}" --query "Service.ServiceArn" --output text)"
  record_created app-runner-service "${SERVICE_ARN}" "region=${AWS_REGION}"
  SERVICE_URL="https://$(aws apprunner describe-service --service-arn "${SERVICE_ARN}" --region "${AWS_REGION}" \
    --query "Service.ServiceUrl" --output text)"
  echo "[+] App Runner service deployed: ${SERVICE_URL}"
else
  echo "[-] AgentCore Runtime creation failed (see the error above)."
  echo "    Set APP_RUNNER_FALLBACK=true to deploy to App Runner instead (billed while running)."
  exit 1
fi

# ─── STEP 8: Runtime endpoint ────────────────────────────────────────────────
echo "[8/8] Resolving the runtime endpoint..."
GATEWAY_URL="${SERVICE_URL}"
if [[ -z "${GATEWAY_URL}" && -n "${RUNTIME_ID}" ]]; then
  RUNTIME_ARN="$(aws bedrock-agentcore-control get-agent-runtime --agent-runtime-id "${RUNTIME_ID}" \
    --region "${AWS_REGION}" --query "agentRuntimeArn" --output text 2>/dev/null || true)"
  GATEWAY_URL="aws bedrock-agentcore invoke-agent-runtime --agent-runtime-arn ${RUNTIME_ARN} ..."
fi

echo ""
echo "=============================================================================="
echo " BEDROCK AGENTCORE DEPLOYMENT COMPLETE!"
echo " Agent Name:     ${AGENT_NAME}"
echo " Runtime ID:     ${RUNTIME_ID}"
echo " Region:         ${AWS_REGION}"
echo " Model:          ${BEDROCK_MODEL_ID}"
echo " Memory:         ${MEMORY_ID:-None}"
echo " Invoke:         ${GATEWAY_URL}"
echo " Teardown:       ${SCRIPT_DIR}/destroy.sh --yes   (deletes what this deploy created)"
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
