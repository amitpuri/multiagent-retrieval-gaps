<#
.SYNOPSIS
    Teardown Script for Azure Deployment in PowerShell.
#>
[CmdletBinding()]
param(
    [string]$ResourceGroup = "rg-clinical-agents",
    [string]$AppName = "maf-clinical-agents",
    [switch]$DeleteEntireResourceGroup,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$cfgPath = Join-Path $scriptDir "config.env"
if (Test-Path $cfgPath) {
    Get-Content $cfgPath | ForEach-Object {
        if ($_ -match '^\s*([A-Za-z_0-9]+)\s*=\s*["'']?(.*?)["'']?\s*$') {
            $k = $matches[1]
            $v = $matches[2]
            if ($k -eq "RESOURCE_GROUP" -and -not $PSBoundParameters.ContainsKey('ResourceGroup') -and $v) { $ResourceGroup = $v }
            if ($k -eq "APP_NAME" -and -not $PSBoundParameters.ContainsKey('AppName') -and $v) { $AppName = $v }
        }
    }
}

Write-Host "TEARDOWN: Azure Resources in Resource Group [$ResourceGroup]" -ForegroundColor Yellow

$doDeleteRg = $DeleteEntireResourceGroup
if (-not $doDeleteRg -and -not $Force) {
    $choice = Read-Host "Delete entire Resource Group '$ResourceGroup' (including ACR and Environment)? (y/N)"
    if ($choice -match "^[yY]$") {
        $doDeleteRg = $true
    }
}

if ($doDeleteRg) {
    Write-Host "Deleting Resource Group $ResourceGroup..."
    az group delete --name $ResourceGroup --yes --no-wait
    Write-Host "[+] Resource group deletion initiated." -ForegroundColor Green
} else {
    Write-Host "Deleting Container App $AppName..."
    az containerapp delete --name $AppName --resource-group $ResourceGroup --yes 2>$null
    Write-Host "[+] Container App deleted." -ForegroundColor Green
}
