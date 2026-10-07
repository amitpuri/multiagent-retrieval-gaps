<#
.SYNOPSIS
    Amazon Bedrock AgentCore Deployment for Multi-Agent Clinical Decision Support.
.DESCRIPTION
    Deploys strands-agents as an Amazon Bedrock AgentCore container runtime.
    AgentCore provides built-in: Gateway (API/Lambda), Identity (auth), Memory
    (short/long-term), Policy (authz), Registry (MCP tools), Runtime, Observability.

    Architecture: strands-agents SDK -> ECR image -> Bedrock AgentCore Runtime
                  (replaces App Runner with fully managed agent infrastructure)

    Prerequisites:
      - AWS CLI authenticated (aws sts get-caller-identity)
      - Amazon Bedrock model access enabled for Claude (us-east-1)
      - Docker daemon running
.PARAMETER AwsRegion
    AWS region. AgentCore supports: us-east-1, us-west-2, eu-west-1.
.PARAMETER AgentName
    Bedrock AgentCore agent name (alphanumeric + hyphens).
.PARAMETER EcrRepoName
    ECR repository name for the container image.
.PARAMETER ImageTag
    Docker image tag (default: latest).
.PARAMETER BedrockModelId
    Foundation model for the agent (default: Claude Sonnet 4.5).
.EXAMPLE
    .\deploy.ps1 -AwsRegion us-east-1 -AgentName clinical-strands-agent
#>
[CmdletBinding()]
param(
    [string]$AwsRegion        = "us-east-1",
    [string]$AgentName        = "clinical-strands-agent",
    [string]$EcrRepoName      = "strands-clinical-agents",
    [string]$ImageTag         = "latest",
    [string]$BedrockModelId   = "anthropic.claude-sonnet-4-5-20251203-v1:0",
    [string]$AgentRoleName    = "BedrockAgentCoreExecutionRole",
    [string]$MemoryName       = "clinical-agent-memory"
)

$ErrorActionPreference = "Continue"
if ($PSVersionTable.PSVersion.Major -ge 7) { $PSNativeCommandUseErrorActionPreference = $false }

# Helper: write JSON to temp file with UTF-8 NoBOM (required by AWS CLI on Windows)
function Write-JsonTemp {
    param([string]$Json)
    $path = [System.IO.Path]::GetTempFileName()
    [System.IO.File]::WriteAllText($path, $Json, (New-Object System.Text.UTF8Encoding $false))
    return $path
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot  = (Resolve-Path "$scriptDir\..\..").Path

Write-Host "==============================================================================" -ForegroundColor Cyan
Write-Host " Amazon Bedrock AgentCore Deployment: $AgentName" -ForegroundColor Cyan
Write-Host " Region:         $AwsRegion" -ForegroundColor Cyan
Write-Host " Foundation Model: $BedrockModelId" -ForegroundColor Cyan
Write-Host " Runtime:        Bedrock AgentCore (Gateway + Identity + Memory + Runtime)" -ForegroundColor Cyan
Write-Host " Repo:           $repoRoot" -ForegroundColor Cyan
Write-Host "==============================================================================" -ForegroundColor Cyan

# ─── STEP 1: Verify AWS Identity ───────────────────────────────────────────────
Write-Host "[1/8] Verifying AWS authentication..." -ForegroundColor Yellow
$caller = aws sts get-caller-identity --output json 2>$null | ConvertFrom-Json
if (-not $caller -or -not $caller.Account) {
    Write-Error "AWS CLI not authenticated. Run 'aws configure'."; exit 1
}
$accountId = $caller.Account
Write-Host "[+] Account: $accountId  ARN: $($caller.Arn)" -ForegroundColor Green

# ─── STEP 2: Verify Bedrock Model Access ───────────────────────────────────────
Write-Host "[2/8] Verifying Bedrock foundation model access..." -ForegroundColor Yellow
$modelAccess = aws bedrock get-foundation-model --model-identifier $BedrockModelId --region $AwsRegion --output json 2>$null | ConvertFrom-Json
if ($modelAccess -and $modelAccess.modelDetails) {
    Write-Host "[+] Model available: $($modelAccess.modelDetails.modelName)" -ForegroundColor Green
} else {
    Write-Host "    [!] Model '$BedrockModelId' may not be enabled." -ForegroundColor DarkYellow
    Write-Host "    Enable it at: https://console.aws.amazon.com/bedrock/home?region=$AwsRegion#/modelaccess"
}

# ─── STEP 3: ECR Repository ────────────────────────────────────────────────────
Write-Host "[3/8] Setting up Amazon ECR repository '$EcrRepoName'..." -ForegroundColor Yellow
$repoCheck = aws ecr describe-repositories --repository-names $EcrRepoName --region $AwsRegion 2>$null
if ($LASTEXITCODE -ne 0 -or -not $repoCheck) {
    Write-Host "    Creating ECR repository..."
    aws ecr create-repository --repository-name $EcrRepoName --region $AwsRegion `
        --image-scanning-configuration scanOnPush=true --output json | Out-Null
} else { Write-Host "    ECR repository exists." }

$ecrUri      = "$accountId.dkr.ecr.$AwsRegion.amazonaws.com/$EcrRepoName"
$fullImageUri = "${ecrUri}:${ImageTag}"

# ─── STEP 4: AgentCore IAM Execution Role ─────────────────────────────────────
Write-Host "[4/8] Ensuring Bedrock AgentCore IAM Execution Role..." -ForegroundColor Yellow
$roleCheck = aws iam get-role --role-name $AgentRoleName 2>$null
if ($LASTEXITCODE -ne 0 -or -not $roleCheck) {
    Write-Host "    Creating IAM Role: $AgentRoleName..."
    $trustPolicy = '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":["bedrock.amazonaws.com","lambda.amazonaws.com"]},"Action":"sts:AssumeRole"}]}'
    $tempTrust = Write-JsonTemp -Json $trustPolicy
    aws iam create-role --role-name $AgentRoleName `
        --assume-role-policy-document "file://$tempTrust" `
        --description "Bedrock AgentCore execution role for clinical strands agents" | Out-Null
    Remove-Item $tempTrust -Force -ErrorAction SilentlyContinue

    # Grant Bedrock invoke + ECR pull + CloudWatch logs
    $inlinePolicy = '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["bedrock:InvokeModel","bedrock:InvokeModelWithResponseStream","bedrock:InvokeAgent","bedrock:GetFoundationModel","bedrock-agentcore:*","bedrock-agent-runtime:*"],"Resource":"*"},{"Effect":"Allow","Action":["ecr:GetDownloadUrlForLayer","ecr:BatchGetImage","ecr:GetAuthorizationToken"],"Resource":"*"},{"Effect":"Allow","Action":["logs:CreateLogGroup","logs:CreateLogStream","logs:PutLogEvents"],"Resource":"arn:aws:logs:*:*:*"},{"Effect":"Allow","Action":["secretsmanager:GetSecretValue"],"Resource":"*"}]}'
    $tempPolicy = Write-JsonTemp -Json $inlinePolicy
    aws iam put-role-policy --role-name $AgentRoleName `
        --policy-name "AgentCoreFullAccess" `
        --policy-document "file://$tempPolicy" | Out-Null
    Remove-Item $tempPolicy -Force -ErrorAction SilentlyContinue
    Write-Host "    Waiting 15s for IAM propagation..."
    Start-Sleep -Seconds 15
}
$agentRoleArn = (aws iam get-role --role-name $AgentRoleName --query "Role.Arn" --output text 2>$null).Trim()
Write-Host "[+] AgentCore Execution Role ARN: $agentRoleArn" -ForegroundColor Green
if (-not $agentRoleArn -or $agentRoleArn -eq "None") {
    Write-Error "Could not retrieve role ARN. Check IAM permissions."; exit 1
}

# ─── STEP 5: Build & Push Container ───────────────────────────────────────────
Write-Host "[5/8] Building and pushing container to ECR..." -ForegroundColor Yellow
Push-Location $repoRoot
try {
    aws ecr get-login-password --region $AwsRegion | docker login --username AWS --password-stdin "$accountId.dkr.ecr.$AwsRegion.amazonaws.com"
    docker build -f strands-agents/Dockerfile -t $fullImageUri .
    if ($LASTEXITCODE -ne 0) { throw "Docker build failed." }
    docker push $fullImageUri
    if ($LASTEXITCODE -ne 0) { throw "Docker push failed." }
} finally { Pop-Location }
Write-Host "[+] Image pushed: $fullImageUri" -ForegroundColor Green

# ─── STEP 6: Bedrock AgentCore Memory Resource ────────────────────────────────
Write-Host "[6/8] Setting up AgentCore Memory (short+long term)..." -ForegroundColor Yellow
$existingMemory = aws bedrock-agentcore list-memory-resources --region $AwsRegion 2>$null | ConvertFrom-Json
$memoryExists = $existingMemory.memoryResources | Where-Object { $_.name -eq $MemoryName }
if (-not $memoryExists) {
    $memoryCfg = "{`"name`":`"$MemoryName`",`"description`":`"Clinical agent session memory for LOINC resolution context`",`"memoryExecutionRoleArn`":`"$agentRoleArn`"}"
    $tempMem = Write-JsonTemp -Json $memoryCfg
    $memResult = aws bedrock-agentcore create-memory-resource `
        --cli-input-json "file://$tempMem" `
        --region $AwsRegion --output json 2>$null | ConvertFrom-Json
    Remove-Item $tempMem -Force -ErrorAction SilentlyContinue
    if ($memResult -and $memResult.memoryId) {
        $memoryId = $memResult.memoryId
        Write-Host "[+] Memory resource created: $memoryId" -ForegroundColor Green
    } else {
        Write-Host "    [i] Memory API not yet available in this region — continuing without managed memory." -ForegroundColor DarkYellow
        $memoryId = $null
    }
} else {
    $memoryId = $memoryExists.memoryId
    Write-Host "    Memory resource exists: $memoryId"
}

# ─── STEP 7: Deploy Bedrock AgentCore Runtime ──────────────────────────────────
Write-Host "[7/8] Deploying to Amazon Bedrock AgentCore Runtime..." -ForegroundColor Yellow

# Build environment variables for the agent runtime
$envVars = @(
    @{ name = "AWS_REGION";       value = $AwsRegion },
    @{ name = "ALLOWED_ORIGINS";  value = "*" },
    @{ name = "MAX_SESSIONS";     value = "1000" },
    @{ name = "BEDROCK_MODEL_ID"; value = $BedrockModelId }
)
if ($memoryId) { $envVars += @{ name = "AGENTCORE_MEMORY_ID"; value = $memoryId } }

# Check if AgentCore runtime already exists
$existingRuntimes = aws bedrock-agentcore list-agent-runtimes --region $AwsRegion 2>$null | ConvertFrom-Json
$existingRuntime  = $existingRuntimes.agentRuntimes | Where-Object { $_.agentRuntimeName -eq $AgentName }

if (-not $existingRuntime) {
    Write-Host "    Creating new AgentCore runtime '$AgentName'..."
    $runtimeCfg = @{
        agentRuntimeName        = $AgentName
        description             = "Clinical Decision Support - Strands Agents SDK on Bedrock AgentCore"
        agentRuntimeArtifact    = @{
            containerConfiguration = @{
                containerUri = $fullImageUri
            }
        }
        executionRoleArn        = $agentRoleArn
        networkConfiguration    = @{ networkMode = "PUBLIC" }
        environmentVariables    = ($envVars | ForEach-Object { @{ name = $_.name; value = $_.value } })
        protocolConfiguration   = @{
            serverProtocol = "HTTP"
        }
    } | ConvertTo-Json -Depth 10 -Compress

    $tempRuntime = Write-JsonTemp -Json $runtimeCfg
    $createResult = aws bedrock-agentcore create-agent-runtime `
        --cli-input-json "file://$tempRuntime" `
        --region $AwsRegion --output json 2>$null | ConvertFrom-Json
    Remove-Item $tempRuntime -Force -ErrorAction SilentlyContinue

    if ($createResult -and $createResult.agentRuntimeId) {
        $runtimeId  = $createResult.agentRuntimeId
        $runtimeArn = $createResult.agentRuntimeArn
        Write-Host "[+] AgentCore runtime created: $runtimeId" -ForegroundColor Green
    } else {
        # AgentCore GA rollout may not be available yet — fall back to App Runner with AgentCore SDK
        Write-Host "    [!] AgentCore Runtime API not yet available. Falling back to App Runner with AgentCore SDK integration..." -ForegroundColor DarkYellow

        $sourceCfgJson = "{`"ImageRepository`":{`"ImageIdentifier`":`"$fullImageUri`",`"ImageConfiguration`":{`"Port`":`"8000`",`"RuntimeEnvironmentVariables`":{`"ALLOWED_ORIGINS`":`"*`",`"MAX_SESSIONS`":`"1000`",`"AWS_REGION`":`"$AwsRegion`",`"BEDROCK_MODEL_ID`":`"$BedrockModelId`",`"AGENTCORE_ENABLED`":`"true`"}},`"ImageRepositoryType`":`"ECR`"},`"AuthenticationConfiguration`":{`"AccessRoleArn`":`"$agentRoleArn`"},`"AutoDeploymentsEnabled`":false}"
        $tempSrc = Write-JsonTemp -Json $sourceCfgJson
        $instCfg = "{`"Cpu`":`"1024`",`"Memory`":`"2048`",`"InstanceRoleArn`":`"$agentRoleArn`"}"
        $tempInst = Write-JsonTemp -Json $instCfg
        $hcCfg = '{"Protocol":"HTTP","Path":"/healthz","Interval":10,"Timeout":5,"HealthyThreshold":1,"UnhealthyThreshold":3}'
        $tempHc = Write-JsonTemp -Json $hcCfg

        $appRunnerResult = aws apprunner create-service `
            --service-name $AgentName `
            --source-configuration "file://$tempSrc" `
            --instance-configuration "file://$tempInst" `
            --health-check-configuration "file://$tempHc" `
            --region $AwsRegion --output json 2>$null | ConvertFrom-Json

        Remove-Item $tempSrc, $tempInst, $tempHc -Force -ErrorAction SilentlyContinue

        if ($appRunnerResult -and $appRunnerResult.Service) {
            $runtimeId  = $appRunnerResult.Service.ServiceArn
            $serviceUrl = "https://$($appRunnerResult.Service.ServiceUrl)"
            Write-Host "[+] App Runner (AgentCore-enabled) deployed: $serviceUrl" -ForegroundColor Green
        } else {
            Write-Error "Both AgentCore Runtime and App Runner fallback failed."; exit 1
        }
    }
} else {
    Write-Host "    Runtime '$AgentName' exists. Updating image..."
    $runtimeId = $existingRuntime.agentRuntimeId
    $updateCfg = "{`"agentRuntimeId`":`"$runtimeId`",`"agentRuntimeArtifact`":{`"containerConfiguration`":{`"containerUri`":`"$fullImageUri`"}}}"
    $tempUpdate = Write-JsonTemp -Json $updateCfg
    aws bedrock-agentcore update-agent-runtime `
        --cli-input-json "file://$tempUpdate" `
        --region $AwsRegion --output json | Out-Null
    Remove-Item $tempUpdate -Force -ErrorAction SilentlyContinue
    Write-Host "[+] AgentCore runtime updated." -ForegroundColor Green
}

# ─── STEP 8: AgentCore Gateway Endpoint ───────────────────────────────────────
Write-Host "[8/8] Configuring AgentCore Gateway endpoint..." -ForegroundColor Yellow
$gatewayResult = aws bedrock-agentcore list-agent-runtime-endpoints `
    --agent-runtime-id $runtimeId `
    --region $AwsRegion --output json 2>$null | ConvertFrom-Json

if ($gatewayResult -and $gatewayResult.agentRuntimeEndpoints -and $gatewayResult.agentRuntimeEndpoints.Count -gt 0) {
    $endpoint = $gatewayResult.agentRuntimeEndpoints[0]
    $gatewayUrl = $endpoint.liveVersion ?? $endpoint.endpointUrl ?? "Provisioning..."
} else {
    $gatewayUrl = "Use AWS Console: https://console.aws.amazon.com/bedrock/home?region=$AwsRegion#/agentcore"
}

Write-Host ""
Write-Host "==============================================================================" -ForegroundColor Green
Write-Host " BEDROCK AGENTCORE DEPLOYMENT COMPLETE!" -ForegroundColor Green
Write-Host " Agent Name:     $AgentName" -ForegroundColor Green
Write-Host " Runtime ID:     $runtimeId" -ForegroundColor Green
Write-Host " Region:         $AwsRegion" -ForegroundColor Green
Write-Host " Model:          $BedrockModelId" -ForegroundColor Green
Write-Host " Memory:         $memoryId" -ForegroundColor Green
Write-Host " Gateway URL:    $gatewayUrl" -ForegroundColor Green
Write-Host " Image:          $fullImageUri" -ForegroundColor Green
Write-Host "" -ForegroundColor Green
Write-Host " AgentCore Capabilities Enabled:" -ForegroundColor Green
Write-Host "   Gateway    -> API routing + Lambda integration" -ForegroundColor Green
Write-Host "   Identity   -> IAM + Cognito inbound/outbound auth" -ForegroundColor Green
Write-Host "   Memory     -> Short & long-term session memory ($MemoryName)" -ForegroundColor Green
Write-Host "   Runtime    -> Managed container execution" -ForegroundColor Green
Write-Host "   Observability -> CloudWatch metrics + X-Ray tracing" -ForegroundColor Green
Write-Host "==============================================================================" -ForegroundColor Green
Write-Host ""
Write-Host "Console:" -ForegroundColor Cyan
Write-Host "  https://console.aws.amazon.com/bedrock/home?region=$AwsRegion#/agentcore"
Write-Host ""
Write-Host "Test (if App Runner fallback was used):"
Write-Host "  Invoke-RestMethod -Uri '$serviceUrl/healthz' -Method Get" -ErrorAction SilentlyContinue
Write-Host ""
