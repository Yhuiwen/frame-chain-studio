param(
    [Parameter(Mandatory = $true)][ValidateSet("SHORT_CONTINUITY_CANARY", "LEGACY_FULL_TWO_SHOT")][string]$Candidate,
    [ValidateSet("https://toapis.com/v1")][string]$ApiBaseUrl = "https://toapis.com/v1",
    [Parameter(Mandatory = $true)][ValidateSet("TOAPIS_CREDIT")][string]$BillingUnit,
    [Parameter(Mandatory = $true)][ValidatePattern("^[a-fA-F0-9]{64}$")][string]$PricingSnapshotHash,
    [Parameter(Mandatory = $true)][ValidateRange(0.000001, 500)][decimal]$MaxBillingUnits,
    [switch]$BalanceEvidencePrecheck
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$helper = Join-Path $PSScriptRoot "toapis_paid_readiness.py"

if ($ApiBaseUrl -ne "https://toapis.com/v1") {
    throw "Only the fixed official TOAPIS v1 base URL is permitted."
}

Push-Location $repoRoot
try {
    $arguments = @(
        $helper,
        "--candidate", $Candidate,
        "--billing-unit", $BillingUnit,
        "--pricing-snapshot-hash", $PricingSnapshotHash,
        "--max-billing-units", ([string]$MaxBillingUnits)
    )
    if ($BalanceEvidencePrecheck) { $arguments += "--balance-evidence-precheck" }
    python @arguments
    if ($LASTEXITCODE -ne 0) { throw "TOAPIS paid-readiness audit failed." }
}
finally {
    Pop-Location
}
