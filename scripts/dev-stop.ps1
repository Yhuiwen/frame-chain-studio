param([int]$TimeoutSeconds = 5)

$ErrorActionPreference = "SilentlyContinue"
$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$PidFile = Join-Path $ProjectRoot ".run\dev-processes.json"

function Get-ProcessTreeIds($RootPid) {
  $children = @(Get-CimInstance Win32_Process | Where-Object { $_.ParentProcessId -eq $RootPid })
  foreach ($child in $children) {
    Get-ProcessTreeIds $child.ProcessId
    $child.ProcessId
  }
}

function Stop-ServiceTree($Item, [switch]$Force) {
  $ids = @($item.pid) + @(Get-ProcessTreeIds $item.pid)
  $ids = @($ids | Select-Object -Unique | Sort-Object -Descending)
  foreach ($id in $ids) {
    $process = Get-Process -Id $id -ErrorAction SilentlyContinue
    if (-not $process) { continue }
    if ($Force) {
      Write-Host "Force stopping $($item.name) pid=$id"
      Stop-Process -Id $id -Force
    } else {
      Write-Host "Stopping $($item.name) pid=$id"
      $process.CloseMainWindow() | Out-Null
    }
  }
}

if (-not (Test-Path $PidFile)) {
  Write-Host "No dev PID file found."
  exit 0
}

$parsedItems = Get-Content $PidFile -Raw | ConvertFrom-Json
$items = @($parsedItems | ForEach-Object { $_ })
foreach ($item in $items) {
  Stop-ServiceTree $item
}

$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
while ((Get-Date) -lt $deadline) {
  $alive = @(
    foreach ($item in $items) {
      @($item.pid) + @(Get-ProcessTreeIds $item.pid) | Where-Object { Get-Process -Id $_ -ErrorAction SilentlyContinue }
    }
  )
  if ($alive.Count -eq 0) { break }
  Start-Sleep -Milliseconds 250
}

foreach ($item in $items) {
  Stop-ServiceTree $item -Force
}

Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
Write-Host "Frame Chain Studio dev stack stopped."
