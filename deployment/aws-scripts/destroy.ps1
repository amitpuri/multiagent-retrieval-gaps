<#
.SYNOPSIS
    Teardown for the AWS deployment.
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
    [switch]$Discover
)
$teardownArgs = @("aws")
if ($Yes -or $Force) { $teardownArgs += "--yes" }
if ($Discover) { $teardownArgs += "--discover" }
python (Join-Path $PSScriptRoot "..\teardown.py") @teardownArgs
exit $LASTEXITCODE
