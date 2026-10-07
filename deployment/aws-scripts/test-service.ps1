<#
.SYNOPSIS
    Service Health & Scenario Verification for AWS App Runner in PowerShell.
#>
[CmdletBinding()]
param(
    [string]$ServiceUrl = "",
    [string]$ServiceName = "clinical-strands-agent",
    [string]$AwsRegion = "us-east-1"
)

$ErrorActionPreference = "Stop"

if (-not $ServiceUrl) {
    foreach ($name in @($ServiceName, "strands-clinical-agents", "clinical-agent-harness")) {
        $serviceArn = (aws apprunner list-services --region $AwsRegion --query "ServiceSummaryList[?ServiceName=='$name'].ServiceArn" --output text 2>$null).Trim()
        if ($serviceArn -and $serviceArn -ne "None") {
            $rawUrl = (aws apprunner describe-service --service-arn $serviceArn --region $AwsRegion --query "Service.ServiceUrl" --output text 2>$null).Trim()
            $ServiceUrl = "https://$rawUrl"
            break
        }
    }
}

if (-not $ServiceUrl -or $ServiceUrl -eq "https://") {
    Write-Error "Service URL could not be determined. Pass -ServiceUrl 'https://...'"
    exit 1
}

Write-Host "==============================================================================" -ForegroundColor Cyan
Write-Host " Testing Clinical Agent Harness at: $ServiceUrl" -ForegroundColor Cyan
Write-Host "==============================================================================" -ForegroundColor Cyan

# 1. Healthz
Write-Host "`n[1/4] Testing Liveness (/healthz)..." -ForegroundColor Yellow
$healthz = Invoke-RestMethod -Uri "$ServiceUrl/healthz" -Method Get
$healthz | ConvertTo-Json

# 2. Readyz
Write-Host "`n[2/4] Testing Readiness & MCP Discovery (/readyz)..." -ForegroundColor Yellow
$readyz = Invoke-RestMethod -Uri "$ServiceUrl/readyz" -Method Get
$readyz | ConvertTo-Json

# 3. Create Session
Write-Host "`n[3/4] Creating Turn Session (/api/v1/sessions)..." -ForegroundColor Yellow
$sess = Invoke-RestMethod -Uri "$ServiceUrl/api/v1/sessions" -Method Post
$sess | ConvertTo-Json
$sessionId = $sess.session_id

# 4. Clinical Query
Write-Host "`n[4/4] Sending Scenario A Clinician Turn: 'Hb 13.5 | g/dL'..." -ForegroundColor Yellow
$body = @{
    prompt = "Hb 13.5 | g/dL"
    session_id = $sessionId
    user_id = "dr_puri"
} | ConvertTo-Json

$resp = Invoke-RestMethod -Uri "$ServiceUrl/api/v1/query" -Method Post -Body $body -ContentType "application/json"
$resp | ConvertTo-Json -Depth 5

Write-Host "`n[+] AWS App Runner service verified successfully!" -ForegroundColor Green
