[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Target,
    [Parameter(Mandatory)][string]$Project,
    [Parameter(Mandatory)][string]$Package,
    [string]$Preset = 'Android',
    [string]$AndroidBridgeRepo,
    [string]$Godot,
    [string]$EvidenceDir,
    [string]$BridgeEvidenceDir,
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

$projectName = Split-Path -Leaf ([System.IO.Path]::GetFullPath($Project).TrimEnd('\','/'))
$runId = Get-Date -Format 'yyyyMMdd-HHmmss'
if (-not $EvidenceDir) {
    $EvidenceDir = Join-Path 'C:\GodotLabEvidence' "$projectName\android-$runId"
}
if (-not $BridgeEvidenceDir) {
    $BridgeEvidenceDir = "evidence/private/godot-lab/$projectName/android-$runId"
}

$params = @{
    Target = $Target
    Project = $Project
    Package = $Package
    Preset = $Preset
    LogLines = $LogLines
}
if (-not $SkipEvidence) { $params.EvidenceDir = $BridgeEvidenceDir }
if ($Godot) { $params.Godot = $Godot }
if ($AllowDowngrade) { $params.AllowDowngrade = $true }
if ($Release) { $params.Release = $true }
if ($SkipEvidence) { $params.SkipEvidence = $true }
if ($DryRun) { $params.DryRun = $true }
if ($Confirm) { $params.Confirm = $Confirm }

& $deployScript @params
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

if (-not $DryRun) {
    New-Item -ItemType Directory -Force -Path $EvidenceDir | Out-Null
    [ordered]@{
        schema = 'evavo_godot_lab_android_device_dispatch_v1'
        ok = $true
        targetRef = $Target
        package = $Package
        project = [System.IO.Path]::GetFullPath($Project)
        preset = $Preset
        exportMode = if ($Release) { 'release' } else { 'debug' }
        bridgeEvidenceRelativePath = if ($SkipEvidence) { $null } else { $BridgeEvidenceDir }
        bridgeRepository = [System.IO.Path]::GetFullPath($AndroidBridgeRepo)
        labEvidenceDirectory = [System.IO.Path]::GetFullPath($EvidenceDir)
        physicalDeviceExecutionClaimed = $true
        semanticGameplayClaimed = $false
        completedAt = (Get-Date).ToUniversalTime().ToString('o')
    } | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $EvidenceDir 'android-device-dispatch.json') -Encoding UTF8
}

exit 0
