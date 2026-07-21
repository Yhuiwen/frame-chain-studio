param(
    [Parameter(Mandatory = $true)][int]$RunId,
    [switch]$AcknowledgeConsoleReview,
    [Parameter(Mandatory = $true)][string]$ExistingRemoteTaskId,
    [Parameter(Mandatory = $true)][ValidateRange(0.000001, 500)][decimal]$ActualBillingUnits,
    [ValidateSet("TOAPIS_CREDIT")][string]$BillingUnit = "TOAPIS_CREDIT",
    [ValidateSet("TOAPIS_CONSOLE_REVIEW")][string]$EvidenceType = "TOAPIS_CONSOLE_REVIEW"
)

$ErrorActionPreference = "Stop"
if (-not $AcknowledgeConsoleReview) {
    Write-Host "CONSOLE_REVIEW_ACKNOWLEDGEMENT_REQUIRED"
    Write-Host "databaseUpdated=false"
    exit 0
}
$helper = Join-Path $PSScriptRoot "review_toapis_video_canary_api.py"
$raw = & python $helper --run-id $RunId --existing-remote-task-id $ExistingRemoteTaskId --actual-billing-units ([string]$ActualBillingUnits)
if ($LASTEXITCODE -ne 0) { throw "VIDEO_CANARY_CONSOLE_REVIEW_FAILED" }
$result = $raw | ConvertFrom-Json
$review = @{
    run_id = $RunId
    remote_task_id = $ExistingRemoteTaskId
    actual_billing_units = ([string]$ActualBillingUnits)
    billing_unit = $BillingUnit
    evidence_type = $EvidenceType
    reviewed_at = (Get-Date).ToUniversalTime().ToString("o")
} | ConvertTo-Json
$review | Set-Content -Encoding UTF8 (Join-Path (Split-Path -Parent $PSScriptRoot) ".run\toapis-video-canary-console-review.json")
Write-Host "databaseUpdated=true"
Write-Host "actualBillingUnits=$($result.actual_billing_units)"
Write-Host "actualBillingSource=$($result.actual_billing_source)"
