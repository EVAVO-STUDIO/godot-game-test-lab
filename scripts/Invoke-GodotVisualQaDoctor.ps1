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
    [string]$Artifacts
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ResolvedLabRoot = (Resolve-Path -LiteralPath $LabRoot).Path
$ArtifactPath = [System.IO.Path]::GetFullPath($Artifacts)
$Arguments = @(
    '-m',
    'godot_game_test_lab.visual_qa_doctor',
    '--lab-root',
    $ResolvedLabRoot,
    '--artifacts',
    $ArtifactPath
)

Push-Location -LiteralPath $ResolvedLabRoot
try {
    & $Python @Arguments
    $ExitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}

if ($null -eq $ExitCode) {
    throw 'The Python visual QA doctor did not return an exit code.'
}
exit $ExitCode
