[CmdletBinding()]
param(
    [Parameter()]
    [string]$RuntimeRoot = "C:\GitRepos\godot-web-runtime",

    [Parameter()]
    [string]$PythonExecutable = "python"
)

$ErrorActionPreference = "Stop"
$ScriptPath = Join-Path $PSScriptRoot "check_web_export_descriptor_fixture.py"

if (-not (Test-Path -LiteralPath $ScriptPath -PathType Leaf)) {
    throw "Descriptor fixture checker is missing: $ScriptPath"
}

$RuntimeRootPath = [System.IO.Path]::GetFullPath($RuntimeRoot)
if (-not (Test-Path -LiteralPath $RuntimeRootPath -PathType Container)) {
    throw "Godot Web Runtime root is unavailable: $RuntimeRootPath"
}

& $PythonExecutable $ScriptPath --runtime-root $RuntimeRootPath --json
if ($LASTEXITCODE -ne 0) {
    throw "Godot web descriptor contract check failed with exit code $LASTEXITCODE."
}
