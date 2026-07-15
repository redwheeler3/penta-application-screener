$ErrorActionPreference = "Stop"

Write-Host "Installing backend dependencies..."
Push-Location (Join-Path $PSScriptRoot "backend")
try {
    & uv sync
} finally {
    Pop-Location
}

Write-Host "Installing frontend dependencies..."
Push-Location (Join-Path $PSScriptRoot "frontend")
try {
    & npm install
} finally {
    Pop-Location
}

Write-Host "Running database migrations..."
Push-Location (Join-Path $PSScriptRoot "backend")
try {
    & uv run alembic upgrade head
} finally {
    Pop-Location
}

Write-Host "Setup complete. Configure Google OAuth before signing in."
