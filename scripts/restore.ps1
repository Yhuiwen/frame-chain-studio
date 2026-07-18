param(
  [Parameter(Mandatory = $true)][string]$BackupPath,
  [switch]$Force
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$BackendRoot = Join-Path $ProjectRoot "backend"
$PidFile = Join-Path $ProjectRoot ".run\dev-processes.json"

if ((Test-Path $PidFile) -and -not $Force) {
  throw "Dev services appear to be running. Stop them first or pass -Force."
}
if (-not (Test-Path $BackupPath)) {
  throw "Backup file was not found: $BackupPath"
}
if (-not $Force) {
  $answer = Read-Host "Restore will replace the current SQLite database. Type RESTORE to continue"
  if ($answer -ne "RESTORE") { throw "Restore cancelled." }
}

Push-Location $BackendRoot
try {
  $env:FCS_RESTORE_SOURCE = (Resolve-Path $BackupPath)
  @'
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
import os
from app.core.config import get_settings

settings = get_settings()
target = Path(settings.database_url.removeprefix("sqlite:///"))
source = Path(os.environ["FCS_RESTORE_SOURCE"])
with sqlite3.connect(source) as connection:
    connection.execute("PRAGMA quick_check").fetchone()
if target.exists():
    safety = target.with_suffix(f".pre-restore-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.db")
    shutil.copy2(target, safety)
    print(f"pre_restore_backup={safety}")
target.parent.mkdir(parents=True, exist_ok=True)
shutil.copy2(source, target)
print(f"restored={target}")
'@ | python -
  python -m alembic upgrade head
} finally {
  Pop-Location
  Remove-Item Env:FCS_RESTORE_SOURCE -ErrorAction SilentlyContinue
}
