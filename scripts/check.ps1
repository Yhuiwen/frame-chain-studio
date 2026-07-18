$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")

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
}
