$ErrorActionPreference = "Stop"

Write-Host "Installing backend dependencies..."
Push-Location (Join-Path $PSScriptRoot "backend")
try {
    & uv sync
    if ($LASTEXITCODE -ne 0) { throw "Backend dependency installation failed with exit code $LASTEXITCODE." }
} finally {
    Pop-Location
}

Write-Host "Installing frontend dependencies..."
Push-Location (Join-Path $PSScriptRoot "frontend")
try {
    & npm install
    if ($LASTEXITCODE -ne 0) { throw "Frontend dependency installation failed with exit code $LASTEXITCODE." }
} finally {
    Pop-Location
}

Write-Host "Running database migrations..."
Push-Location (Join-Path $PSScriptRoot "backend")
try {
    & uv run alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw "Database migration failed with exit code $LASTEXITCODE." }
} finally {
    Pop-Location
}

Write-Host "Setup complete. Configure email delivery or Google sign-in before signing in."
