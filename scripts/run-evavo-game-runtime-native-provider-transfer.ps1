param(
    [Parameter(Mandatory = $true)]
    [string]$RuntimeRepo,

    [string]$GodotPath = $env:GODOT_BIN,

    [string]$ArtifactRoot = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$TestLabRoot = Split-Path -Parent $PSScriptRoot

if (-not $GodotPath -or -not (Test-Path -LiteralPath $GodotPath)) {
    throw "GodotPath/GODOT_BIN must point to Godot 4.6.2."
}
if (-not $ArtifactRoot) {
    $ArtifactRoot = Join-Path $TestLabRoot `
        "artifacts\evavo-game-runtime-native-provider-transfer"
}

$PythonCommand = Get-Command python -ErrorAction SilentlyContinue
$PythonArguments = @()
if (-not $PythonCommand) {
    $PythonCommand = Get-Command py -ErrorAction SilentlyContinue
    $PythonArguments = @("-3")
}
if (-not $PythonCommand) {
    throw "Python 3 is required."
}

& $PythonCommand.Source @PythonArguments `
    (Join-Path $PSScriptRoot "run-evavo-game-runtime-native-provider-transfer.py") `
    --runtime-repo $RuntimeRepo `
    --godot $GodotPath `
    --artifact-root $ArtifactRoot
if ($LASTEXITCODE -ne 0) {
    throw "EVAVO native provider transfer Test Lab suite failed."
}
