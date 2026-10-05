# Take a consistent local SQLite snapshot; labels are passed as CLI data.
param([string]$Tag = "manual")
$ErrorActionPreference = "Stop"
Push-Location (Join-Path $PSScriptRoot "backend")
try {
    & uv run python -m app.services.backup backup "--tag=$Tag"
    if ($LASTEXITCODE -ne 0) { throw "Backup failed with exit code $LASTEXITCODE." }
} finally {
    Pop-Location
}
