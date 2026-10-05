param(
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$backendDir = Join-Path $PSScriptRoot "backend"
$databasePath = Join-Path $backendDir "data\penta_screener.db"

Write-Host "This will delete the local SQLite database and recreate an empty schema."
Write-Host "Database: $databasePath"
Write-Host "This clears local applications, sessions, users, settings, analyses, and recorded AI results."

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
$migration = Start-Process -PassThru -NoNewWindow -Wait -WorkingDirectory $backendDir `
    -FilePath "uv" -ArgumentList "run", "alembic", "upgrade", "head"

if ($migration.ExitCode -ne 0) { throw "Database migration failed with exit code $($migration.ExitCode)." }

Write-Host "Database reset complete."
