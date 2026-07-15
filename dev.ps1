$ErrorActionPreference = "Stop"

Write-Host "Running migrations..."
Start-Process -NoNewWindow -Wait -WorkingDirectory "$PSScriptRoot\backend" `
    -FilePath "uv" -ArgumentList "run", "alembic", "upgrade", "head"

$backend = $null
$frontend = $null
function Resolve-NpmCli {
    $npm = Get-Command "npm.cmd" -ErrorAction Stop
    $npmCli = Join-Path (Split-Path -Parent $npm.Source) "node_modules\npm\bin\npm-cli.js"
    if (-not (Test-Path $npmCli)) {
        throw "Could not find npm CLI script at $npmCli."
    }
    return $npmCli
}

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
    # Watch application code only: saving tests should never interrupt a running
    # server reload on Windows.
    $backend = Start-Process -NoNewWindow -PassThru -WorkingDirectory "$PSScriptRoot\backend" `
        -FilePath "uv" -ArgumentList "run", "uvicorn", "app.main:app", "--host", "localhost", "--port", "8000", "--reload", "--reload-dir", "app"

    Write-Host "Starting frontend on http://localhost:5173 ..."
    $node = (Get-Command "node.exe" -ErrorAction Stop).Source
    $npmCli = Resolve-NpmCli
    $frontendArgs = "`"$npmCli`" run dev"
    $frontend = Start-Process -NoNewWindow -PassThru -WorkingDirectory "$PSScriptRoot\frontend" `
        -FilePath $node -ArgumentList $frontendArgs

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
