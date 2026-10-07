<#
.SYNOPSIS
    Teardown Script for AWS Bedrock AgentCore Deployment.
#>
[CmdletBinding()]
param(
    [string]$AwsRegion    = "us-east-1",
    [string]$AgentName    = "clinical-strands-agent",
    [string]$EcrRepoName  = "strands-clinical-agents",
    [string]$AgentRoleName = "BedrockAgentCoreExecutionRole",
    [string]$MemoryName   = "clinical-agent-memory",
    [switch]$Force
)

$ErrorActionPreference = "Continue"

Write-Host "TEARDOWN: AWS Bedrock AgentCore [$AgentName] in [$AwsRegion]" -ForegroundColor Red

# 1. Delete AgentCore Runtime
$runtimes = aws bedrock-agentcore list-agent-runtimes --region $AwsRegion --output json 2>$null | ConvertFrom-Json
$runtime  = $runtimes.agentRuntimes | Where-Object { $_.agentRuntimeName -eq $AgentName }
if ($runtime) {
    Write-Host "Deleting AgentCore runtime: $($runtime.agentRuntimeId)..."
    aws bedrock-agentcore delete-agent-runtime --agent-runtime-id $runtime.agentRuntimeId --region $AwsRegion | Out-Null
    Write-Host "[+] AgentCore runtime deleted."
} else { Write-Host "AgentCore runtime '$AgentName' not found." }

# 2. Delete App Runner fallback (if it exists)
$svcArn = (aws apprunner list-services --region $AwsRegion --query "ServiceSummaryList[?ServiceName=='$AgentName'].ServiceArn" --output text 2>$null).Trim()
if ($svcArn -and $svcArn -ne "None") {
    Write-Host "Deleting App Runner fallback service..."
    aws apprunner delete-service --service-arn $svcArn --region $AwsRegion --output json | Out-Null
    Write-Host "[+] App Runner service deleted."
}

# 3. Delete Memory Resource
$memories = aws bedrock-agentcore list-memory-resources --region $AwsRegion --output json 2>$null | ConvertFrom-Json
$memory   = $memories.memoryResources | Where-Object { $_.name -eq $MemoryName }
if ($memory) {
    aws bedrock-agentcore delete-memory-resource --memory-id $memory.memoryId --region $AwsRegion | Out-Null
    Write-Host "[+] Memory resource deleted."
}

# 4. Delete ECR repo
if ($Force -or (Read-Host "Delete ECR repository '$EcrRepoName'? (y/N)") -match "^[yY]$") {
    aws ecr delete-repository --repository-name $EcrRepoName --region $AwsRegion --force 2>$null | Out-Null
    Write-Host "[+] ECR repository deleted."
}

# 5. Delete IAM role
if ($Force -or (Read-Host "Delete IAM role '$AgentRoleName'? (y/N)") -match "^[yY]$") {
    aws iam delete-role-policy --role-name $AgentRoleName --policy-name AgentCoreFullAccess 2>$null | Out-Null
    aws iam delete-role --role-name $AgentRoleName 2>$null | Out-Null
    Write-Host "[+] IAM role deleted."
}

Write-Host "[+] AWS AgentCore Teardown complete." -ForegroundColor Green
