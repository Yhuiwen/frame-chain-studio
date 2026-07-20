param(
    [switch]$ConfirmLive,
    [decimal]$MaxCost,
    [decimal]$MaxBillingUnits,
    [string]$BillingUnit,
    [string]$PricingSnapshotHash,
    [string]$ApiBaseUrl = "http://127.0.0.1:8000/api",
    [switch]$AutoApproveForVerification
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$backendRoot = Join-Path $repoRoot "backend"

Write-Host "Provider: TOAPIS"
Write-Host "Image model: doubao-seedream-5-0"
Write-Host "Video model: viduq3-pro"
Write-Host "Shots: 2; image tasks: max 2; video tasks: max 2"
Write-Host "Video duration: 4s; resolution: 720p; audio: false; image resolution: 2K"

if (-not $ConfirmLive) {
    Push-Location $backendRoot
    try {
        python -m pytest tests/test_toapis_provider.py -q
        if ($LASTEXITCODE -ne 0) { throw "TOAPIS offline contract tests failed." }
    }
    finally { Pop-Location }
    Write-Host "TOAPIS contract verified"
    Write-Host "BLOCKED_LIVE_VERIFICATION"
    Write-Host "networkCalled=false"
    Write-Host "uploadCalled=false"
    Write-Host "submitCalled=false"
    Write-Host "pollCalled=false"
    exit 0
}

if (-not $env:TOAPIS_API_KEY) { throw "TOAPIS_API_KEY must be set in the environment." }
if (-not $PSBoundParameters.ContainsKey("BillingUnit") -or -not $PSBoundParameters.ContainsKey("MaxBillingUnits")) {
    Write-Host "BILLING_UNIT_REQUIRED"
    throw "TOAPIS live verification requires -BillingUnit and -MaxBillingUnits; -MaxCost cannot convert credits to currency."
}
if ($BillingUnit -ne "TOAPIS_CREDIT") {
    Write-Host "BILLING_UNIT_MISMATCH"
    throw "TOAPIS model pricing must be compared in TOAPIS_CREDIT."
}
if ($MaxBillingUnits -lt 172.6) {
    Write-Host "BLOCKED_BY_BUDGET"
    Write-Host "uploadCalled=false"
    Write-Host "submitCalled=false"
    throw "Maximum billing units are below the current 172.6 TOAPIS_CREDIT estimate."
}
if ($MaxBillingUnits -gt 500) { throw "MaxBillingUnits exceeds the system safety ceiling of 500 TOAPIS_CREDIT." }
if ([string]::IsNullOrWhiteSpace($PricingSnapshotHash)) { throw "PricingSnapshotHash is required." }

Write-Host "Billing unit: TOAPIS_CREDIT"
Write-Host "Estimated billing units: 172.6"
Write-Host "Maximum billing units: $MaxBillingUnits"
if ($AutoApproveForVerification) {
    Write-Warning "Auto approval only continues the isolated verification workflow; it is not visual-quality or human-review approval."
}

try {
    $gate = Invoke-RestMethod -Method Get -Uri "$($ApiBaseUrl.TrimEnd('/'))/provider-profiles/toapis/pricing-review" -TimeoutSec 10
}
catch {
    Write-Host "BLOCKED_LIVE_VERIFICATION"
    throw "Backend live gate could not be verified. Start the local stack before confirmed live execution."
}
if ($gate.pricing_snapshot_hash -ne $PricingSnapshotHash) { throw "PRICING_SNAPSHOT_MISMATCH" }
if (-not $gate.live_orchestration_enabled) {
    Write-Host "LIVE_ORCHESTRATION_DISABLED"
    throw "TOAPIS live orchestration is disabled."
}
if (-not $gate.preflight.image_model_accessible -or -not $gate.preflight.video_model_accessible) { throw "MODEL_ACCESS_NOT_VERIFIED" }
if (-not $gate.account_balance_sufficient) { throw "ACCOUNT_BALANCE_NOT_CONFIRMED" }

throw "TOAPIS live gates passed, but paid two-shot execution is intentionally not run by the LIVE-ENABLE implementation command."
