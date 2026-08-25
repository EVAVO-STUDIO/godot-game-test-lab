[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Target,
    [Parameter(Mandatory)][string]$Project,
    [Parameter(Mandatory)][string]$Package,
    [string]$Preset = 'Android',
    [string]$AndroidBridgeRepo,
    [string]$Godot,
    [string]$EvidenceDir,
    [int]$LogLines = 2000,
    [switch]$AllowDowngrade,
    [switch]$Release,
    [switch]$SkipEvidence,
    [switch]$DryRun,
    [string]$Confirm
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if (-not $AndroidBridgeRepo) {
    $repoParent = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
    $AndroidBridgeRepo = Join-Path $repoParent 'evavo-android-device-bridge'
}

$deployScript = Join-Path $AndroidBridgeRepo 'scripts\deploy-godot-android.ps1'
if (-not (Test-Path -LiteralPath $deployScript -PathType Leaf)) {
    throw "EVAVO Android Device Bridge deployment script not found: $deployScript"
}

if (-not $EvidenceDir) {
    $projectName = Split-Path -Leaf ([System.IO.Path]::GetFullPath($Project).TrimEnd('\','/'))
    $runId = Get-Date -Format 'yyyyMMdd-HHmmss'
    $EvidenceDir = Join-Path 'C:\GodotLabEvidence' "$projectName\android-$runId"
}

$params = @{
    Target = $Target
    Project = $Project
    Package = $Package
    Preset = $Preset
    EvidenceDir = $EvidenceDir
    LogLines = $LogLines
}
if ($Godot) { $params.Godot = $Godot }
if ($AllowDowngrade) { $params.AllowDowngrade = $true }
if ($Release) { $params.Release = $true }
if ($SkipEvidence) { $params.SkipEvidence = $true }
if ($DryRun) { $params.DryRun = $true }
if ($Confirm) { $params.Confirm = $Confirm }

& $deployScript @params
exit $LASTEXITCODE
