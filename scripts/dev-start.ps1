param(
  [int]$FrontendPort = 5173,
  [int]$BackendPort = 8000,
  [int]$FakeProviderPort = 8090,
  [string]$RunRoot = "",
  [string]$DatabasePath = "",
  [string]$StorageRoot = "",
  [string]$LogRoot = "",
  [string]$ProviderConfigFile = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$BackendRoot = Join-Path $ProjectRoot "backend"
$FrontendRoot = Join-Path $ProjectRoot "frontend"
$ProductionDatabase = [System.IO.Path]::GetFullPath((Join-Path $BackendRoot "data\frame_chain.db"))
$ProductionStorage = [System.IO.Path]::GetFullPath((Join-Path $BackendRoot "data\storage"))
if (-not $RunRoot) { $RunRoot = Join-Path $ProjectRoot ".run" }
$RunRoot = [System.IO.Path]::GetFullPath($RunRoot)
if (-not $LogRoot) { $LogRoot = Join-Path $RunRoot "logs" }
$PidFile = Join-Path $RunRoot "dev-processes.json"
if (-not $DatabasePath) { $DatabasePath = $ProductionDatabase }
if (-not $StorageRoot) { $StorageRoot = $ProductionStorage }
if (-not $ProviderConfigFile) { $ProviderConfigFile = Join-Path $BackendRoot "provider-config.dev.json" }
$DatabasePath = [System.IO.Path]::GetFullPath($DatabasePath)
$StorageDir = [System.IO.Path]::GetFullPath($StorageRoot)
$LogRoot = [System.IO.Path]::GetFullPath($LogRoot)
$ProviderConfig = [System.IO.Path]::GetFullPath($ProviderConfigFile)
$DatabaseUrl = "sqlite:///" + ($DatabasePath -replace "\\", "/")

function Fail($Message) {
  Write-Error $Message
  powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "dev-stop.ps1") -RunRoot $RunRoot | Out-Null
  exit 1
}

function Require-Command($Name) {
  if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
    Fail "$Name is required but was not found on PATH."
  }
}

function Test-PortFree($Port, $Name) {
  $busy = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
  if ($busy) { Fail "$Name port $Port is already in use." }
}

function Quote-Ps($Value) {
  return "'" + ($Value -replace "'", "''") + "'"
}

function Start-ServiceProcess($Name, $WorkingDirectory, $Command) {
  $stdout = Join-Path $LogRoot "$Name.out.log"
  $stderr = Join-Path $LogRoot "$Name.err.log"
  $process = Start-Process -FilePath "powershell" -WindowStyle Hidden -PassThru -WorkingDirectory $WorkingDirectory `
    -RedirectStandardOutput $stdout -RedirectStandardError $stderr `
    -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $Command)
  return [ordered]@{ name = $Name; pid = $process.Id; stdout = $stdout; stderr = $stderr }
}

function Wait-Http($Name, $Url) {
  for ($i = 0; $i -lt 60; $i++) {
    try {
      Invoke-WebRequest $Url -UseBasicParsing -TimeoutSec 2 | Out-Null
      return
    } catch {
      Start-Sleep -Milliseconds 500
    }
  }
  Fail "$Name did not become ready at $Url"
}

function Wait-ReadyJson($Name, $Url) {
  for ($i = 0; $i -lt 60; $i++) {
    try {
      $response = Invoke-RestMethod $Url -TimeoutSec 2
      if ($response.status -eq "ready") { return }
    } catch {
      Start-Sleep -Milliseconds 500
      continue
    }
    Start-Sleep -Milliseconds 500
  }
  $stderr = Join-Path $LogRoot "backend.err.log"
  if (Test-Path $stderr) {
    Write-Host "Backend stderr tail:"
    Get-Content $stderr -Tail 80
  }
  Fail "$Name did not report status=ready at $Url"
}

function Wait-WorkersReady($Url) {
  for ($i = 0; $i -lt 60; $i++) {
    try {
      $workers = Invoke-RestMethod $Url -TimeoutSec 2
      if (
        $workers.generation.online_count -ge 1 -and
        $workers.result.online_count -ge 1 -and
        $workers.render.online_count -ge 1
      ) { return }
    } catch {
      Start-Sleep -Milliseconds 500
      continue
    }
    Start-Sleep -Milliseconds 500
  }
  Fail "Workers did not all become online at $Url"
}

if (Test-Path $PidFile) {
  $existing = Get-Content $PidFile -Raw | ConvertFrom-Json
  $alive = @($existing | Where-Object { Get-Process -Id $_.pid -ErrorAction SilentlyContinue })
  if ($alive.Count -gt 0) {
    Write-Host "Frame Chain Studio dev stack is already running. Use scripts/dev-status.ps1."
    exit 0
  }
}

New-Item -ItemType Directory -Force -Path $RunRoot, $LogRoot, $StorageDir, (Split-Path $DatabasePath), (Split-Path $ProviderConfig) | Out-Null
Require-Command python
Require-Command node
Require-Command npm.cmd
Require-Command ffmpeg
Require-Command ffprobe
Test-PortFree $FrontendPort "frontend"
Test-PortFree $BackendPort "backend"
Test-PortFree $FakeProviderPort "fake-provider"

if (-not (Test-Path (Join-Path $BackendRoot "app"))) { Fail "Backend source directory is missing." }
if (-not (Test-Path (Join-Path $FrontendRoot "node_modules"))) { Fail "Frontend dependencies are not installed. Run npm install in frontend." }

$providerJson = Get-Content (Join-Path $BackendRoot "provider-config.example.json") -Raw
$providerJson = $providerJson -replace "http://127\.0\.0\.1:8090", "http://127.0.0.1:$FakeProviderPort"
Set-Content -Path $ProviderConfig -Value $providerJson -Encoding UTF8

Push-Location $BackendRoot
try {
  $env:FCS_DATABASE_URL = $DatabaseUrl
  $env:TOAPIS_API_KEY = ""
  python -m alembic upgrade head
} finally {
  Pop-Location
}

$commonEnv = @(
  "`$env:FCS_DATABASE_URL=$(Quote-Ps $DatabaseUrl)",
  "`$env:FCS_STORAGE_DIR=$(Quote-Ps $StorageDir)",
  "`$env:FCS_LOG_DIR=$(Quote-Ps $LogRoot)",
  "`$env:FCS_FIXTURE_DIR=$(Quote-Ps (Join-Path $BackendRoot "tests\fixtures"))",
  "`$env:FCS_PROVIDER_CONFIG_FILE=$(Quote-Ps $ProviderConfig)",
  "`$env:FCS_ENV='development'",
  "`$env:FCS_RESULT_ALLOWED_PRIVATE_HOSTS='127.0.0.1'",
  "`$env:FCS_DEFAULT_IMAGE_PROVIDER_ID='fake-http'",
  "`$env:FCS_DEFAULT_VIDEO_PROVIDER_ID='fake-http'",
  "`$env:FCS_BACKEND_PORT='$BackendPort'",
  "`$env:FCS_FRONTEND_PORT='$FrontendPort'",
  "`$env:FCS_FAKE_PROVIDER_PORT='$FakeProviderPort'",
  "`$env:TOAPIS_API_KEY=''"
) -join "; "

$processes = @()
try {
  $processes += Start-ServiceProcess "fake-provider" $BackendRoot "$commonEnv; python -m uvicorn fake_provider.app:app --host 127.0.0.1 --port $FakeProviderPort"
  Wait-Http "fake-provider" "http://127.0.0.1:$FakeProviderPort/fake/v1/ready"
  $processes += Start-ServiceProcess "backend" $BackendRoot "$commonEnv; python -m uvicorn app.main:app --host 127.0.0.1 --port $BackendPort"
  Wait-ReadyJson "backend" "http://127.0.0.1:$BackendPort/api/ready"
  $processes += Start-ServiceProcess "generation-worker" $BackendRoot "$commonEnv; `$env:FCS_WORKER_ID='dev-generation-worker'; python -m app.workers.cli"
  $processes += Start-ServiceProcess "result-worker" $BackendRoot "$commonEnv; `$env:FCS_RESULT_WORKER_ID='dev-result-worker'; python -m app.workers.result_cli"
  $processes += Start-ServiceProcess "render-worker" $BackendRoot "$commonEnv; `$env:FCS_WORKER_ID='dev-render-worker'; python -m app.workers.render_cli"
  Wait-WorkersReady "http://127.0.0.1:$BackendPort/api/workers/status"
  $processes += Start-ServiceProcess "frontend" $FrontendRoot "`$env:VITE_API_BASE_URL=''; `$env:VITE_API_PROXY_TARGET='http://127.0.0.1:$BackendPort'; npm.cmd run dev -- --host 127.0.0.1 --port $FrontendPort"
  Wait-Http "frontend" "http://127.0.0.1:$FrontendPort"
  $processes | ConvertTo-Json -Depth 4 | Set-Content -Path $PidFile -Encoding UTF8
  Write-Host "Frame Chain Studio dev stack started."
  Write-Host "Frontend: http://127.0.0.1:$FrontendPort"
  Write-Host "Backend:  http://127.0.0.1:$BackendPort/api/ready"
} catch {
  $processes | ConvertTo-Json -Depth 4 | Set-Content -Path $PidFile -Encoding UTF8
  Fail $_.Exception.Message
}
