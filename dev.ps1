$ErrorActionPreference = "Stop"

Write-Host "Running migrations..."
Start-Process -NoNewWindow -Wait -WorkingDirectory "$PSScriptRoot\backend" `
    -FilePath "uv" -ArgumentList "run", "alembic", "upgrade", "head"

$backend = $null
$frontend = $null
$logDir = Join-Path $PSScriptRoot ".dev-logs"
$sessionStamp = Get-Date -Format "yyyyMMdd-HHmmss"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

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

    # ``taskkill /T`` stops the complete child tree without relying on CIM, which may
    # be blocked by local Windows policy. That includes Uvicorn's reload worker and
    # Vite's Node child, so a stopped launcher cannot leave either service behind.
    & taskkill.exe /PID $Process.Id /T /F 2>$null | Out-Null
}

function Show-LogTail {
    param(
        [string]$Service,
        [string]$OutputLog,
        [string]$ErrorLog
    )

    Write-Warning "$Service logs: $OutputLog ; $ErrorLog"
    foreach ($log in @($ErrorLog, $OutputLog)) {
        if (Test-Path $log) {
            $tail = Get-Content -Path $log -Tail 30
            if ($tail) {
                Write-Host "--- $Service $(Split-Path -Leaf $log) (last 30 lines) ---"
                $tail | Write-Host
            }
        }
    }
}

function Start-Frontend {
    param([int]$Attempt)

    $node = (Get-Command "node.exe" -ErrorAction Stop).Source
    $npmCli = Resolve-NpmCli
    $outputLog = Join-Path $logDir "$sessionStamp-frontend-$Attempt.out.log"
    $errorLog = Join-Path $logDir "$sessionStamp-frontend-$Attempt.err.log"
    $arguments = "`"$npmCli`" run dev"
    $process = Start-Process -PassThru -WorkingDirectory "$PSScriptRoot\frontend" `
        -FilePath $node -ArgumentList $arguments `
        -WindowStyle Hidden `
        -RedirectStandardOutput $outputLog -RedirectStandardError $errorLog
    return [pscustomobject]@{ Process = $process; OutputLog = $outputLog; ErrorLog = $errorLog }
}

try {
    Write-Host "To use the API docs (http://localhost:8000/docs), first sign in here:"
    Write-Host "  http://localhost:8000/auth/google/login"
    Write-Host ""

    Write-Host "Starting backend on http://localhost:8000 ..."
    # Watch application code only: saving tests should never interrupt a running
    # server reload on Windows.
    $backendOutputLog = Join-Path $logDir "$sessionStamp-backend.out.log"
    $backendErrorLog = Join-Path $logDir "$sessionStamp-backend.err.log"
    $backend = Start-Process -PassThru -WorkingDirectory "$PSScriptRoot\backend" `
        -FilePath "uv" -ArgumentList "run", "uvicorn", "app.main:app", "--host", "localhost", "--port", "8000", "--reload", "--reload-dir", "app" `
        -WindowStyle Hidden `
        -RedirectStandardOutput $backendOutputLog -RedirectStandardError $backendErrorLog

    Write-Host "Starting frontend on http://localhost:5173 ..."
    $frontendRun = Start-Frontend -Attempt 0
    $frontend = $frontendRun.Process

    Write-Host "Backend PID: $($backend.Id) | Frontend PID: $($frontend.Id)"
    Write-Host "Service logs: $logDir"
    Write-Host "Press Ctrl+C to stop both servers."

    $reportedBackendExit = $false
    $frontendRestarts = 0
    $maxFrontendRestarts = 2
    $frontendUnavailable = $false
    while (-not $backend.HasExited -or (-not $frontendUnavailable -and -not $frontend.HasExited)) {
        Start-Sleep -Milliseconds 500
        $backend.Refresh()
        $frontend.Refresh()

        if ($backend.HasExited -and -not $reportedBackendExit) {
            Write-Warning "Backend exited with code $($backend.ExitCode). Frontend will keep running until you stop this script."
            Show-LogTail -Service "Backend" -OutputLog $backendOutputLog -ErrorLog $backendErrorLog
            $reportedBackendExit = $true
        }
        if (-not $frontendUnavailable -and $frontend.HasExited) {
            Write-Warning "Frontend exited with code $($frontend.ExitCode)."
            Show-LogTail -Service "Frontend" -OutputLog $frontendRun.OutputLog -ErrorLog $frontendRun.ErrorLog
            if ($frontendRestarts -ge $maxFrontendRestarts) {
                Write-Warning "Frontend restart limit reached. Backend will keep running until you stop this script."
                $frontendUnavailable = $true
                continue
            }
            $frontendRestarts += 1
            Write-Host "Restarting frontend ($frontendRestarts/$maxFrontendRestarts)..."
            Start-Sleep -Seconds 2
            $frontendRun = Start-Frontend -Attempt $frontendRestarts
            $frontend = $frontendRun.Process
        }
    }
} finally {
    Stop-ProcessTree $frontend
    Stop-ProcessTree $backend
}
