[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [ValidateNotNullOrEmpty()]
    [string]$Python = 'python',

    [Parameter(Mandatory = $false)]
    [ValidateNotNullOrEmpty()]
    [string]$LabRoot = (Split-Path -Parent $PSScriptRoot),

    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$Artifacts,

    [Parameter(Mandatory = $false)]
    [string]$Godot,

    [Parameter(Mandatory = $false)]
    [ValidateRange(10, 900)]
    [int]$Timeout = 120,

    [Parameter(Mandatory = $false)]
    [switch]$Headless
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ResolvedLabRoot = (Resolve-Path -LiteralPath $LabRoot).Path
$ArtifactPath = [System.IO.Path]::GetFullPath($Artifacts)
$Arguments = @(
    '-m',
    'godot_game_test_lab.visual_qa_self_test_runner',
    '--lab-root',
    $ResolvedLabRoot,
    '--artifacts',
    $ArtifactPath,
    '--timeout',
    [string]$Timeout
)

if (-not [string]::IsNullOrWhiteSpace($Godot)) {
    $ResolvedGodot = (Resolve-Path -LiteralPath $Godot).Path
    $Arguments += @('--godot', $ResolvedGodot)
}
if ($Headless.IsPresent) {
    $Arguments += '--headless'
}

Push-Location -LiteralPath $ResolvedLabRoot
try {
    & $Python @Arguments
    $ExitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}

if ($null -eq $ExitCode) {
    throw 'The Python visual QA self-test did not return an exit code.'
}
exit $ExitCode
