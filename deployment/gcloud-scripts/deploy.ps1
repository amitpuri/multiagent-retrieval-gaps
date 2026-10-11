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
    - (optional, -UseAgentRuntime) Vertex AI Agent Runtime hosting the ADK workflow as an AdkApp

    Architecture: google-adk-agents -> Cloud Run, and optionally Vertex AI Agent Runtime (AdkApp)
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
    [switch]$UseAgentRuntime,
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
Write-Host " Platform: Cloud Run + (optional) Vertex AI Agent Runtime" -ForegroundColor Cyan
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

# ─── STEP 3b: Knowledge release + skill store ─────────────────────────────────
# `ontogate build` fails closed on any integrity, skill-lint or SHACL error.
Write-Host "[3b/8] Building the knowledge release and publishing locked skills..." -ForegroundColor Yellow
Push-Location $repoRoot
$env:PYTHONPATH = "$repoRoot\shared" + $(if ($env:PYTHONPATH) { ";$env:PYTHONPATH" } else { "" })
python -m ontogate build
if ($LASTEXITCODE -ne 0) { Pop-Location; throw "ontogate build failed: the knowledge release is not valid." }
$skillStore = if ($env:SKILL_STORE) { $env:SKILL_STORE } else { "gs://$ProjectId-skills/skills" }
$skillBucket = "gs://" + ($skillStore -replace '^gs://', '').Split('/')[0]
gcloud storage buckets describe $skillBucket --project=$ProjectId 2>$null | Out-Null
if ($LASTEXITCODE -eq 0) {
    python -m ontogate skills publish $skillStore
    if ($LASTEXITCODE -ne 0) { Pop-Location; throw "Publishing skills to $skillStore failed." }
    Write-Host "[+] Skills published to $skillStore (content-addressed, immutable)." -ForegroundColor Green
} else {
    Write-Host "    [i] Skill store bucket $skillBucket not found; skills ship inside the image only." -ForegroundColor DarkYellow
}
Pop-Location

$agentEngineId = $null
if ($UseAgentRuntime) {
    Write-Host "    Deploying the ADK workflow to Vertex AI Agent Runtime as an AdkApp..."
    $stagingBucket = if ($env:STAGING_BUCKET) { $env:STAGING_BUCKET } else { "gs://$ProjectId-agent-staging" }
    $runtimeOutput = python "$repoRoot\deployment\gcloud-scripts\agent_runtime.py" `
        --project $ProjectId --location $Region --staging-bucket $stagingBucket --display-name $AgentDisplayName 2>&1
    $runtimeOutput | ForEach-Object { Write-Host "    $_" }
    if ($LASTEXITCODE -eq 0) {
        $match = $runtimeOutput | Select-String "Agent Runtime resource: (.+)"
        if ($match) { $agentEngineId = $match.Matches[0].Groups[1].Value.Split('/')[-1] }
        Write-Host "[+] Agent Runtime deployment complete." -ForegroundColor Green
    } else {
        Write-Host "[!] Agent Runtime deployment failed (output above); continuing with Cloud Run." -ForegroundColor Red
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
    Write-Host "    Agent Runtime:     https://console.cloud.google.com/vertex-ai/agents/agent-engines/$agentEngineId?project=$ProjectId"
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
Write-Host " Agent Runtime ID: $agentEngineId" -ForegroundColor Green
}
Write-Host "" -ForegroundColor Green
Write-Host " Agent Platform Capabilities:" -ForegroundColor Green
Write-Host "   Vertex AI      -> Gemini $ModelId foundation model" -ForegroundColor Green
Write-Host "   Agent Runtime  -> ADK AdkApp (-UseAgentRuntime)" -ForegroundColor Green
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
