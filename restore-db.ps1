# Restore a named or latest backup. The shared CLI requests explicit confirmation.
# Stop the backend before restoring; the current DB is snapshotted first.
param([string]$Target = "", [switch]$Latest)
$ErrorActionPreference = "Stop"
Push-Location (Join-Path $PSScriptRoot "backend")
try {
    $restoreArgs = @("run", "python", "-m", "app.services.backup", "restore")
    if ($Latest) { $restoreArgs += "--latest" }
    if ($Target) { $restoreArgs += @("--", $Target) }
    & uv @restoreArgs
    if ($LASTEXITCODE -ne 0) { throw "Restore failed with exit code $LASTEXITCODE." }
} finally {
    Pop-Location
}
