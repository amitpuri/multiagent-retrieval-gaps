<#
.SYNOPSIS
    Service Health & Scenario Verification for Azure Container Apps in PowerShell.
#>
[CmdletBinding()]
param(
    [string]$ServiceUrl = "",
    [string]$AppName = "maf-clinical-agents",
    [string]$ResourceGroup = "rg-clinical-agents"
)

$ErrorActionPreference = "Stop"

if (-not $ServiceUrl) {
    foreach ($app in @($AppName, "clinical-agent-harness")) {
        $fqdn = (az containerapp show --name $app --resource-group $ResourceGroup --query "properties.configuration.ingress.fqdn" -o tsv 2>$null).Trim()
        if ($fqdn) {
            $ServiceUrl = "https://$fqdn"
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

Write-Host "`n[+] Azure Container App verified successfully!" -ForegroundColor Green
