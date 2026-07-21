param(
    [switch]$ConfirmLive,
    [switch]$ExecutePaid,
    [decimal]$MaxCost,
    [decimal]$MaxBillingUnits,
    [string]$BillingUnit,
    [string]$PricingSnapshotHash,
    [int]$RunId,
    [string]$InitialAnchorPath,
    [ValidateRange(2, 300)][int]$PollIntervalSeconds = 5,
    [ValidateRange(1, 120)][int]$TimeoutMinutes = 30,
    [string]$ApiBaseUrl = "http://127.0.0.1:8000/api",
    [switch]$AutoApproveForVerification,
    [switch]$CanaryImageOnly,
    [switch]$CanaryVideoFirstLast,
    [switch]$PlanOnly,
    [switch]$RecoveryPlanOnly,
    [int]$FailedRunId,
    [int]$RecoverFailedRunId,
    [string]$RecoveryPlanHash
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Net.Http
$repoRoot = Split-Path -Parent $PSScriptRoot
$backendRoot = Join-Path $repoRoot "backend"
$RecoverySourceRunId = $RecoverFailedRunId

Write-Host "Provider: TOAPIS"
Write-Host "Image model: doubao-seedream-5-0"
Write-Host "Video model: viduq3-pro"
if ($CanaryImageOnly -and $CanaryVideoFirstLast) { throw "CANARY_MODES_ARE_MUTUALLY_EXCLUSIVE" }
if ($PlanOnly -and $RecoveryPlanOnly) { throw "PLAN_MODES_ARE_MUTUALLY_EXCLUSIVE" }
if ($CanaryImageOnly) {
    Write-Host "Mode: paid image canary; Shots: 1; image tasks: max 1; video tasks: 0"
} elseif ($CanaryVideoFirstLast) {
    Write-Host "Mode: first-last-frame video canary; Shots: 1; image tasks: 0; video tasks: max 1"
} else {
    Write-Host "Mode: two-shot verification; Shots: 2; image tasks: max 2; video tasks: max 2"
}
if ($CanaryVideoFirstLast) {
    Write-Host "Video duration: 1s; resolution: 720p; audio: false"
} else {
    Write-Host "Video duration: 4s; resolution: 720p; audio: false; image resolution: 2K"
}

if ($RecoveryPlanOnly) {
    if (-not $ConfirmLive -or -not $ExecutePaid) { throw "RECOVERY_PLAN_CONFIRMATION_REQUIRED" }
    if ($FailedRunId -le 0) { throw "FAILED_RUN_ID_REQUIRED" }
    if ($BillingUnit -ne "TOAPIS_CREDIT" -or $MaxBillingUnits -ne [decimal]190) { throw "RECOVERY_LINEAGE_BUDGET_INVALID" }
    $planner = Join-Path $PSScriptRoot "toapis_recovery_plan.py"
    & python $planner --failed-run-id $FailedRunId --billing-unit $BillingUnit `
        --max-billing-units ([string]$MaxBillingUnits) --pricing-snapshot-hash $PricingSnapshotHash
    if ($LASTEXITCODE -ne 0) { throw "RECOVERY_PLAN_FAILED" }
    exit 0
}

if ($RecoverFailedRunId -gt 0) {
    if ([string]::IsNullOrWhiteSpace($RecoveryPlanHash)) { throw "RECOVERY_PLAN_HASH_REQUIRED" }
    if (-not $ConfirmLive -or -not $ExecutePaid) { throw "RECOVERY_EXECUTION_AUTHORIZATION_REQUIRED" }
    if ($BillingUnit -ne "TOAPIS_CREDIT" -or $MaxBillingUnits -ne [decimal]190) { throw "RECOVERY_LINEAGE_BUDGET_INVALID" }
}

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
    Write-Host "remoteTasksCreated=0"
    Write-Host "generationCost=0"
    exit 0
}

if ($PlanOnly) {
    if ($CanaryImageOnly -or $CanaryVideoFirstLast) { throw "PLAN_ONLY_IS_FOR_TWO_SHOT_ONLY" }
    $planner = Join-Path $PSScriptRoot "toapis_two_shot_plan.py"
    & python $planner --billing-unit $BillingUnit --max-billing-units ([string]$MaxBillingUnits) `
        --pricing-snapshot-hash $PricingSnapshotHash --initial-anchor-path $InitialAnchorPath
    if ($LASTEXITCODE -ne 0) { throw "TWO_SHOT_PLAN_FAILED" }
    exit 0
}

if (-not $ExecutePaid) {
    Write-Host "PAID_EXECUTION_NOT_AUTHORIZED"
    Write-Host "uploadCalled=false"
    Write-Host "submitCalled=false"
    Write-Host "pollCalled=false"
    Write-Host "remoteTasksCreated=0"
    Write-Host "generationCost=0"
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
if ($MaxBillingUnits -gt 500) { throw "MaxBillingUnits exceeds the system safety ceiling of 500 TOAPIS_CREDIT." }
if ($CanaryImageOnly -and ($MaxBillingUnits -lt [decimal]6.3 -or $MaxBillingUnits -gt [decimal]10)) {
    Write-Host "BLOCKED_BY_CANARY_BUDGET"
    Write-Host "uploadCalled=false"
    Write-Host "submitCalled=false"
    throw "Image canary MaxBillingUnits must be between 6.3 and 10 TOAPIS_CREDIT."
}
if ($CanaryVideoFirstLast -and ($MaxBillingUnits -lt [decimal]20 -or $MaxBillingUnits -gt [decimal]25)) {
    Write-Host "BLOCKED_BY_VIDEO_CANARY_BUDGET"
    throw "Video canary MaxBillingUnits must be between 20 and 25 TOAPIS_CREDIT."
}
if ([string]::IsNullOrWhiteSpace($PricingSnapshotHash)) { throw "PricingSnapshotHash is required." }

Write-Host "Billing unit: TOAPIS_CREDIT"
Write-Host "Maximum billing units: $MaxBillingUnits"
if ($AutoApproveForVerification) {
    Write-Warning "Auto approval only continues the isolated verification workflow; it is not visual-quality or human-review approval."
}

$api = $ApiBaseUrl.TrimEnd('/')
$primaryError = $null
try {
    try {
        $gate = Invoke-RestMethod -Method Get -Uri "$api/provider-profiles/toapis/pricing-review" -TimeoutSec 10
    }
    catch {
        Write-Host "BLOCKED_LIVE_VERIFICATION"
        throw "Backend live gate could not be verified. Start the local stack before confirmed live execution."
    }
    if ($gate.pricing_snapshot_hash -ne $PricingSnapshotHash) { throw "PRICING_SNAPSHOT_MISMATCH" }
    if ($CanaryImageOnly) {
        $imageRules = @($gate.image.pricing.rules | Where-Object { $_.unit -eq "IMAGE_REQUEST" })
        if ($imageRules.Count -ne 1) { throw "PRICING_SCHEMA_INVALID" }
        $estimate = [decimal]$imageRules[0].price
    } elseif ($CanaryVideoFirstLast) {
        $videoRules = @($gate.video.pricing.rules | Where-Object { $_.unit -eq "VIDEO_SECOND" })
        if ($videoRules.Count -ne 1) { throw "PRICING_SCHEMA_INVALID" }
        $estimate = [decimal]$videoRules[0].price
    } else {
        $estimate = [decimal]$gate.estimated_two_shot_billing_units
    }
    if ($estimate -le 0) { throw "PRICING_SCHEMA_INVALID" }
    if ($MaxBillingUnits -lt $estimate) {
        Write-Host "BLOCKED_BY_BUDGET"
        Write-Host "uploadCalled=false"
        Write-Host "submitCalled=false"
        throw "Maximum billing units are below the reviewed estimate."
    }
    Write-Host "Estimated billing units: $estimate"
    if (-not $gate.preflight.image_model_accessible -or -not $gate.preflight.video_model_accessible) { throw "MODEL_ACCESS_NOT_VERIFIED" }
    if (-not $gate.account_balance_sufficient) { throw "ACCOUNT_BALANCE_NOT_CONFIRMED" }
    if ($gate.account_balance_pricing_snapshot_hash -ne $PricingSnapshotHash) { throw "ACCOUNT_BALANCE_PRICING_MISMATCH" }
    if ($gate.account_balance_evidence_type -ne "TOKEN_BALANCE_READ_ONLY") { throw "ACCOUNT_BALANCE_EVIDENCE_INVALID" }
    if ([decimal]$gate.account_balance_confirmed_units -lt $MaxBillingUnits) { throw "ACCOUNT_BALANCE_COVERAGE_INSUFFICIENT" }

    if (-not $gate.live_orchestration_enabled) {
        $enableBody = @{
            acknowledged = $true
            pricing_snapshot_hash = $PricingSnapshotHash
            reason = if ($RecoverFailedRunId -gt 0) { "Explicitly authorized failed-run recovery with a matching plan hash." } elseif ($CanaryImageOnly) { "Explicitly authorized isolated paid image canary." } elseif ($CanaryVideoFirstLast) { "Explicitly authorized isolated paid video canary." } else { "Explicitly authorized paid two-shot verification." }
        } | ConvertTo-Json
        $enabled = Invoke-RestMethod -Method Post -Uri "$api/provider-profiles/toapis/live-enable" -ContentType "application/json" -Body $enableBody -TimeoutSec 10
        if (-not $enabled.live_orchestration_enabled) { throw "LIVE_ENABLE_FAILED" }
    }

    if ($RecoverFailedRunId -gt 0) {
        $recoveryBody = @{
            acknowledged = $true
            recovery_plan_hash = $RecoveryPlanHash
            billing_unit = $BillingUnit
            estimated_remaining_billing_units = "166.3"
            maximum_lineage_billing_units = "$MaxBillingUnits"
            authorization_reference = "EXPLICIT_USER_AUTHORIZATION"
        } | ConvertTo-Json
        $created = Invoke-RestMethod -Method Post -Uri "$api/provider-verification-runs/$RecoverFailedRunId/start-failed-run-recovery" -ContentType "application/json" -Body $recoveryBody -TimeoutSec 15
        $RunId = [int]$created.id
        $RecoverFailedRunId = 0
    } elseif (-not $PSBoundParameters.ContainsKey("RunId")) {
        $profiles = Invoke-RestMethod -Method Get -Uri "$api/provider-profiles" -TimeoutSec 10
        $profile = @($profiles | Where-Object { $_.provider_key -eq "toapis" })[0]
        if ($null -eq $profile) { throw "TOAPIS_PROVIDER_NOT_FOUND" }
        $createBody = @{
            confirm_live = $true
            execute_paid = $true
            billing_unit = $BillingUnit
            max_billing_units = "$MaxBillingUnits"
            pricing_snapshot_hash = $PricingSnapshotHash
            auto_approve_for_verification = [bool]$AutoApproveForVerification
            canary_image_only = [bool]$CanaryImageOnly
            canary_video_first_last = [bool]$CanaryVideoFirstLast
        } | ConvertTo-Json
        $created = Invoke-RestMethod -Method Post -Uri "$api/provider-profiles/$($profile.id)/verify-live" -ContentType "application/json" -Body $createBody -TimeoutSec 15
        if ($created.status -eq "BLOCKED") { throw "BLOCKED_LIVE_VERIFICATION" }
        $RunId = [int]$created.id
    }

    $deadline = (Get-Date).AddMinutes($TimeoutMinutes)
    $anchorUploaded = $false
    while ((Get-Date) -lt $deadline) {
        $state = Invoke-RestMethod -Method Get -Uri "$api/provider-verification-runs/$RunId" -TimeoutSec 10
        if ($state.status -in @("PASSED", "FAILED", "BLOCKED", "CANCELLED")) { break }
        if ($InitialAnchorPath -and -not $anchorUploaded -and $state.current_stage -eq "PROJECT_READY") {
            $resolvedAnchor = (Resolve-Path -LiteralPath $InitialAnchorPath).Path
            $client = [System.Net.Http.HttpClient]::new()
            $multipart = [System.Net.Http.MultipartFormDataContent]::new()
            $stream = [System.IO.File]::OpenRead($resolvedAnchor)
            try {
                $content = [System.Net.Http.StreamContent]::new($stream)
                $multipart.Add($content, "file", "verification-anchor")
                $response = $client.PostAsync("$api/provider-verification-runs/$RunId/initial-anchor", $multipart).GetAwaiter().GetResult()
                if (-not $response.IsSuccessStatusCode) { throw "INITIAL_ANCHOR_UPLOAD_FAILED" }
                $anchorUploaded = $true
            }
            finally {
                $stream.Dispose(); $multipart.Dispose(); $client.Dispose()
            }
        }
        $progress = Invoke-RestMethod -Method Post -Uri "$api/provider-verification-runs/$RunId/advance" -TimeoutSec 15
        if (-not $progress.can_advance) { Start-Sleep -Seconds $PollIntervalSeconds }
    }
    if ((Get-Date) -ge $deadline) { throw "VERIFICATION_TIMEOUT" }
    $state = Invoke-RestMethod -Method Get -Uri "$api/provider-verification-runs/$RunId" -TimeoutSec 10
    $progress = Invoke-RestMethod -Method Post -Uri "$api/provider-verification-runs/$RunId/advance" -TimeoutSec 15
    Write-Host "runId=$RunId"
    Write-Host "projectId=$($progress.project_id)"
    Write-Host "shot1Id=$(@($progress.shot_ids)[0])"
    if (-not $CanaryImageOnly -and -not $CanaryVideoFirstLast) { Write-Host "shot2Id=$(@($progress.shot_ids)[1])" }
    Write-Host "stage=$($progress.stage)"
    Write-Host "status=$($progress.status)"
    Write-Host "imageRequestsCreated=$($progress.image_requests_created)"
    Write-Host "videoRequestsCreated=$($progress.video_requests_created)"
    Write-Host "renderId=$($progress.render_id)"
    Write-Host "finalRenderAssetId=$($progress.final_render_asset_id)"
    Write-Host "estimatedBillingUnits=$($progress.estimated_billing_units)"
    Write-Host "actualBillingUnits=$($progress.actual_billing_units)"
    Write-Host "networkCalled=true"
    Write-Host "uploadCalled=$($progress.video_requests_created -gt 0)"
    Write-Host "submitCalled=$($progress.image_requests_created -gt 0 -or $progress.video_requests_created -gt 0)"
    Write-Host "pollCalled=$($progress.image_requests_created -gt 0 -or $progress.video_requests_created -gt 0)"
    if ($RecoverySourceRunId -gt 0) {
        $newImages = [Math]::Max(0, [int]$progress.image_requests_created - 1)
        $newVideos = [int]$progress.video_requests_created
        Write-Host "historicalImageSubmits=1"
        Write-Host "newImageSubmits=$newImages"
        Write-Host "newVideoSubmits=$newVideos"
        Write-Host "remoteTasksCreated=$($newImages + $newVideos)"
    } else {
        Write-Host "remoteTasksCreated=$($progress.image_requests_created + $progress.video_requests_created)"
    }
    Write-Host "generationCost=$($progress.actual_billing_units)"
    if ($state.status -ne "PASSED") { throw "VERIFICATION_$($state.status)" }
}
catch {
    $primaryError = $_
    throw
}
finally {
    try {
        $disabled = Invoke-RestMethod -Method Post -Uri "$api/provider-profiles/toapis/live-disable" -TimeoutSec 10
        Write-Host "liveOrchestrationEnabled=$($disabled.live_orchestration_enabled)"
    }
    catch {
        Write-Warning "LIVE_DISABLE_FAILED: manually disable TOAPIS live orchestration."
        if ($null -eq $primaryError) { throw }
    }
}
