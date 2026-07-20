param(
    [switch]$EnableLive
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$backendRoot = Join-Path $repoRoot "backend"
$providerConfig = $env:FCS_PROVIDER_CONFIG_FILE

if (-not $EnableLive -and $env:FCS_ENABLE_REAL_PROVIDER_E2E -ne "1") {
    Write-Host "BLOCKED_LIVE_VERIFICATION"
    Write-Host "Set FCS_ENABLE_REAL_PROVIDER_E2E=1 or pass -EnableLive after configuring FCS_PROVIDER_CONFIG_FILE and provider credentials locally."
    exit 0
}

if (-not $providerConfig) {
    throw "FCS_PROVIDER_CONFIG_FILE is required for real provider verification."
}

$resolvedConfig = if ([System.IO.Path]::IsPathRooted($providerConfig)) {
    $providerConfig
} else {
    Join-Path $backendRoot $providerConfig
}

if (-not (Test-Path -LiteralPath $resolvedConfig)) {
    throw "Provider config was not found: $providerConfig"
}

Push-Location $backendRoot
try {
    python -m pytest tests/test_provider_http.py tests/test_provider_mapping.py tests/test_provider_registry.py
    Write-Host "CONTRACT_VERIFIED_ONLY"
    Write-Host "Live provider workflow execution is intentionally not automated without a provider-specific documented contract and non-production credentials."
}
finally {
    Pop-Location
}
