param(
    [switch]$ConfirmLive,
    [decimal]$MaxCost,
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
if (-not $PSBoundParameters.ContainsKey("MaxCost") -or $MaxCost -le 0) { throw "-MaxCost must be explicitly provided and greater than zero." }

Write-Host "Maximum cost: $MaxCost"
if ($AutoApproveForVerification) {
    Write-Warning "Auto approval only continues the isolated verification workflow; it is not visual-quality or human-review approval."
}
throw "Confirmed live TOAPIS orchestration is not enabled until the account contract and pricing snapshot have been reviewed. No network request was made."
