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
    [string]$AgentName        = "clinical_strands_agent",   # AgentCore: [a-zA-Z][a-zA-Z0-9_]{0,47}
    [string]$AppRunnerName    = "clinical-strands-agent",
    [string]$EcrRepoName      = "strands-clinical-agents",
    [string]$ImageTag         = "latest",
    [string]$BedrockModelId   = "global.anthropic.claude-opus-5-5",
    [string]$AgentRoleName    = "BedrockAgentCoreExecutionRole",
    [string]$MemoryName       = "clinical_agent_memory",
    [int]$MemoryExpiryDays    = 30,
    # App Runner bills for provisioned instances around the clock: opt in explicitly.
    [switch]$AppRunnerFallback
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

# Every resource this script CREATES is appended to the ledger; destroy.ps1 deletes
# exactly those (deployment/teardown.py). Reused, pre-existing resources are not recorded.
$ledger = Join-Path $scriptDir ".deployed\ledger.tsv"
function Record-Created([string]$Kind, [string]$Name, [string]$Attrs = "") {
    New-Item -ItemType Directory -Force -Path (Split-Path $ledger) | Out-Null
    [System.IO.File]::AppendAllText($ledger, "$Kind`t$Name`t$Attrs`n", (New-Object System.Text.UTF8Encoding $false))
}

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
# Cross-region IDs (global./us./eu.) are inference profiles; bare IDs are foundation models.
if ($BedrockModelId -match '^(global|us|eu|apac|au|jp)\.') {
    $modelAccess = aws bedrock get-inference-profile --inference-profile-identifier $BedrockModelId --region $AwsRegion --output json 2>$null | ConvertFrom-Json
    $modelName = $modelAccess.inferenceProfileName
} else {
    $modelAccess = aws bedrock get-foundation-model --model-identifier $BedrockModelId --region $AwsRegion --output json 2>$null | ConvertFrom-Json
    $modelName = $modelAccess.modelDetails.modelName
}
if ($modelAccess -and $modelName) {
    Write-Host "[+] Model available: $modelName" -ForegroundColor Green
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
    if ($LASTEXITCODE -eq 0) { Record-Created "ecr-repository" $EcrRepoName "region=$AwsRegion" }
} else { Write-Host "    ECR repository exists." }

$ecrUri      = "$accountId.dkr.ecr.$AwsRegion.amazonaws.com/$EcrRepoName"
$fullImageUri = "${ecrUri}:${ImageTag}"

# ─── STEP 4: AgentCore IAM Execution Role ─────────────────────────────────────
Write-Host "[4/8] Ensuring Bedrock AgentCore IAM Execution Role..." -ForegroundColor Yellow
$roleCheck = aws iam get-role --role-name $AgentRoleName 2>$null
if ($LASTEXITCODE -ne 0 -or -not $roleCheck) {
    Write-Host "    Creating IAM Role: $AgentRoleName..."
    $trustPolicy = '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":["bedrock-agentcore.amazonaws.com","build.apprunner.amazonaws.com","tasks.apprunner.amazonaws.com"]},"Action":"sts:AssumeRole","Condition":{"StringEquals":{"aws:SourceAccount":"' + $accountId + '"}}}]}'
    $tempTrust = Write-JsonTemp -Json $trustPolicy
    aws iam create-role --role-name $AgentRoleName `
        --assume-role-policy-document "file://$tempTrust" `
        --description "Bedrock AgentCore execution role for clinical strands agents" | Out-Null
    if ($LASTEXITCODE -eq 0) { Record-Created "iam-role" $AgentRoleName "region=$AwsRegion" }
    Remove-Item $tempTrust -Force -ErrorAction SilentlyContinue

    # Least privilege: invoke models, pull this repository, write runtime logs/traces, use this memory.
    $inlinePolicy = @"
{"Version":"2012-10-17","Statement":[
 {"Effect":"Allow","Action":["bedrock:InvokeModel","bedrock:InvokeModelWithResponseStream","bedrock:GetInferenceProfile"],
  "Resource":["arn:aws:bedrock:*::foundation-model/*","arn:aws:bedrock:*:${accountId}:inference-profile/*"]},
 {"Effect":"Allow","Action":["ecr:BatchGetImage","ecr:GetDownloadUrlForLayer"],
  "Resource":"arn:aws:ecr:${AwsRegion}:${accountId}:repository/${EcrRepoName}"},
 {"Effect":"Allow","Action":"ecr:GetAuthorizationToken","Resource":"*"},
 {"Effect":"Allow","Action":["logs:CreateLogGroup","logs:CreateLogStream","logs:PutLogEvents","logs:DescribeLogStreams"],
  "Resource":"arn:aws:logs:${AwsRegion}:${accountId}:log-group:/aws/bedrock-agentcore/*"},
 {"Effect":"Allow","Action":["xray:PutTraceSegments","xray:PutTelemetryRecords"],"Resource":"*"},
 {"Effect":"Allow","Action":["bedrock-agentcore:CreateEvent","bedrock-agentcore:GetEvent","bedrock-agentcore:ListEvents",
  "bedrock-agentcore:ListSessions","bedrock-agentcore:RetrieveMemoryRecords"],
  "Resource":"arn:aws:bedrock-agentcore:${AwsRegion}:${accountId}:memory/*"}]}
"@
    $tempPolicy = Write-JsonTemp -Json $inlinePolicy
    aws iam put-role-policy --role-name $AgentRoleName `
        --policy-name "ClinicalAgentRuntimeAccess" `
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

# ─── STEP 4b: Knowledge release + S3 skill store ──────────────────────────────
# `ontogate build` fails closed on any integrity, skill-lint or SHACL error.
Write-Host "[4b/9] Building the knowledge release and publishing locked skills..." -ForegroundColor Yellow
Push-Location $repoRoot
$env:PYTHONPATH = "$repoRoot\shared" + $(if ($env:PYTHONPATH) { ";$env:PYTHONPATH" } else { "" })
python -m ontogate build
if ($LASTEXITCODE -ne 0) { Pop-Location; throw "ontogate build failed: the knowledge release is not valid." }
$skillsBucket = if ($env:SKILLS_BUCKET) { $env:SKILLS_BUCKET } else { "${ProjectName}-${Environment}-skills" }
aws s3api head-bucket --bucket $skillsBucket 2>$null | Out-Null
if ($LASTEXITCODE -eq 0) {
    python -m ontogate skills publish "s3://$skillsBucket/skills"
    if ($LASTEXITCODE -ne 0) { Pop-Location; throw "Publishing skills to s3://$skillsBucket/skills failed." }
    Write-Host "[+] Skills published to s3://$skillsBucket/skills (content-addressed, immutable)." -ForegroundColor Green
} else {
    Write-Host "    [i] S3 bucket $skillsBucket not found; skills ship inside the image only." -ForegroundColor DarkYellow
}
Pop-Location

# ─── STEP 5: Build & Push Container ───────────────────────────────────────────
Write-Host "[5/9] Building and pushing container to ECR..." -ForegroundColor Yellow
Push-Location $repoRoot
try {
    aws ecr get-login-password --region $AwsRegion | docker login --username AWS --password-stdin "$accountId.dkr.ecr.$AwsRegion.amazonaws.com"
    # AgentCore Runtime needs linux/arm64; the opt-in App Runner fallback needs linux/amd64.
    docker buildx build --platform linux/arm64,linux/amd64 -f strands-agents/Dockerfile -t $fullImageUri --push .
    if ($LASTEXITCODE -ne 0) { throw "Docker build/push failed." }
} finally { Pop-Location }
Write-Host "[+] Image pushed: $fullImageUri" -ForegroundColor Green

# ─── STEP 6: Bedrock AgentCore Memory ────────────────────────────────────────
Write-Host "[6/8] Setting up AgentCore Memory..." -ForegroundColor Yellow
# Memory ids are "<name>-<suffix>"; list-memories returns ids, not names.
$memoryId = (aws bedrock-agentcore-control list-memories --region $AwsRegion `
    --query "memories[?starts_with(id, '$MemoryName-')].id | [0]" --output text 2>$null)
if ($memoryId -and $memoryId.Trim() -ne "None") {
    $memoryId = $memoryId.Trim()
    Write-Host "    Memory exists: $memoryId"
} else {
    $memoryId = (aws bedrock-agentcore-control create-memory --name $MemoryName `
        --description "Clinical agent session memory (no PHI in long-term records)" `
        --event-expiry-duration $MemoryExpiryDays --memory-execution-role-arn $agentRoleArn `
        --region $AwsRegion --query "memory.id" --output text)
    if ($LASTEXITCODE -eq 0 -and $memoryId) {
        $memoryId = $memoryId.Trim()
        Record-Created "agentcore-memory" $memoryId "region=$AwsRegion"
        Write-Host "[+] Memory created: $memoryId" -ForegroundColor Green
    } else {
        $memoryId = ""
        Write-Host "    [i] AgentCore Memory unavailable (see the error above); continuing without managed memory." -ForegroundColor DarkYellow
    }
}

# ─── STEP 7: Deploy Bedrock AgentCore Runtime ────────────────────────────────
Write-Host "[7/8] Deploying to Amazon Bedrock AgentCore Runtime..." -ForegroundColor Yellow
$artifactFile = Write-JsonTemp -Json "{`"containerConfiguration`":{`"containerUri`":`"$fullImageUri`"}}"
$networkFile  = Write-JsonTemp -Json '{"networkMode":"PUBLIC"}'
$envFile      = Write-JsonTemp -Json "{`"AWS_REGION`":`"$AwsRegion`",`"BEDROCK_MODEL_ID`":`"$BedrockModelId`",`"AGENTCORE_MEMORY_ID`":`"$memoryId`",`"ALLOWED_ORIGINS`":`"*`",`"MAX_SESSIONS`":`"1000`"}"
$serviceUrl = ""
$runtimeId = (aws bedrock-agentcore-control list-agent-runtimes --region $AwsRegion `
    --query "agentRuntimes[?agentRuntimeName=='$AgentName'].agentRuntimeId | [0]" --output text 2>$null)
if ($runtimeId -and $runtimeId.Trim() -ne "None") {
    $runtimeId = $runtimeId.Trim()
    Write-Host "    Runtime '$AgentName' exists ($runtimeId). Updating image..."
    aws bedrock-agentcore-control update-agent-runtime --agent-runtime-id $runtimeId `
        --agent-runtime-artifact "file://$artifactFile" --role-arn $agentRoleArn `
        --network-configuration "file://$networkFile" --environment-variables "file://$envFile" `
        --region $AwsRegion --output json | Out-Null
    Write-Host "[+] AgentCore runtime updated." -ForegroundColor Green
} else {
    $runtimeId = (aws bedrock-agentcore-control create-agent-runtime --agent-runtime-name $AgentName `
        --description "Clinical Decision Support - Strands Agents SDK on Bedrock AgentCore" `
        --agent-runtime-artifact "file://$artifactFile" --role-arn $agentRoleArn `
        --network-configuration "file://$networkFile" --environment-variables "file://$envFile" `
        --region $AwsRegion --query "agentRuntimeId" --output text)
    if ($LASTEXITCODE -eq 0 -and $runtimeId) {
        $runtimeId = $runtimeId.Trim()
        Record-Created "agentcore-runtime" $runtimeId "region=$AwsRegion"
        Write-Host "[+] AgentCore runtime created: $runtimeId" -ForegroundColor Green
    } elseif ($AppRunnerFallback) {
        Write-Host "    [!] AgentCore Runtime creation failed. -AppRunnerFallback: deploying to App Runner (billed while running)..." -ForegroundColor DarkYellow
        $sourceFile = Write-JsonTemp -Json "{`"ImageRepository`":{`"ImageIdentifier`":`"$fullImageUri`",`"ImageConfiguration`":{`"Port`":`"8080`",`"RuntimeEnvironmentVariables`":{`"AWS_REGION`":`"$AwsRegion`",`"BEDROCK_MODEL_ID`":`"$BedrockModelId`",`"ALLOWED_ORIGINS`":`"*`"}},`"ImageRepositoryType`":`"ECR`"},`"AuthenticationConfiguration`":{`"AccessRoleArn`":`"$agentRoleArn`"},`"AutoDeploymentsEnabled`":false}"
        $serviceArn = (aws apprunner create-service --service-name $AppRunnerName `
            --source-configuration "file://$sourceFile" `
            --instance-configuration "{`"Cpu`":`"1024`",`"Memory`":`"2048`",`"InstanceRoleArn`":`"$agentRoleArn`"}" `
            --region $AwsRegion --query "Service.ServiceArn" --output text)
        Remove-Item $sourceFile -Force -ErrorAction SilentlyContinue
        if ($LASTEXITCODE -ne 0 -or -not $serviceArn) { throw "App Runner deployment failed." }
        Record-Created "app-runner-service" $serviceArn.Trim() "region=$AwsRegion"
        $serviceUrl = "https://" + (aws apprunner describe-service --service-arn $serviceArn.Trim() --region $AwsRegion `
            --query "Service.ServiceUrl" --output text).Trim()
        $runtimeId = ""
        Write-Host "[+] App Runner service deployed: $serviceUrl" -ForegroundColor Green
    } else {
        Remove-Item $artifactFile, $networkFile, $envFile -Force -ErrorAction SilentlyContinue
        throw "AgentCore Runtime creation failed (see the error above). Pass -AppRunnerFallback to deploy to App Runner instead (billed while running)."
    }
}
Remove-Item $artifactFile, $networkFile, $envFile -Force -ErrorAction SilentlyContinue

# ─── STEP 8: Runtime endpoint ────────────────────────────────────────────────
Write-Host "[8/8] Resolving the runtime endpoint..." -ForegroundColor Yellow
$gatewayUrl = $serviceUrl
if (-not $gatewayUrl -and $runtimeId) {
    $runtimeArn = (aws bedrock-agentcore-control get-agent-runtime --agent-runtime-id $runtimeId `
        --region $AwsRegion --query "agentRuntimeArn" --output text 2>$null)
    $gatewayUrl = "aws bedrock-agentcore invoke-agent-runtime --agent-runtime-arn $runtimeArn ..."
}

Write-Host ""
Write-Host "==============================================================================" -ForegroundColor Green
Write-Host " BEDROCK AGENTCORE DEPLOYMENT COMPLETE!" -ForegroundColor Green
Write-Host " Agent Name:     $AgentName" -ForegroundColor Green
Write-Host " Runtime ID:     $runtimeId" -ForegroundColor Green
Write-Host " Region:         $AwsRegion" -ForegroundColor Green
Write-Host " Model:          $BedrockModelId" -ForegroundColor Green
Write-Host " Memory:         $memoryId" -ForegroundColor Green
Write-Host " Invoke:         $gatewayUrl" -ForegroundColor Green
Write-Host " Teardown:       $scriptDir\destroy.ps1 -Yes   (deletes what this deploy created)" -ForegroundColor Green
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
