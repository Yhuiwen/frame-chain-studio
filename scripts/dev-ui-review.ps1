param(
  [int]$FrontendPort = 5174,
  [int]$BackendPort = 8100,
  [int]$FakeProviderPort = 8091,
  [string]$RunRoot = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ProductionDatabase = [System.IO.Path]::GetFullPath((Join-Path $ProjectRoot "backend\data\frame_chain.db"))
$ProductionStorage = [System.IO.Path]::GetFullPath((Join-Path $ProjectRoot "backend\data\storage"))

if (-not $RunRoot) {
  $RunRoot = Join-Path $ProjectRoot (".run\ui-review\" + [guid]::NewGuid().ToString())
}
$RunRoot = [System.IO.Path]::GetFullPath($RunRoot)
$ReviewBase = [System.IO.Path]::GetFullPath((Join-Path $ProjectRoot ".run\ui-review"))
if (-not $RunRoot.StartsWith($ReviewBase + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
  throw "UI_REVIEW_RUN_ROOT_OUTSIDE_ISOLATED_DIRECTORY"
}

$DatabasePath = [System.IO.Path]::GetFullPath((Join-Path $RunRoot "database\frame_chain.db"))
$StorageRoot = [System.IO.Path]::GetFullPath((Join-Path $RunRoot "storage"))
$LogRoot = [System.IO.Path]::GetFullPath((Join-Path $RunRoot "logs"))
$ProviderConfig = [System.IO.Path]::GetFullPath((Join-Path $RunRoot "provider-config\fake-provider.json"))

if ($DatabasePath -eq $ProductionDatabase) { throw "UI_REVIEW_DATABASE_POINTS_TO_PRODUCTION" }
if ($StorageRoot -eq $ProductionStorage) { throw "UI_REVIEW_STORAGE_POINTS_TO_PRODUCTION" }

New-Item -ItemType Directory -Force -Path $RunRoot, (Split-Path $DatabasePath), $StorageRoot, $LogRoot, (Split-Path $ProviderConfig), (Join-Path $RunRoot "screenshots") | Out-Null

& (Join-Path $PSScriptRoot "dev-start.ps1") `
  -FrontendPort $FrontendPort `
  -BackendPort $BackendPort `
  -FakeProviderPort $FakeProviderPort `
  -RunRoot $RunRoot `
  -DatabasePath $DatabasePath `
  -StorageRoot $StorageRoot `
  -LogRoot $LogRoot `
  -ProviderConfigFile $ProviderConfig

if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

[ordered]@{
  run_root = $RunRoot
  database = $DatabasePath
  storage = $StorageRoot
  logs = $LogRoot
  provider_config = $ProviderConfig
  frontend_port = $FrontendPort
  backend_port = $BackendPort
  fake_provider_port = $FakeProviderPort
  fake_provider_only = $true
} | ConvertTo-Json | Set-Content -Encoding UTF8 -LiteralPath (Join-Path $RunRoot "ui-review.json")

Write-Host "UI review run root: $RunRoot"
Write-Host "UI review database: $DatabasePath"
Write-Host "UI review storage: $StorageRoot"
