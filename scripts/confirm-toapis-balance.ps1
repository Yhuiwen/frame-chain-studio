param(
    [Parameter(Mandatory = $true)][ValidateSet("SHORT_CONTINUITY_CANARY", "LEGACY_FULL_TWO_SHOT")][string]$Candidate,
    [switch]$AcknowledgeBalance,
    [ValidateSet("TOKEN_BALANCE_READ_ONLY")][string]$EvidenceType = "TOKEN_BALANCE_READ_ONLY",
    [Parameter(Mandatory = $true)][ValidatePattern("^[a-fA-F0-9]{64}$")][string]$PricingSnapshotHash,
    [Parameter(Mandatory = $true)][ValidateRange(0.000001, 500)][decimal]$RequiredBillingUnits
)

$ErrorActionPreference = "Stop"
if (-not $AcknowledgeBalance) {
    Write-Host "BALANCE_ACKNOWLEDGEMENT_REQUIRED"
    Write-Host "databaseUpdated=false"
    exit 0
}

$readiness = & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "toapis-paid-readiness.ps1") `
    -Candidate $Candidate -BillingUnit TOAPIS_CREDIT -PricingSnapshotHash $PricingSnapshotHash -MaxBillingUnits $RequiredBillingUnits -BalanceEvidencePrecheck
if ($LASTEXITCODE -ne 0 -or $readiness -notcontains "ready=true") {
    Write-Host "BALANCE_READINESS_FAILED"
    Write-Host "databaseUpdated=false"
    exit 1
}

$helper = Join-Path $PSScriptRoot "confirm_toapis_balance_api.py"
$raw = & python $helper --pricing-snapshot-hash $PricingSnapshotHash --required-billing-units ([string]$RequiredBillingUnits)
if ($LASTEXITCODE -ne 0) { throw "TOAPIS balance review API rejected the evidence." }
$result = $raw | ConvertFrom-Json
if (-not $result.account_balance_sufficient -or $result.live_orchestration_enabled) {
    throw "TOAPIS balance review persistence check failed."
}
Write-Host "databaseUpdated=true"
Write-Host "accountBalanceSufficient=true"
Write-Host "accountBalanceReviewedAt=$($result.account_balance_reviewed_at)"
Write-Host "pricingSnapshotHash=$PricingSnapshotHash"
Write-Host "confirmedBillingUnits=$RequiredBillingUnits"
Write-Host "evidenceType=$EvidenceType"
Write-Host "liveOrchestrationEnabled=false"
