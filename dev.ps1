$ErrorActionPreference = "Stop"

Write-Host "Running migrations..."
Start-Process -NoNewWindow -Wait -WorkingDirectory "$PSScriptRoot\backend" `
    -FilePath "uv" -ArgumentList "run", "alembic", "upgrade", "head"

$backend = $null
$frontend = $null
function Stop-ProcessTree {
    param(
        [System.Diagnostics.Process]$Process
    )

    if ($null -eq $Process) {
        return
    }

    try {
        $allProcesses = Get-CimInstance Win32_Process
    } catch {
        Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
        return
    }
    $pending = @($Process.Id)
    $processIds = New-Object System.Collections.Generic.List[int]

    while ($pending.Count -gt 0) {
        $parentId = $pending[0]
        $pending = @($pending | Select-Object -Skip 1)

        if (-not $processIds.Contains($parentId)) {
            $processIds.Add($parentId)
        }

        $children = $allProcesses | Where-Object { $_.ParentProcessId -eq $parentId }
        foreach ($child in $children) {
            if (-not $processIds.Contains($child.ProcessId)) {
                $pending += $child.ProcessId
            }
        }
    }

    # Stop children before parents so reloader shells do not strand workers.
    foreach ($processId in ($processIds.ToArray() | Select-Object -Reverse)) {
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
    }
}

try {
    Write-Host "To use the API docs (http://localhost:8000/docs), first sign in here:"
    Write-Host "  http://localhost:8000/auth/google/login"
    Write-Host ""

    Write-Host "Starting backend on http://localhost:8000 ..."
    $backend = Start-Process -NoNewWindow -PassThru -WorkingDirectory "$PSScriptRoot\backend" `
        -FilePath "uv" -ArgumentList "run", "fastapi", "dev", "--host", "localhost", "app/main.py"

    Write-Host "Starting frontend on http://localhost:5173 ..."
    $frontend = Start-Process -NoNewWindow -PassThru -WorkingDirectory "$PSScriptRoot\frontend" `
        -FilePath "npm.cmd" -ArgumentList "run", "dev"

    Write-Host "Backend PID: $($backend.Id) | Frontend PID: $($frontend.Id)"
    Write-Host "Press Ctrl+C to stop both servers."

    $reportedBackendExit = $false
    $reportedFrontendExit = $false
    while (-not $backend.HasExited -or -not $frontend.HasExited) {
        Start-Sleep -Milliseconds 500
        $backend.Refresh()
        $frontend.Refresh()

        if ($backend.HasExited -and -not $reportedBackendExit) {
            Write-Warning "Backend exited with code $($backend.ExitCode). Frontend will keep running until you stop this script."
            $reportedBackendExit = $true
        }
        if ($frontend.HasExited -and -not $reportedFrontendExit) {
            Write-Warning "Frontend exited with code $($frontend.ExitCode). Backend will keep running until you stop this script."
            $reportedFrontendExit = $true
        }
    }
} finally {
    Stop-ProcessTree $frontend
    Stop-ProcessTree $backend
}
