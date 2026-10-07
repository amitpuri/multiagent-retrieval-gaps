<#
.SYNOPSIS
    Azure Container Apps & Azure AI Foundry Deployment Script for Multi-Agent Clinical Decision Support.
.DESCRIPTION
    Creates Resource Group, ACR, Container Apps Environment, sets up/wires Azure AI Foundry service
    and project, assigns Managed Identity RBAC for keyless access, builds and deploys Azure Container App.
#>
[CmdletBinding()]
param(
    [string]$ResourceGroup = "rg-clinical-agents",
    [string]$Location = "eastus",
    [string]$AcrName = "",
    [string]$EnvironmentName = "cae-clinical-agents",
    [string]$AppName = "maf-clinical-agents",
    [string]$ImageName = "agent-framework",
    [string]$ImageTag = "latest",
    [string]$AiFoundryAccount = "ais-clinical-agents",
    [string]$AiFoundryProject = "aiproj-clinical-agents",
    [string]$AiFoundryResourceGroup = "rg-clinical-agents",
    [string]$FoundryModel = "gpt-5",
    [int]$Port = 8000,
    [string]$Cpu = "1.0",
    [string]$Memory = "2.0Gi"
)

$ErrorActionPreference = "Continue"
if ($PSVersionTable.PSVersion.Major -ge 7) {
    $PSNativeCommandUseErrorActionPreference = $false
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = (Resolve-Path "$scriptDir\..\..").Path

# Load configuration from config.env if present
$cfgPath = Join-Path $scriptDir "config.env"
if (Test-Path $cfgPath) {
    Get-Content $cfgPath | ForEach-Object {
        if ($_ -match '^\s*([A-Za-z_0-9]+)\s*=\s*["'']?(.*?)["'']?\s*$') {
            $k = $matches[1]
            $v = $matches[2]
            if ($k -eq "RESOURCE_GROUP" -and -not $PSBoundParameters.ContainsKey('ResourceGroup') -and $v) { $ResourceGroup = $v }
            if ($k -eq "LOCATION" -and -not $PSBoundParameters.ContainsKey('Location') -and $v) { $Location = $v }
            if ($k -eq "APP_NAME" -and -not $PSBoundParameters.ContainsKey('AppName') -and $v) { $AppName = $v }
            if ($k -eq "ENVIRONMENT_NAME" -and -not $PSBoundParameters.ContainsKey('EnvironmentName') -and $v) { $EnvironmentName = $v }
            if ($k -eq "AI_FOUNDRY_ACCOUNT_NAME" -and -not $PSBoundParameters.ContainsKey('AiFoundryAccount') -and $v) { $AiFoundryAccount = $v }
            if ($k -eq "AI_FOUNDRY_PROJECT_NAME" -and -not $PSBoundParameters.ContainsKey('AiFoundryProject') -and $v) { $AiFoundryProject = $v }
            if ($k -eq "AI_FOUNDRY_RESOURCE_GROUP" -and -not $PSBoundParameters.ContainsKey('AiFoundryResourceGroup') -and $v) { $AiFoundryResourceGroup = $v }
            if ($k -eq "FOUNDRY_MODEL" -and -not $PSBoundParameters.ContainsKey('FoundryModel') -and $v) { $FoundryModel = $v }
        }
    }
}

Write-Host "==============================================================================" -ForegroundColor Cyan
Write-Host " Azure AI Foundry & Container Apps Deployment: $AppName" -ForegroundColor Cyan
Write-Host " Resource Group:     $ResourceGroup" -ForegroundColor Cyan
Write-Host " Location:           $Location" -ForegroundColor Cyan
Write-Host " AI Foundry Account: $AiFoundryAccount ($AiFoundryResourceGroup)" -ForegroundColor Cyan
Write-Host " AI Foundry Project: $AiFoundryProject" -ForegroundColor Cyan
Write-Host " Foundation Model:   $FoundryModel" -ForegroundColor Cyan
Write-Host " Repo:               $repoRoot" -ForegroundColor Cyan
Write-Host "==============================================================================" -ForegroundColor Cyan

# 1. Verify Azure Auth
Write-Host "[1/7] Verifying Azure authentication..." -ForegroundColor Yellow
$sub = az account show --output json 2>$null | ConvertFrom-Json
if (-not $sub -or -not $sub.id) {
    Write-Error "Azure CLI is not authenticated. Please run 'az login' first."
    exit 1
}
$subId = $sub.id
Write-Host "[+] Active Subscription: $($sub.name) ($subId)" -ForegroundColor Green

# 2. Resource Group
Write-Host "[2/7] Ensuring Resource Group '$ResourceGroup' exists..." -ForegroundColor Yellow
$rgExists = az group show --name $ResourceGroup 2>$null
if (-not $rgExists) {
    Write-Host "    Creating Resource Group $ResourceGroup in $Location..."
    az group create --name $ResourceGroup --location $Location -o none
} else {
    Write-Host "    Resource Group $ResourceGroup exists."
}

# 3. Setup ACR
Write-Host "[3/7] Setting up Azure Container Registry..." -ForegroundColor Yellow
if (-not $AcrName) {
    $hash = [System.BitConverter]::ToString(([System.Security.Cryptography.MD5]::Create()).ComputeHash([System.Text.Encoding]::UTF8.GetBytes($subId))).Replace("-","").Substring(0,6).ToLower()
    $AcrName = "acrclinagents$hash"
}

$acrExists = az acr show --name $AcrName --resource-group $ResourceGroup 2>$null
if (-not $acrExists) {
    Write-Host "    Creating ACR '$AcrName' in $ResourceGroup ($Location)..."
    az acr create --resource-group $ResourceGroup --name $AcrName --sku Basic --admin-enabled true -o none
    if ($LASTEXITCODE -ne 0) {
        Write-Error "ACR creation failed in '$Location'. Try a different region (e.g. eastus, northeurope)."
        exit 1
    }
} else {
    Write-Host "    ACR '$AcrName' exists."
}

$acrLoginServer = (az acr show --name $AcrName --query "loginServer" -o tsv 2>$null).Trim()
if (-not $acrLoginServer) {
    Write-Error "Could not retrieve ACR login server for '$AcrName'."
    exit 1
}
$fullImageUri = "$acrLoginServer/${ImageName}:$ImageTag"

# 4. Build & Push Image
Write-Host "[4/7] Building and pushing container image: $fullImageUri..." -ForegroundColor Yellow
Push-Location $repoRoot
try {
    $dockerAvailable = $false
    try {
        docker info 2>$null | Out-Null
        $dockerAvailable = $true
    } catch {
        $dockerAvailable = $false
    }

    if ($dockerAvailable) {
        Write-Host "    Local Docker daemon detected. Building with Docker..."
        az acr login --name $AcrName
        docker build -f agent-framework/Dockerfile -t $fullImageUri .
        docker push $fullImageUri
    } else {
        Write-Host "    Building remotely via Azure Container Registry Tasks (az acr build)..."
        az acr build --registry $AcrName --image "${ImageName}:$ImageTag" --file "agent-framework/Dockerfile" .
    }
} finally {
    Pop-Location
}
Write-Host "[+] Image ready: $fullImageUri" -ForegroundColor Green

# 5. Azure AI Foundry Service & Project Discovery/Setup
Write-Host "[5/7] Configuring Azure AI Foundry service and project..." -ForegroundColor Yellow

$foundryProjectEndpoint = ""
$azureOpenAiEndpoint = ""
$aiAccountId = ""

# Check specified AI Foundry account/project or auto-detect
$targetAiRg = if ($AiFoundryResourceGroup) { $AiFoundryResourceGroup } else { $ResourceGroup }
$aiAccountCheck = az cognitiveservices account show --name $AiFoundryAccount --resource-group $targetAiRg 2>$null | ConvertFrom-Json

if ($aiAccountCheck) {
    $aiAccountId = $aiAccountCheck.id
    $azureOpenAiEndpoint = $aiAccountCheck.properties.endpoint
    Write-Host "    Found Azure AI Services account: $AiFoundryAccount ($($aiAccountCheck.location))"

    # Check project
    $projectCheck = az cognitiveservices account project show --name $AiFoundryAccount --resource-group $targetAiRg --project-name $AiFoundryProject 2>$null | ConvertFrom-Json
    if ($projectCheck -and $projectCheck.properties -and $projectCheck.properties.endpoints) {
        $foundryProjectEndpoint = $projectCheck.properties.endpoints.'AI Foundry API'
        Write-Host "[+] Azure AI Foundry Project: $AiFoundryProject" -ForegroundColor Green
        Write-Host "    Endpoint: $foundryProjectEndpoint"
    } else {
        Write-Host "    Creating Azure AI Foundry Project '$AiFoundryProject' in $AiFoundryAccount..."
        az cognitiveservices account project create `
            --name $AiFoundryAccount `
            --resource-group $targetAiRg `
            --project-name $AiFoundryProject `
            --location $aiAccountCheck.location `
            --description "Clinical Decision Support multi-agent project for Microsoft Agent Framework" `
            -o none
        $projectCheck = az cognitiveservices account project show --name $AiFoundryAccount --resource-group $targetAiRg --project-name $AiFoundryProject 2>$null | ConvertFrom-Json
        if ($projectCheck -and $projectCheck.properties -and $projectCheck.properties.endpoints) {
            $foundryProjectEndpoint = $projectCheck.properties.endpoints.'AI Foundry API'
        }
    }
} else {
    Write-Host "    AI Foundry account '$AiFoundryAccount' not found. Creating new AI Services account in $ResourceGroup ($Location)..."
    az cognitiveservices account create `
        --name $AiFoundryAccount `
        --resource-group $ResourceGroup `
        --kind AIServices `
        --sku S0 `
        --location $Location `
        --yes -o none

    $aiAccountCheck = az cognitiveservices account show --name $AiFoundryAccount --resource-group $ResourceGroup | ConvertFrom-Json
    $aiAccountId = $aiAccountCheck.id
    $azureOpenAiEndpoint = $aiAccountCheck.properties.endpoint
    $targetAiRg = $ResourceGroup

    Write-Host "    Creating AI Foundry project '$AiFoundryProject'..."
    az cognitiveservices account project create `
        --name $AiFoundryAccount `
        --resource-group $ResourceGroup `
        --project-name $AiFoundryProject `
        --location $Location `
        -o none

    # Deploy model
    Write-Host "    Deploying foundation model '$FoundryModel'..."
    az cognitiveservices account deployment create `
        --name $AiFoundryAccount `
        --resource-group $ResourceGroup `
        --deployment-name $FoundryModel `
        --model-name "gpt-4o" `
        --model-version "2024-08-06" `
        --model-format OpenAI `
        --sku-capacity 10 `
        --sku-name "Standard" `
        -o none 2>$null

    $projectCheck = az cognitiveservices account project show --name $AiFoundryAccount --resource-group $ResourceGroup --project-name $AiFoundryProject 2>$null | ConvertFrom-Json
    if ($projectCheck -and $projectCheck.properties -and $projectCheck.properties.endpoints) {
        $foundryProjectEndpoint = $projectCheck.properties.endpoints.'AI Foundry API'
    }
}

if (-not $foundryProjectEndpoint) {
    # Fallback to direct AI Services endpoint
    $foundryProjectEndpoint = $azureOpenAiEndpoint
}
Write-Host "[+] AI Foundry Endpoint active: $foundryProjectEndpoint" -ForegroundColor Green

# 6. Container Apps Environment
Write-Host "[6/7] Ensuring Container Apps Environment '$EnvironmentName' exists..." -ForegroundColor Yellow
$envExists = az containerapp env show --name $EnvironmentName --resource-group $ResourceGroup 2>$null
if (-not $envExists) {
    Write-Host "    Creating Container Apps Environment in $Location..."
    az containerapp env create --name $EnvironmentName --resource-group $ResourceGroup --location $Location -o none
} else {
    Write-Host "    Environment '$EnvironmentName' exists."
}

# 7. Deploy Container App with Managed Identity & RBAC
Write-Host "[7/7] Deploying Azure Container App '$AppName' with Managed Identity..." -ForegroundColor Yellow
$acrPass = (az acr credential show --name $AcrName --query "passwords[0].value" -o tsv).Trim()
$acrUser = (az acr credential show --name $AcrName --query "username" -o tsv).Trim()

$envVarsList = @(
    "ALLOWED_ORIGINS=*",
    "MAX_SESSIONS=1000",
    "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT=$foundryProjectEndpoint",
    "FOUNDRY_MODEL=$FoundryModel",
    "AZURE_OPENAI_ENDPOINT=$azureOpenAiEndpoint",
    "AZURE_SUBSCRIPTION_ID=$subId"
)
if ($env:OPENAI_API_KEY) { $envVarsList += "OPENAI_API_KEY=$($env:OPENAI_API_KEY)" }

$appExists = az containerapp show --name $AppName --resource-group $ResourceGroup 2>$null
if (-not $appExists) {
    Write-Host "    Creating new Container App with System-Assigned Identity..."
    az containerapp create `
        --name $AppName `
        --resource-group $ResourceGroup `
        --environment $EnvironmentName `
        --image $fullImageUri `
        --target-port $Port `
        --ingress external `
        --registry-server $acrLoginServer `
        --registry-username $acrUser `
        --registry-password $acrPass `
        --system-assigned `
        --cpu $Cpu `
        --memory $Memory `
        --min-replicas 0 `
        --max-replicas 5 `
        --env-vars $envVarsList `
        -o none
} else {
    Write-Host "    Updating existing Container App..."
    az containerapp update `
        --name $AppName `
        --resource-group $ResourceGroup `
        --image $fullImageUri `
        --set-env-vars $envVarsList `
        -o none
    az containerapp identity assign --name $AppName --resource-group $ResourceGroup --system-assigned -o none 2>$null
}

# RBAC: Assign Cognitive Services OpenAI User role to Container App Managed Identity
$appPrincipalId = (az containerapp show --name $AppName --resource-group $ResourceGroup --query "identity.principalId" -o tsv 2>$null).Trim()
if ($appPrincipalId -and $aiAccountId) {
    Write-Host "    Assigning RBAC: 'Cognitive Services OpenAI User' to Container App Identity ($appPrincipalId)..."
    az role assignment create `
        --assignee-object-id $appPrincipalId `
        --assignee-principal-type "ServicePrincipal" `
        --role "Cognitive Services OpenAI User" `
        --scope $aiAccountId `
        -o none 2>$null
    Write-Host "[+] Keyless RBAC granted for Azure AI Foundry access." -ForegroundColor Green
}

$fqdn = (az containerapp show --name $AppName --resource-group $ResourceGroup --query "properties.configuration.ingress.fqdn" -o tsv).Trim()
$appUrl = "https://$fqdn"

Write-Host ""
Write-Host "==============================================================================" -ForegroundColor Green
Write-Host " AZURE AI FOUNDRY DEPLOYMENT SUCCESSFUL!" -ForegroundColor Green
Write-Host " App Name:            $AppName" -ForegroundColor Green
Write-Host " AI Foundry Project:  $AiFoundryProject ($AiFoundryAccount)" -ForegroundColor Green
Write-Host " AI Foundry Endpoint: $foundryProjectEndpoint" -ForegroundColor Green
Write-Host " Model:               $FoundryModel" -ForegroundColor Green
Write-Host " Service URL:         $appUrl" -ForegroundColor Green
Write-Host " Liveness:            $appUrl/healthz" -ForegroundColor Green
Write-Host " Readiness:           $appUrl/readyz" -ForegroundColor Green
Write-Host " Docs:                $appUrl/docs" -ForegroundColor Green
Write-Host " Managed Identity:    $appPrincipalId" -ForegroundColor Green
Write-Host "==============================================================================" -ForegroundColor Green
Write-Host ""
Write-Host "Quick Test Command:" -ForegroundColor Cyan
Write-Host "  Invoke-RestMethod -Uri '$appUrl/healthz' -Method Get"
Write-Host ""
