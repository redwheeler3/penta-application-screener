# Take a consistent snapshot of the local SQLite DB into backend/data/backups/.
# Safe to run while the backend is up (uses SQLite VACUUM INTO, not a raw copy).
# Usage: ./backup-db.ps1 [-Tag <label>]   (Tag defaults to "manual")
param([string]$Tag = "manual")
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location (Join-Path $repoRoot "backend")
try {
    $py = @"
from app.services.backup import create_and_prune, list_backups, backups_dir
p = create_and_prune(tag='$Tag')
print(f'Backup written: {p} ({p.stat().st_size/1_000_000:.1f} MB)')
print(f'{len(list_backups())} backup(s) retained in {backups_dir()}')
"@
    uv run python -c $py
}
finally {
    Pop-Location
}
