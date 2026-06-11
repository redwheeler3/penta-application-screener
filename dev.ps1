$ErrorActionPreference = "Stop"

$backend = Start-Process -NoNewWindow -PassThru -WorkingDirectory "$PSScriptRoot\backend" `
    -FilePath "uv" -ArgumentList "run", "fastapi", "dev", "app/main.py"

$frontend = Start-Process -NoNewWindow -PassThru -WorkingDirectory "$PSScriptRoot\frontend" `
    -FilePath "npm" -ArgumentList "run", "dev"

Write-Host "Backend PID: $($backend.Id) | Frontend PID: $($frontend.Id)"
Write-Host "Press Ctrl+C to stop both servers."

try {
    Wait-Process -Id $backend.Id, $frontend.Id
} finally {
    Stop-Process -Id $backend.Id, $frontend.Id -ErrorAction SilentlyContinue
}
