param(
    [string]$Model,
    [string]$Case
)

$ErrorActionPreference = "Stop"
$arguments = @("run", "python", "-m", "app.evals.judge")
if ($Model) {
    $arguments += "--model", $Model
}
if ($Case) {
    $arguments += "--case", $Case
}

Push-Location (Join-Path $PSScriptRoot "backend")
try {
    & uv @arguments
} finally {
    Pop-Location
}
