# Restore the local SQLite DB from a backup in backend/data/backups/.
# The current DB is snapshotted first (tag "pre-restore"), so a restore is itself
# reversible. Stop the backend before restoring so nothing is mid-write.
#
# Usage:
#   ./restore-db.ps1                 # list backups, prompt for one
#   ./restore-db.ps1 -Latest         # restore the most recent backup
#   ./restore-db.ps1 <path|filename> # restore a specific backup
param([string]$Target = "", [switch]$Latest)
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendDir = Join-Path $repoRoot "backend"
$backupsDir = Join-Path $backendDir "data/backups"
Push-Location $backendDir
try {
    if ($Latest) {
        $Target = uv run python -c "from app.services.backup import list_backups; bs=list_backups(); print(bs[0] if bs else '')"
    }
    elseif (-not $Target) {
        Write-Host "Available backups (newest first):"
        uv run python -c "from app.services.backup import list_backups`nfor p in list_backups(): print(p.name)"
        $picked = Read-Host "Enter a backup filename to restore (or blank to cancel)"
        if (-not $picked) { Write-Host "Restore cancelled."; return }
        $Target = if (Test-Path $picked) { $picked } else { Join-Path $backupsDir $picked }
    }
    if (-not $Target -or -not (Test-Path $Target)) {
        Write-Error "No such backup: $Target"; return
    }

    Write-Host "This will REPLACE the live DB with:`n  $Target"
    Write-Host "The current DB is snapshotted first (tag pre-restore) and can be restored back."
    $confirmation = Read-Host "Type RESTORE to continue"
    if ($confirmation -ne "RESTORE") { Write-Host "Restore cancelled."; return }

    $py = "from pathlib import Path`nfrom app.services.backup import restore_backup`np=restore_backup(Path(r'$Target'))`nprint(f'Restored {p} from $Target')"
    uv run python -c $py
}
finally {
    Pop-Location
}
