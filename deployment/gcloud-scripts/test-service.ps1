<#
.SYNOPSIS
    Service Health & Scenario Verification for Google Cloud Run in PowerShell.
#>
[CmdletBinding()]
param(
    [string]$ServiceUrl = "",
    [string]$ServiceName = "clinical-adk-agent",
    [string]$Region = "europe-west1",
    [string]$ProjectId = ""
)

$ErrorActionPreference = "Stop"

if (-not $ServiceUrl) {
    if (-not $ProjectId) {
        $ProjectId = (gcloud config get-value project 2>$null).Trim()
    }
    foreach ($svc in @($ServiceName, "clinical-agent-harness")) {
        $url = (gcloud run services describe $svc --platform=managed --region=$Region --project=$ProjectId --format="value(status.url)" 2>$null).Trim()
        if ($url) {
            $ServiceUrl = $url
            break
        }
    }
}

if (-not $ServiceUrl) {
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

Write-Host "`n[+] Cloud Run service verified successfully!" -ForegroundColor Green
