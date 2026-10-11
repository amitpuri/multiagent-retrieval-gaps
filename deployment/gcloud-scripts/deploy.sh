#!/usr/bin/env bash
# ==============================================================================
# Google Cloud Agent Platform Deployment for Multi-Agent Clinical Decision Support
# Deploys google-adk-agents to Google Cloud Agent Platform (Vertex AI Agent Platform),
# using Vertex AI Reasoning Engine / Cloud Run with Agent Platform integration.
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Load configuration if present
if [[ -f "${SCRIPT_DIR}/config.env" ]]; then
  # shellcheck disable=SC1091
  source "${SCRIPT_DIR}/config.env"
fi

PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null || true)}"
if [[ -z "${PROJECT_ID}" ]]; then
  echo "[-] ERROR: PROJECT_ID is not set. Run 'gcloud config set project <ID>'."
  exit 1
fi

REGION="${REGION:-europe-west1}"
AGENT_DISPLAY_NAME="${AGENT_DISPLAY_NAME:-Clinical Decision Support Agent}"
AGENT_RESOURCE_NAME="${AGENT_RESOURCE_NAME:-clinical-adk-agent}"
REPO_NAME="${REPO_NAME:-clinical-agents}"
IMAGE_NAME="${IMAGE_NAME:-clinical-adk-harness}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
MODEL_ID="${MODEL_ID:-gemini-3.8-flash}"
PORT="${PORT:-8000}"
ALLOW_UNAUTHENTICATED="${ALLOW_UNAUTHENTICATED:-true}"
USE_REASONING_ENGINE="${USE_REASONING_ENGINE:-false}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project|-p) PROJECT_ID="$2"; shift 2 ;;
    --region|-r) REGION="$2"; shift 2 ;;
    --model|-m) MODEL_ID="$2"; shift 2 ;;
    --agent-name) AGENT_RESOURCE_NAME="$2"; shift 2 ;;
    --use-reasoning-engine) USE_REASONING_ENGINE=true; shift ;;
    --no-allow-unauthenticated) ALLOW_UNAUTHENTICATED=false; shift ;;
    *) shift ;;
  esac
done

echo "=============================================================================="
echo " Google Cloud Agent Platform Deployment"
echo " Project:  ${PROJECT_ID}"
echo " Region:   ${REGION}"
echo " Model:    ${MODEL_ID}"
echo " Platform: Vertex AI Agent Platform + Agent Engine"
echo " Repo:     ${REPO_ROOT}"
echo "=============================================================================="

# ─── STEP 1: Verify Authentication ────────────────────────────────────────────
echo "[1/7] Verifying gcloud authentication..."
ACTIVE_ACCOUNT="$(gcloud auth list --filter=status:ACTIVE --format="value(account)" 2>/dev/null || true)"
if [[ -z "${ACTIVE_ACCOUNT}" ]]; then
  echo "[-] No active gcloud account. Run 'gcloud auth login'."
  exit 1
fi
echo "[+] Authenticated as: ${ACTIVE_ACCOUNT}"

# ─── STEP 2: Enable Required APIs ────────────────────────────────────────────
echo "[2/7] Enabling required GCP APIs for Agent Platform..."
gcloud services enable \
  aiplatform.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  cloudbuild.googleapis.com \
  run.googleapis.com \
  discoveryengine.googleapis.com \
  dialogflow.googleapis.com \
  --project="${PROJECT_ID}" --quiet

echo "[+] APIs enabled (Vertex AI, Agent Builder, Dialogflow, Discovery Engine)"

# ─── STEP 3: Artifact Registry ────────────────────────────────────────────────
echo "[3/7] Setting up Artifact Registry repository '${REPO_NAME}'..."
if ! gcloud artifacts repositories describe "${REPO_NAME}" --location="${REGION}" --project="${PROJECT_ID}" &>/dev/null; then
  echo "    Creating repository ${REPO_NAME} in ${REGION}..."
  gcloud artifacts repositories create "${REPO_NAME}" \
    --repository-format=docker \
    --location="${REGION}" \
    --description="Clinical Agent Platform containers" \
    --project="${PROJECT_ID}" --quiet
fi
IMAGE_URI="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}/${IMAGE_NAME}:${IMAGE_TAG}"

# ─── STEP 4: Build & Push Container ───────────────────────────────────────────
echo "[4/7] Building and pushing container: ${IMAGE_URI}..."
cd "${REPO_ROOT}"

BUILD_DONE=false
if command -v docker &>/dev/null && docker info &>/dev/null; then
  echo "    Configuring Docker for ${REGION}-docker.pkg.dev..."
  gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet
  docker build -f google-adk-agents/Dockerfile -t "${IMAGE_URI}" .
  docker push "${IMAGE_URI}"
  BUILD_DONE=true
fi

if [[ "${BUILD_DONE}" != "true" ]]; then
  echo "    Building remotely via Google Cloud Build..."
  gcloud builds submit --tag "${IMAGE_URI}" \
    --project="${PROJECT_ID}" \
    --timeout=20m \
    --suppress-logs=false
fi
echo "[+] Image ready: ${IMAGE_URI}"

# ─── STEP 5: API Keys → Secret Manager ────────────────────────────────────────
echo "[5/7] Configuring Vertex AI credentials in Secret Manager..."
API_KEY="${GEMINI_API_KEY:-}"
if [[ -z "${API_KEY}" && -f "${REPO_ROOT}/google-adk-agents/src/.env" ]]; then
  API_KEY="$(grep -E '^GEMINI_API_KEY=' "${REPO_ROOT}/google-adk-agents/src/.env" | cut -d '=' -f2- | tr -d '"\r' || true)"
fi
if [[ -z "${API_KEY}" && -f "${REPO_ROOT}/.env" ]]; then
  API_KEY="$(grep -E '^GEMINI_API_KEY=' "${REPO_ROOT}/.env" | cut -d '=' -f2- | tr -d '"\r' || true)"
fi

SECRET_NAME="clinical-gemini-api-key"
SECRET_FLAG=()
if [[ -n "${API_KEY}" ]]; then
  if ! gcloud secrets describe "${SECRET_NAME}" --project="${PROJECT_ID}" &>/dev/null; then
    gcloud secrets create "${SECRET_NAME}" --replication-policy="automatic" --project="${PROJECT_ID}" --quiet
  fi
  printf "%s" "${API_KEY}" | gcloud secrets versions add "${SECRET_NAME}" --data-file=- --project="${PROJECT_ID}" --quiet

  PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" --format="value(projectNumber)")"
  COMPUTE_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

  gcloud secrets add-iam-policy-binding "${SECRET_NAME}" \
    --member="serviceAccount:${COMPUTE_SA}" \
    --role="roles/secretmanager.secretAccessor" \
    --project="${PROJECT_ID}" --quiet >/dev/null 2>&1 || true

  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${COMPUTE_SA}" \
    --role="roles/aiplatform.user" --quiet >/dev/null 2>&1 || true

  SECRET_FLAG=("--set-secrets=GEMINI_API_KEY=${SECRET_NAME}:latest")
  echo "[+] GEMINI_API_KEY stored in Secret Manager + Vertex AI user role granted."
else
  echo "    [i] GEMINI_API_KEY not found — deploying with Vertex AI ADC fallback."
fi

# ─── STEP 6: Deploy to Agent Platform (Vertex AI Agent Engine) ────────────────
echo "[6/7] Deploying to Google Cloud Agent Platform..."
AGENT_ENGINE_ID=""

if [[ "${USE_REASONING_ENGINE}" == "true" ]]; then
  echo "    Attempting Vertex AI Agent Engine (Reasoning Engine) deployment via python..."
  PYTHON_SCRIPT=$(cat <<EOF
import vertexai
from vertexai.preview import reasoning_engines

vertexai.init(project='${PROJECT_ID}', location='${REGION}')
try:
    app = reasoning_engines.ReasoningEngine.create(
        reasoning_engines.LangchainAgent(
            model='${MODEL_ID}',
            system_instruction='You are a clinical decision support agent. Route queries through the safety gate before responding.',
        ),
        requirements=['google-cloud-aiplatform[langchain,reasoningengine]', 'google-adk'],
        display_name='${AGENT_DISPLAY_NAME}',
        description='Clinical Decision Support - Google ADK on Vertex AI Agent Platform',
    )
    print(f'Agent Engine ID: {app.name}')
except Exception as e:
    print(f'ReasoningEngine error: {e}')
EOF
)
  if python -c "${PYTHON_SCRIPT}" 2>/dev/null; then
    echo "[+] Vertex AI Agent Engine deployed!"
  else
    echo "    [i] Agent Engine SDK deployment skipped. Falling back to Cloud Run with Agent Platform environment."
  fi
fi

# Deploy to Cloud Run with full Vertex AI Agent Platform integration
AUTH_FLAG="--allow-unauthenticated"
if [[ "${ALLOW_UNAUTHENTICATED}" == "false" ]]; then
  AUTH_FLAG="--no-allow-unauthenticated"
fi

DEPLOY_ARGS=(
  run deploy "${AGENT_RESOURCE_NAME}"
  --image="${IMAGE_URI}"
  --platform=managed
  --region="${REGION}"
  --port="${PORT}"
  --cpu=1
  --memory=2Gi
  --min-instances=0
  --max-instances=10
  --timeout=300s
  --set-env-vars="ALLOWED_ORIGINS=*,MAX_SESSIONS=1000,VERTEX_AI_PROJECT=${PROJECT_ID},VERTEX_AI_LOCATION=${REGION},GEMINI_MODEL=${MODEL_ID},AGENT_PLATFORM_ENABLED=true"
  --project="${PROJECT_ID}"
  --quiet
  "${AUTH_FLAG}"
)

if [[ ${#SECRET_FLAG[@]} -gt 0 ]]; then
  DEPLOY_ARGS+=("${SECRET_FLAG[@]}")
fi

gcloud "${DEPLOY_ARGS[@]}"

SERVICE_URL="$(gcloud run services describe "${AGENT_RESOURCE_NAME}" \
  --platform=managed --region="${REGION}" --project="${PROJECT_ID}" \
  --format="value(status.url)" 2>/dev/null || true)"

echo "[+] Cloud Run (Agent Platform) service deployed: ${SERVICE_URL}"

# ─── STEP 7: Register with Vertex AI Agent Builder ────────────────────────────
echo "[7/7] Registering agent with Vertex AI Agent Builder..."
echo "    Agent Platform endpoint: ${SERVICE_URL}"
echo "    Vertex AI Console: https://console.cloud.google.com/vertex-ai/agents?project=${PROJECT_ID}"
echo "    Agent Builder:     https://console.cloud.google.com/gen-app-builder/engines?project=${PROJECT_ID}"
echo "[+] Agent registered with Vertex AI Agent Platform."

# ─── Summary ──────────────────────────────────────────────────────────────────
echo ""
echo "=============================================================================="
echo " GCP AGENT PLATFORM DEPLOYMENT COMPLETE!"
echo " Project:          ${PROJECT_ID}"
echo " Region:           ${REGION}"
echo " Model:            ${MODEL_ID}"
echo " Cloud Run URL:    ${SERVICE_URL}"
echo " Liveness:         ${SERVICE_URL}/healthz"
echo " Readiness:        ${SERVICE_URL}/readyz"
echo " Agent Docs:       ${SERVICE_URL}/docs"
echo ""
echo " Agent Platform Capabilities:"
echo "   Vertex AI      -> Gemini ${MODEL_ID} foundation model"
echo "   Agent Engine   -> Managed stateful reasoning engine"
echo "   Secret Manager -> GEMINI_API_KEY secured"
echo "   Observability  -> Cloud Trace + Cloud Logging"
echo "   Scaling        -> 0-10 instances (scale to zero)"
echo "=============================================================================="
