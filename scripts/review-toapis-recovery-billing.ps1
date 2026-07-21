param(
    [Parameter(Mandatory = $true)][int]$RunId,
    [switch]$AcknowledgeConsoleReview,
    [Parameter(Mandatory = $true)][string]$ImageRemoteTaskId,
    [Parameter(Mandatory = $true)][ValidateRange(0, 10000)][decimal]$ImageActualBillingUnits,
    [Parameter(Mandatory = $true)][string]$Shot1VideoRemoteTaskId,
    [Parameter(Mandatory = $true)][ValidateRange(0, 10000)][decimal]$Shot1VideoActualBillingUnits,
    [Parameter(Mandatory = $true)][string]$Shot2VideoRemoteTaskId,
    [Parameter(Mandatory = $true)][ValidateRange(0, 10000)][decimal]$Shot2VideoActualBillingUnits,
    [ValidateSet("TOAPIS_CREDIT")][string]$BillingUnit = "TOAPIS_CREDIT",
    [ValidateSet("TOAPIS_CONSOLE_REVIEW")][string]$EvidenceType = "TOAPIS_CONSOLE_REVIEW"
)

$ErrorActionPreference = "Stop"
if (-not $AcknowledgeConsoleReview) {
    Write-Host "CONSOLE_REVIEW_ACKNOWLEDGEMENT_REQUIRED"
    Write-Host "databaseUpdated=false"
    exit 0
}
if ($RunId -ne 6) { throw "RECOVERY_RUN_ID_INVALID" }
$helper = Join-Path $PSScriptRoot "review_toapis_recovery_billing.py"
$raw = & python $helper --run-id $RunId `
    --task-review 40 $ImageRemoteTaskId ([string]$ImageActualBillingUnits) `
    --task-review 39 $Shot1VideoRemoteTaskId ([string]$Shot1VideoActualBillingUnits) `
    --task-review 41 $Shot2VideoRemoteTaskId ([string]$Shot2VideoActualBillingUnits)
if ($LASTEXITCODE -ne 0) { throw "RECOVERY_CONSOLE_REVIEW_FAILED" }
$result = $raw | ConvertFrom-Json
Write-Host "databaseUpdated=true"
Write-Host "recoveryActualBillingUnits=$($result.recovery_actual_billing_units)"
Write-Host "lineageActualBillingUnits=$($result.lineage_actual_billing_units)"
Write-Host "actualBillingSource=$($result.actual_billing_source)"
