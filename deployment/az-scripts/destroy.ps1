<#
.SYNOPSIS
    Teardown for the Azure deployment.
.DESCRIPTION
    Deletes exactly the resources deploy.ps1 created (recorded in .deployed\ledger.tsv),
    newest first, via deployment\teardown.py. Prints the plan unless -Yes is given.
.EXAMPLE
    .\destroy.ps1            # plan only
    .\destroy.ps1 -Yes       # delete (-Force is accepted as an alias)
    .\destroy.ps1 -Discover  # a deployment made before the ledger existed
#>
[CmdletBinding()]
param(
    [switch]$Yes,
    [switch]$Force,
    [switch]$Discover,
    [string]$DeleteResourceGroup
)
$teardownArgs = @("azure")
if ($Yes -or $Force) { $teardownArgs += "--yes" }
if ($Discover) { $teardownArgs += "--discover" }
if ($DeleteResourceGroup) { $teardownArgs += @("--delete-resource-group", $DeleteResourceGroup) }
python (Join-Path $PSScriptRoot "..\teardown.py") @teardownArgs
exit $LASTEXITCODE
