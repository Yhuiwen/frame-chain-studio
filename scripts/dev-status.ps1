param(
  [int]$BackendPort = 8000,
  [int]$FrontendPort = 5173,
  [int]$FakeProviderPort = 8090,
  [string]$RunRoot = "",
  [string]$DatabasePath = ""
)

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$BackendRoot = Join-Path $ProjectRoot "backend"
if (-not $RunRoot) { $RunRoot = Join-Path $ProjectRoot ".run" }
$PidFile = Join-Path ([System.IO.Path]::GetFullPath($RunRoot)) "dev-processes.json"

function Http-Status($Url) {
  try {
    $response = Invoke-WebRequest $Url -UseBasicParsing -TimeoutSec 2
    return "$($response.StatusCode)"
  } catch {
    return "offline"
  }
}

function Get-ProcessTreeIds($RootPid) {
  $children = @(Get-CimInstance Win32_Process | Where-Object { $_.ParentProcessId -eq $RootPid })
  foreach ($child in $children) {
    Get-ProcessTreeIds $child.ProcessId
    $child.ProcessId
  }
}

if (Test-Path $PidFile) {
  $parsedItems = Get-Content $PidFile -Raw | ConvertFrom-Json
  $items = @($parsedItems | ForEach-Object { $_ })
} else {
  $items = @()
}

foreach ($item in $items) {
  $alive = [bool](Get-Process -Id $item.pid -ErrorAction SilentlyContinue)
  $childPids = @(Get-ProcessTreeIds $item.pid)
  [pscustomobject]@{
    Service = $item.name
    PID = $item.pid
    ChildPids = ($childPids -join ",")
    Alive = $alive
    Stdout = $item.stdout
    Stderr = $item.stderr
  }
}

Write-Host ""
Write-Host "HTTP:"
Write-Host "  backend ready:       $(Http-Status "http://127.0.0.1:$BackendPort/api/ready")"
Write-Host "  fake-provider ready: $(Http-Status "http://127.0.0.1:$FakeProviderPort/fake/v1/ready")"
Write-Host "  frontend:            $(Http-Status "http://127.0.0.1:$FrontendPort")"

try {
  $workers = Invoke-RestMethod "http://127.0.0.1:$BackendPort/api/workers/status" -TimeoutSec 2
  Write-Host "Workers:"
  Write-Host "  generation: $($workers.generation.online_count)/$($workers.generation.total_count)"
  Write-Host "  result:     $($workers.result.online_count)/$($workers.result.total_count)"
  Write-Host "  render:     $($workers.render.online_count)/$($workers.render.total_count)"
} catch {
  Write-Host "Workers: unavailable"
}

Push-Location $BackendRoot
try {
  if ($DatabasePath) {
    $env:FCS_DATABASE_URL = "sqlite:///" + ([System.IO.Path]::GetFullPath($DatabasePath) -replace "\\", "/")
  }
  Write-Host "Alembic:"
  python -m alembic current
} finally {
  Remove-Item Env:FCS_DATABASE_URL -ErrorAction SilentlyContinue
  Pop-Location
}
