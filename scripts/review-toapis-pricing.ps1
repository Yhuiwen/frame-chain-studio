param(
    [switch]$AcknowledgePricing,
    [decimal]$ImagePrice = 6.3,
    [string]$ImageUnit = "IMAGE_REQUEST",
    [decimal]$VideoPrice = 20,
    [string]$VideoUnit = "VIDEO_SECOND",
    [string]$BillingUnit = "TOAPIS_CREDIT",
    [string]$ImageModel = "doubao-seedream-5-0",
    [string]$VideoModel = "viduq3-pro",
    [string]$PricingVersion = "toapis-public-2026-07-21",
    [string]$ContractReference = "TOAPIS_OFFICIAL_PUBLIC_GUIDES_2026-07-21",
    [string]$ApiBaseUrl = "http://127.0.0.1:8000/api"
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$imageTotal = [decimal]2 * $ImagePrice
$videoTotal = [decimal]8 * $VideoPrice
$estimatedTotal = $imageTotal + $videoTotal

Write-Host "Image: 2 x $ImagePrice = $imageTotal TOAPIS_CREDIT"
Write-Host "Video: 8 x $VideoPrice = $videoTotal TOAPIS_CREDIT"
Write-Host "Estimated total: $estimatedTotal TOAPIS_CREDIT"
Write-Host "Recommended ceiling: 190 TOAPIS_CREDIT"
Write-Warning "Public pricing is reference pricing."
Write-Warning "Actual provider charging may vary by user group or promotion."
Write-Warning "First-last-frame pricing is reviewed as viduq3-pro standard generation because metadata.generation_type=reference2video is omitted."

if (-not $AcknowledgePricing) {
    Write-Host "PRICING_ACKNOWLEDGEMENT_REQUIRED"
    Write-Host "databaseUpdated=false"
    exit 0
}

$payload = @{
    acknowledged = $true
    pricing_version = $PricingVersion
    image_price = [string]$ImagePrice
    image_unit = $ImageUnit
    video_price = [string]$VideoPrice
    video_unit = $VideoUnit
    billing_unit = $BillingUnit
    image_model = $ImageModel
    video_model = $VideoModel
    pricing_source_kind = "OFFICIAL_PUBLIC_MODEL_GUIDE"
    contract_reference = $ContractReference
} | ConvertTo-Json

$uri = "$($ApiBaseUrl.TrimEnd('/'))/provider-profiles/toapis/pricing-review"
try {
    $result = Invoke-RestMethod -Method Post -Uri $uri -ContentType "application/json" -Body $payload -TimeoutSec 5
}
catch {
    if ($ApiBaseUrl -ne "http://127.0.0.1:8000/api") { throw }
    $helper = Join-Path $PSScriptRoot "review_toapis_pricing_api.py"
    $raw = & python $helper `
        --pricing-version $PricingVersion `
        --image-price ([string]$ImagePrice) `
        --image-unit $ImageUnit `
        --video-price ([string]$VideoPrice) `
        --video-unit $VideoUnit `
        --billing-unit $BillingUnit `
        --image-model $ImageModel `
        --video-model $VideoModel `
        --contract-reference $ContractReference
    if ($LASTEXITCODE -ne 0) { throw "TOAPIS pricing review API rejected the candidate contract." }
    $result = $raw | ConvertFrom-Json
}
if (-not $result.pricing_reviewed) { throw "TOAPIS pricing review was not persisted." }
if ($result.live_orchestration_enabled) { throw "Pricing review must not enable live orchestration." }

Write-Host "databaseUpdated=true"
Write-Host "pricingReviewed=$($result.pricing_reviewed.ToString().ToLowerInvariant())"
Write-Host "pricingVersion=$($result.pricing_version)"
Write-Host "pricingSnapshotHash=$($result.pricing_snapshot_hash)"
Write-Host "estimatedBillingUnits=$($result.estimated_two_shot_billing_units)"
Write-Host "recommendedCeiling=$($result.recommended_test_ceiling)"
Write-Host "liveOrchestrationEnabled=$($result.live_orchestration_enabled.ToString().ToLowerInvariant())"
