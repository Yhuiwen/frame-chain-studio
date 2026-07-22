$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$checkBase = Join-Path $root ".run\check"
$checkRoot = Join-Path $checkBase ([guid]::NewGuid().ToString("N"))
$previousEnvironment = @{}
$isolatedEnvironment = @{
    FCS_ENV = "test"
    FCS_DATABASE_URL = "sqlite:///" + ((Join-Path $checkRoot "check.db") -replace "\\", "/")
    FCS_STORAGE_DIR = Join-Path $checkRoot "storage"
    FCS_STORAGE_ROOT = Join-Path $checkRoot "storage"
    FCS_FIXTURE_DIR = Join-Path $root "backend\tests\fixtures"
    FCS_LOG_DIR = Join-Path $checkRoot "logs"
}

New-Item -ItemType Directory -Force -Path $checkRoot | Out-Null
$resolvedCheckBase = (Resolve-Path -LiteralPath $checkBase).Path
$resolvedCheckRoot = (Resolve-Path -LiteralPath $checkRoot).Path
if (-not $resolvedCheckRoot.StartsWith($resolvedCheckBase + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Unsafe check runtime path: $resolvedCheckRoot"
}
foreach ($name in $isolatedEnvironment.Keys) {
    $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
    [Environment]::SetEnvironmentVariable($name, $isolatedEnvironment[$name], "Process")
}

function Invoke-Step {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Name,
        [Parameter(Mandatory = $true)]
        [scriptblock] $Command
    )

    Write-Host ""
    Write-Host "==> $Name"
    & $Command
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

Push-Location $root
try {
    Invoke-Step "Backend pytest" {
        Push-Location backend
        try { python -m pytest } finally { Pop-Location }
    }

    Invoke-Step "Backend ruff" {
        Push-Location backend
        try { python -m ruff check . } finally { Pop-Location }
    }

    Invoke-Step "Backend mypy" {
        Push-Location backend
        try { python -m mypy app tests } finally { Pop-Location }
    }

    Invoke-Step "Frontend Vitest" {
        Push-Location frontend
        try { npm.cmd run test } finally { Pop-Location }
    }

    Invoke-Step "Frontend vue-tsc" {
        Push-Location frontend
        try { npm.cmd run typecheck } finally { Pop-Location }
    }

    Invoke-Step "Frontend Vite build" {
        Push-Location frontend
        try { npm.cmd run build } finally { Pop-Location }
    }
}
finally {
    Pop-Location
    foreach ($name in $isolatedEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($name, $previousEnvironment[$name], "Process")
    }
    Remove-Item -LiteralPath $checkRoot -Recurse -Force -ErrorAction SilentlyContinue
}
