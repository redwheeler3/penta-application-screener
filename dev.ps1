$ErrorActionPreference = "Stop"

Write-Host "Running migrations..."
Start-Process -NoNewWindow -Wait -WorkingDirectory "$PSScriptRoot\backend" `
    -FilePath "uv" -ArgumentList "run", "alembic", "upgrade", "head"

$backend = $null
$frontend = $null

try {
    $backend = Start-Process -NoNewWindow -PassThru -WorkingDirectory "$PSScriptRoot\backend" `
        -FilePath "uv" -ArgumentList "run", "fastapi", "dev", "app/main.py"

    $frontend = Start-Process -NoNewWindow -PassThru -WorkingDirectory "$PSScriptRoot\frontend" `
        -FilePath "npm.cmd" -ArgumentList "run", "dev"

    Write-Host "Backend PID: $($backend.Id) | Frontend PID: $($frontend.Id)"
    Write-Host "Press Ctrl+C to stop both servers."

    Wait-Process -Id $backend.Id, $frontend.Id
} finally {
    if ($null -ne $backend) {
        Stop-Process -Id $backend.Id -ErrorAction SilentlyContinue
    }

    if ($null -ne $frontend) {
        Stop-Process -Id $frontend.Id -ErrorAction SilentlyContinue
    }
}
