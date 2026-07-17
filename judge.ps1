param(
    [string]$Model,
    [string]$Case,
    [int]$Stability
)

$ErrorActionPreference = "Stop"
$arguments = @("run", "python", "-m", "app.evals.judge")
if ($Model) {
    $arguments += "--model", $Model
}
if ($Case) {
    $arguments += "--case", $Case
}
if ($Stability) {
    $arguments += "--stability", $Stability
}

Push-Location (Join-Path $PSScriptRoot "backend")
try {
    & uv @arguments
} finally {
    Pop-Location
}
