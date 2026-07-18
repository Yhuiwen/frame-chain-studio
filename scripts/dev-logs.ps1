param(
  [string]$Service = "",
  [int]$Tail = 80
)

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$LogRoot = Join-Path $ProjectRoot ".run\logs"

if (-not (Test-Path $LogRoot)) {
  Write-Host "No dev logs found."
  exit 0
}

$pattern = if ($Service) { "$Service*.log" } else { "*.log" }
$files = Get-ChildItem $LogRoot -Filter $pattern -File | Sort-Object Name
if (-not $files) {
  Write-Host "No logs matched."
  exit 0
}

foreach ($file in $files) {
  Write-Host "===== $($file.Name) ====="
  Get-Content $file.FullName -Tail $Tail
}
