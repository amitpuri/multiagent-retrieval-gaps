<#
.SYNOPSIS
    Teardown Script for Google Cloud Deployment.
#>
[CmdletBinding()]
param(
    [string]$ProjectId = "",
    [string]$Region = "europe-west1",
    [string]$ServiceName = "clinical-agent-harness",
    [string]$RepoName = "clinical-agents",
    [switch]$Force
)

$ErrorActionPreference = "Stop"

if (-not $ProjectId) {
    $ProjectId = (gcloud config get-value project 2>$null).Trim()
}

Write-Host "Teardown: Cloud Run Service [$ServiceName] in [$Region] (Project: $ProjectId)" -ForegroundColor Yellow

# Delete Cloud Run Service
Write-Host "Deleting Cloud Run service $ServiceName..."
gcloud run services delete $ServiceName --region=$Region --project=$ProjectId --quiet 2>$null

if ($Force -or (Read-Host "Delete Artifact Registry repository '$RepoName'? (y/N)") -match "^[yY]$") {
    Write-Host "Deleting Artifact Registry $RepoName..."
    gcloud artifacts repositories delete $RepoName --location=$Region --project=$ProjectId --quiet 2>$null
}

if ($Force -or (Read-Host "Delete Secret 'clinical-gemini-api-key'? (y/N)") -match "^[yY]$") {
    Write-Host "Deleting Secret clinical-gemini-api-key..."
    gcloud secrets delete "clinical-gemini-api-key" --project=$ProjectId --quiet 2>$null
}

Write-Host "[+] Teardown complete." -ForegroundColor Green
