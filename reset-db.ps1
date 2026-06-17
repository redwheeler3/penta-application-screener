param(
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$backendDir = Join-Path $PSScriptRoot "backend"
$databasePath = Join-Path $backendDir "data\penta_screener.db"

Write-Host "This will delete the local SQLite database and recreate an empty schema."
Write-Host "Database: $databasePath"
Write-Host "This clears local users, Google credentials, settings, sync runs, and imported applications."

if (-not $Force) {
    $confirmation = Read-Host "Type RESET to continue"
    if ($confirmation -ne "RESET") {
        Write-Host "Database reset cancelled."
        exit 0
    }
}

if (Test-Path -LiteralPath $databasePath) {
    try {
        Remove-Item -LiteralPath $databasePath
        Write-Host "Deleted existing database."
    } catch {
        Write-Error "Could not delete the database. Stop the backend/dev script first, then run this again. $($_.Exception.Message)"
        exit 1
    }
} else {
    Write-Host "No existing database found."
}

Write-Host "Running migrations..."
Start-Process -NoNewWindow -Wait -WorkingDirectory $backendDir `
    -FilePath "uv" -ArgumentList "run", "alembic", "upgrade", "head"

Write-Host "Database reset complete."
