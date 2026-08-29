[CmdletBinding()]
param(
    [ValidateSet('all', 'capture', 'temporal')]
    [string]$Adapter = 'all',

    [string]$Python = 'python'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent $PSScriptRoot
$SourceRoot = Join-Path $RepoRoot 'src'
if (-not (Test-Path -LiteralPath $SourceRoot -PathType Container)) {
    throw "Godot Game Test Lab source directory was not found: $SourceRoot"
}

$PreviousPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = if ([string]::IsNullOrWhiteSpace($PreviousPythonPath)) {
        $SourceRoot
    }
    else {
        "$SourceRoot$([IO.Path]::PathSeparator)$PreviousPythonPath"
    }

    & $Python -m godot_game_test_lab.movie_source_identity_cli --adapter $Adapter
    $ExitCode = $LASTEXITCODE
    if ($ExitCode -ne 0) {
        throw "Godot movie source identity command failed with exit code $ExitCode."
    }
}
finally {
    $env:PYTHONPATH = $PreviousPythonPath
}
