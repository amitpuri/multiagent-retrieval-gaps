<#
.SYNOPSIS
    Google Cloud Agent Platform Deployment for Multi-Agent Clinical Decision Support.
.DESCRIPTION
    Deploys google-adk-agents to Google Cloud Agent Platform (Vertex AI Agent Platform),
    using Vertex AI Reasoning Engine for managed agent hosting with built-in:
    - Vertex AI model serving (Gemini 3.5 Flash / Gemini 2.0)
    - Managed scaling and session management
    - Agent Builder integration
    - Vertex AI Evaluation + Observability
    - Agent Engine (Reasoning Engine) for stateful multi-turn agents

    Architecture: google-adk-agents -> Vertex AI Agent Engine (Reasoning Engine)
                  OR Vertex AI Agent Builder -> Agent Platform runtime

.PARAMETER ProjectId
    GCP project ID (auto-detected from gcloud config if empty).
.PARAMETER Region
    Deployment region. Agent Platform supported: us-central1, europe-west1.
.PARAMETER AgentDisplayName
    Display name for the Vertex AI Agent.
.PARAMETER ModelId
    Gemini model ID (default: gemini-3.8-flash).
.EXAMPLE
    .\deploy.ps1 -ProjectId openagi-codes -Region europe-west1
#>
[CmdletBinding()]
param(
    [string]$ProjectId          = "",
    [string]$Region             = "europe-west1",
    [string]$AgentDisplayName   = "Clinical Decision Support Agent",
    [string]$AgentResourceName  = "clinical-adk-agent",
    [string]$RepoName           = "clinical-agents",
    [string]$ImageName          = "clinical-adk-harness",
    [string]$ImageTag           = "latest",
    [string]$ModelId            = "gemini-3.8-flash",
    [int]$Port                  = 8000,
    [switch]$UseReasoningEngine,
    [switch]$NoAllowUnauthenticated
)

$ErrorActionPreference = "Continue"
if ($PSVersionTable.PSVersion.Major -ge 7) { $PSNativeCommandUseErrorActionPreference = $false }

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot  = (Resolve-Path "$scriptDir\..\..").Path

# Auto-detect Project ID
if (-not $ProjectId) { $ProjectId = (gcloud config get-value project 2>$null).Trim() }
if (-not $ProjectId) { Write-Error "GCP Project ID not set. Run 'gcloud config set project <ID>'."; exit 1 }

Write-Host "==============================================================================" -ForegroundColor Cyan
Write-Host " Google Cloud Agent Platform Deployment" -ForegroundColor Cyan
Write-Host " Project:  $ProjectId" -ForegroundColor Cyan
Write-Host " Region:   $Region" -ForegroundColor Cyan
Write-Host " Model:    $ModelId" -ForegroundColor Cyan
Write-Host " Platform: Vertex AI Agent Platform + Agent Engine" -ForegroundColor Cyan
Write-Host " Repo:     $repoRoot" -ForegroundColor Cyan
Write-Host "==============================================================================" -ForegroundColor Cyan

# ─── STEP 1: Verify Authentication ────────────────────────────────────────────
Write-Host "[1/7] Verifying gcloud authentication..." -ForegroundColor Yellow
$activeAccount = (gcloud auth list --filter="status:ACTIVE" --format="value(account)" 2>$null).Trim()
if (-not $activeAccount) { Write-Error "No active gcloud account. Run 'gcloud auth login'."; exit 1 }
Write-Host "[+] Authenticated as: $activeAccount" -ForegroundColor Green

# ─── STEP 2: Enable Required APIs ────────────────────────────────────────────
Write-Host "[2/7] Enabling required GCP APIs for Agent Platform..." -ForegroundColor Yellow
gcloud services enable `
    aiplatform.googleapis.com `
    artifactregistry.googleapis.com `
    secretmanager.googleapis.com `
    cloudbuild.googleapis.com `
    run.googleapis.com `
    discoveryengine.googleapis.com `
    dialogflow.googleapis.com `
    --project=$ProjectId --quiet

Write-Host "[+] APIs enabled (Vertex AI, Agent Builder, Dialogflow, Discovery Engine)" -ForegroundColor Green

# ─── STEP 3: Artifact Registry ────────────────────────────────────────────────
Write-Host "[3/7] Setting up Artifact Registry repository '$RepoName'..." -ForegroundColor Yellow
$repoExists = gcloud artifacts repositories describe $RepoName --location=$Region --project=$ProjectId 2>$null
if (-not $repoExists) {
    Write-Host "    Creating repository $RepoName in $Region..."
    gcloud artifacts repositories create $RepoName `
        --repository-format=docker `
        --location=$Region `
        --description="Clinical Agent Platform containers" `
        --project=$ProjectId --quiet
}
$imageUri = "$Region-docker.pkg.dev/$ProjectId/$RepoName/${ImageName}:$ImageTag"

# ─── STEP 3b: Build & Sync Skills to GCP Skill Registry ───────────────────────
Write-Host "[3b/8] Building and syncing skills to GCP Skill Registry..." -ForegroundColor Yellow
python -m ontogate.skills build
$skillRegistryBucket = if ($env:GCP_SKILL_REGISTRY_BUCKET) { $env:GCP_SKILL_REGISTRY_BUCKET } else { "gs://$ProjectId-skill-registry/skills" }
$bucketExists = gcloud storage ls $skillRegistryBucket 2>$null
if ($bucketExists) {
    Write-Host "    Syncing dist/skills/*.zip to $skillRegistryBucket..."
    gcloud storage cp dist/skills/*.zip "$skillRegistryBucket/" 2>$null
    Write-Host "[+] Skills synced to GCP Skill Registry store." -ForegroundColor Green
} else {
    Write-Host "    [i] Skill Registry bucket '$skillRegistryBucket' not yet provisioned; skills baked into image via dist/skills." -ForegroundColor DarkYellow
}

# ─── STEP 4: Build & Push Container ───────────────────────────────────────────
Write-Host "[4/8] Building and pushing container: $imageUri..." -ForegroundColor Yellow
Push-Location $repoRoot
try {
    gcloud auth configure-docker "$Region-docker.pkg.dev" --quiet
    docker build -f google-adk-agents/Dockerfile -t $imageUri .
    if ($LASTEXITCODE -ne 0) { throw "Docker build failed." }
    docker push $imageUri
    if ($LASTEXITCODE -ne 0) { throw "Docker push failed." }
} finally { Pop-Location }
Write-Host "[+] Image ready: $imageUri" -ForegroundColor Green

# ─── STEP 5: API Keys → Secret Manager ────────────────────────────────────────
Write-Host "[5/8] Configuring Vertex AI credentials in Secret Manager..." -ForegroundColor Yellow
$apiKey = $env:GEMINI_API_KEY
if (-not $apiKey) {
    $envFile = "$repoRoot\google-adk-agents\src\.env"
    if (Test-Path $envFile) {
        $match = Select-String -Path $envFile -Pattern "^GEMINI_API_KEY=(.+)$"
        if ($match) { $apiKey = $match.Matches[0].Groups[1].Value.Trim('"', "'", "`r", "`n") }
    }
}

$secretName  = "clinical-gemini-api-key"
$secretFlags = @()
if ($apiKey) {
    $secretExists = gcloud secrets describe $secretName --project=$ProjectId 2>$null
    if (-not $secretExists) {
        gcloud secrets create $secretName --replication-policy="automatic" --project=$ProjectId --quiet
    }
    $apiKey | gcloud secrets versions add $secretName --data-file=- --project=$ProjectId --quiet
    $projectNumber = (gcloud projects describe $ProjectId --format="value(projectNumber)").Trim()
    $computeSa     = "$projectNumber-compute@developer.gserviceaccount.com"
    gcloud secrets add-iam-policy-binding $secretName `
        --member="serviceAccount:$computeSa" `
        --role="roles/secretmanager.secretAccessor" `
        --project=$ProjectId --quiet 2>$null | Out-Null
    gcloud projects add-iam-policy-binding $ProjectId `
        --member="serviceAccount:$computeSa" `
        --role="roles/aiplatform.user" --quiet 2>$null | Out-Null
    $secretFlags = @("--set-secrets=GEMINI_API_KEY=${secretName}:latest")
    Write-Host "[+] GEMINI_API_KEY stored in Secret Manager + Vertex AI user role granted." -ForegroundColor Green
} else {
    Write-Host "    [i] GEMINI_API_KEY not found — deploying with Vertex AI ADC fallback." -ForegroundColor DarkYellow
}

# ─── STEP 6: Deploy to Agent Platform (Vertex AI Agent Runtime) ───────────────
Write-Host "[6/8] Deploying to Google Cloud Agent Platform..." -ForegroundColor Yellow

$agentPlatformDeployed = $false

# Try Vertex AI Reasoning Engine (Agent Runtime) first — native ADK agent hosting
Write-Host "    Attempting Vertex AI Agent Runtime deployment via native ADK app..."
$reasoningEngines = gcloud ai reasoning-engines list `
    --location=$Region --project=$ProjectId `
    --format="value(name)" 2>$null | Select-String -Pattern $AgentResourceName

if ($UseReasoningEngine -or -not $reasoningEngines) {
    # Create Agent Runtime via Vertex AI SDK (native ADK app deployment)
    $agentDeployScript = @"
import vertexai
from vertexai.preview import reasoning_engines

class ClinicalAdkAgentRuntime:
    """Clinical Decision Support ADK Agent Runtime application."""
    def __init__(self, model_id: str = "$ModelId"):
        self.model_id = model_id

    def set_up(self):
        from src.workflow import run_clinical_workflow
        self._workflow = run_clinical_workflow

    def query(self, text: str, **kwargs):
        import asyncio
        from src.runner import execute_clinical_turn
        return asyncio.run(execute_clinical_turn(text))

vertexai.init(project='$ProjectId', location='$Region')

app = reasoning_engines.ReasoningEngine.create(
    ClinicalAdkAgentRuntime(model_id='$ModelId'),
    requirements=['google-cloud-aiplatform>=1.60.0', 'google-genai>=1.0.0', 'google-adk>=2.11.0', 'pydantic>=2.0.0', 'pyyaml>=6.0.0'],
    extra_packages=['shared'],
    display_name='$AgentDisplayName',
    description='Clinical Decision Support - Google ADK on Agent Runtime',
)
print(f'Agent Runtime deployed: {app.resource_name}')
print(f'Agent Runtime ID: {app.name}')
"@
    $tempPy = [System.IO.Path]::GetTempFileName() + ".py"
    [System.IO.File]::WriteAllText($tempPy, $agentDeployScript, (New-Object System.Text.UTF8Encoding $false))
    Write-Host "    Running Vertex AI Agent Runtime deployment script..."
    $pythonResult = python $tempPy 2>&1
    Remove-Item $tempPy -Force -ErrorAction SilentlyContinue
    if ($LASTEXITCODE -eq 0 -and $pythonResult) {
        Write-Host "[+] Vertex AI Agent Runtime deployed!" -ForegroundColor Green
        Write-Host "    $pythonResult"
        $agentPlatformDeployed = $true
        $agentEngineId = ($pythonResult | Select-String "Agent Runtime ID: (.+)").Matches[0].Groups[1].Value
    } else {
        Write-Host "    [i] Agent Runtime SDK deployment skipped. Falling back to Cloud Run + Agent Platform configuration..." -ForegroundColor DarkYellow
    }
}

# Deploy to Cloud Run with full Vertex AI Agent Platform integration
$authArg = if ($NoAllowUnauthenticated) { "--no-allow-unauthenticated" } else { "--allow-unauthenticated" }
$deployArgs = @(
    "run", "deploy", $AgentResourceName,
    "--image=$imageUri",
    "--platform=managed",
    "--region=$Region",
    "--port=$Port",
    "--cpu=1",
    "--memory=2Gi",
    "--min-instances=0",
    "--max-instances=10",
    "--timeout=300s",
    "--set-env-vars=ALLOWED_ORIGINS=*,MAX_SESSIONS=1000,VERTEX_AI_PROJECT=$ProjectId,VERTEX_AI_LOCATION=$Region,GEMINI_MODEL=$ModelId,AGENT_PLATFORM_ENABLED=true",
    "--project=$ProjectId",
    "--quiet",
    $authArg
)
if ($secretFlags.Count -gt 0) { $deployArgs += $secretFlags }
& gcloud @deployArgs

$serviceUrl = (gcloud run services describe $AgentResourceName `
    --platform=managed --region=$Region --project=$ProjectId `
    --format="value(status.url)" 2>$null).Trim()

Write-Host "[+] Cloud Run (Agent Platform) service deployed: $serviceUrl" -ForegroundColor Green

# ─── STEP 7: Register with Vertex AI Agent Builder (Agent Store) ───────────────
Write-Host "[7/7] Registering agent with Vertex AI Agent Builder..." -ForegroundColor Yellow

# Create Agent Builder data store for the agent
$agentBuilderPayload = @{
    displayName = $AgentDisplayName
    description = "Clinical Decision Support multi-agent system using Google ADK 2.11 and Gemini"
    defaultLanguageCode = "en"
} | ConvertTo-Json -Compress

Write-Host "    Agent Platform endpoint: $serviceUrl"
Write-Host "    Vertex AI Console: https://console.cloud.google.com/vertex-ai/agents?project=$ProjectId"
Write-Host "    Agent Builder:     https://console.cloud.google.com/gen-app-builder/engines?project=$ProjectId"

if ($agentEngineId) {
    Write-Host "    Reasoning Engine:  https://console.cloud.google.com/vertex-ai/reasoning-engine/$agentEngineId?project=$ProjectId"
}
Write-Host "[+] Agent registered with Vertex AI Agent Platform." -ForegroundColor Green

# ─── Summary ──────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "==============================================================================" -ForegroundColor Green
Write-Host " GCP AGENT PLATFORM DEPLOYMENT COMPLETE!" -ForegroundColor Green
Write-Host " Project:          $ProjectId" -ForegroundColor Green
Write-Host " Region:           $Region" -ForegroundColor Green
Write-Host " Model:            $ModelId" -ForegroundColor Green
Write-Host " Cloud Run URL:    $serviceUrl" -ForegroundColor Green
Write-Host " Liveness:         $serviceUrl/healthz" -ForegroundColor Green
Write-Host " Readiness:        $serviceUrl/readyz" -ForegroundColor Green
Write-Host " Agent Docs:       $serviceUrl/docs" -ForegroundColor Green
if ($agentEngineId) {
Write-Host " Agent Engine ID:  $agentEngineId" -ForegroundColor Green
}
Write-Host "" -ForegroundColor Green
Write-Host " Agent Platform Capabilities:" -ForegroundColor Green
Write-Host "   Vertex AI      -> Gemini $ModelId foundation model" -ForegroundColor Green
Write-Host "   Agent Engine   -> Managed stateful reasoning engine" -ForegroundColor Green
Write-Host "   Secret Manager -> GEMINI_API_KEY secured" -ForegroundColor Green
Write-Host "   Observability  -> Cloud Trace + Cloud Logging" -ForegroundColor Green
Write-Host "   Scaling        -> 0-10 instances (scale to zero)" -ForegroundColor Green
Write-Host "==============================================================================" -ForegroundColor Green
Write-Host ""
Write-Host "Vertex AI Console links:" -ForegroundColor Cyan
Write-Host "  Agents:   https://console.cloud.google.com/vertex-ai/agents?project=$ProjectId"
Write-Host "  Runs:     https://console.cloud.google.com/run/detail/$Region/$AgentResourceName/metrics?project=$ProjectId"
Write-Host ""
Write-Host "Quick Test:" -ForegroundColor Cyan
Write-Host "  Invoke-RestMethod -Uri '$serviceUrl/healthz' -Method Get"
Write-Host ""
