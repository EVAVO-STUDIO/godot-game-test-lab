param(
    [Parameter(Mandatory = $true)]
    [string]$RuntimeRepo,
    [string]$GodotPath = $env:GODOT_BIN,
    [string]$ArtifactRoot = "",
    [double]$TimeoutSeconds = 180
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$TestLabRoot = Split-Path -Parent $PSScriptRoot
$RuntimeRepo = [System.IO.Path]::GetFullPath($RuntimeRepo)
if (-not (Test-Path -LiteralPath $RuntimeRepo -PathType Container)) {
    throw "RuntimeRepo does not exist: $RuntimeRepo"
}
if ([string]::IsNullOrWhiteSpace($GodotPath)) {
    throw "GodotPath or GODOT_BIN must point to Godot 4.6.2."
}
$GodotPath = [System.IO.Path]::GetFullPath($GodotPath)
if (-not (Test-Path -LiteralPath $GodotPath -PathType Leaf)) {
    throw "Godot executable was not found: $GodotPath"
}
if ([string]::IsNullOrWhiteSpace($ArtifactRoot)) {
    $ArtifactRoot = Join-Path $TestLabRoot "artifacts\evavo-game-runtime-http-range-hardening"
}
$ArtifactRoot = [System.IO.Path]::GetFullPath($ArtifactRoot)
$Python = Get-Command python -ErrorAction SilentlyContinue
$PythonArgs = @()
if (-not $Python) {
    $Python = Get-Command py -ErrorAction SilentlyContinue
    $PythonArgs = @("-3")
}
if (-not $Python) {
    throw "Python 3 is required."
}
$Runner = Join-Path $PSScriptRoot "run-evavo-game-runtime-http-range-hardening.py"
& $Python.Source @PythonArgs $Runner `
    --runtime-repo $RuntimeRepo `
    --godot $GodotPath `
    --artifact-root $ArtifactRoot `
    --timeout-seconds $TimeoutSeconds
if ($LASTEXITCODE -ne 0) {
    throw "EVAVO Game Runtime HTTP range hardening Test Lab suite failed."
}
Write-Host "EVAVO Game Runtime HTTP range hardening Test Lab suite passed."
