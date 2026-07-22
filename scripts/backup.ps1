param(
  [string]$OutputDir = "",
  [string]$SourceDatabaseUrl = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$BackendRoot = Join-Path $ProjectRoot "backend"
if (-not $OutputDir) { $OutputDir = Join-Path $ProjectRoot "backups" }
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupPath = Join-Path $OutputDir "frame-chain-$timestamp.db"

Push-Location $BackendRoot
try {
  if ($SourceDatabaseUrl) { $env:FCS_DATABASE_URL = $SourceDatabaseUrl }
  $env:FCS_BACKUP_PATH = $backupPath
  @'
import hashlib
import os
import sqlite3
from pathlib import Path
from app.core.config import get_settings

settings = get_settings()
source = settings.database_url.removeprefix("sqlite:///")
target = Path(os.environ["FCS_BACKUP_PATH"])
target.parent.mkdir(parents=True, exist_ok=True)
with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
    src.backup(dst)
digest = hashlib.sha256(target.read_bytes()).hexdigest()
print(f"backup={target}")
print(f"sha256={digest}")
'@ | python -
} finally {
  Pop-Location
  Remove-Item Env:FCS_BACKUP_PATH -ErrorAction SilentlyContinue
}
