[CmdletBinding()]
param(
    [string]$LabRoot = "",
    [string]$TargetRoot = "C:\GitRepos",
    [string[]]$AdditionalTargetRoots = @(),
    [string]$EvidenceRoot = "C:\GodotLabEvidence",
    [string]$EngineRoot = "$env:LOCALAPPDATA\EVAVO\GodotGameTestLab\engines",
    [string]$EngineVersion = "4.6.3",
    [string]$TaskName = "EVAVO Godot Game Test Lab MCP",
    [ValidateRange(1, 65535)]
    [int]$Port = 8765,
    [string]$OfflineSourceDir = "",
    [switch]$EngineOffline,
    [switch]$PrepareEstate,
    [switch]$PrepareLinuxSandboxImages,
    [switch]$SkipExportTemplates,
    [switch]$ForceEngineInstall,
    [switch]$NoUserPath,
    [bool]$InstallPrerequisites = $true,
    [switch]$RequireFullMediaToolchain,
    [string]$AcceptanceRepositoryPath = "",
    [string]$ExpectedTargetSha = "",
    [string]$ProjectSubpath = ".",
    [string]$NativeProfilePath = "",
    [string]$BotProfilePath = "",
    [ValidateSet("validate", "native", "bot", "all")]
    [string]$AcceptanceMode = "validate",
    [switch]$SkipWorkerProbe
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw "Initialize-GodotLabAgentHost.ps1 must run on Windows."
}
if (-not $LabRoot) {
    $LabRoot = Split-Path -Parent $PSScriptRoot
}
$lab = (Resolve-Path -LiteralPath $LabRoot).Path
$installer = Join-Path $lab "scripts\Install-GodotLab.ps1"
$registerWorker = Join-Path $lab "scripts\Register-GodotLabMcpWorker.ps1"
$testWorker = Join-Path $lab "scripts\Test-GodotLabMcpWorker.ps1"
$acceptance = Join-Path $lab "scripts\Test-GodotLabAgentHost.ps1"
foreach ($script in @($installer, $registerWorker, $testWorker, $acceptance)) {
    if (-not (Test-Path -LiteralPath $script -PathType Leaf)) {
        throw "Required host bootstrap script is missing: $script"
    }
}

$allTargetRoots = [Collections.Generic.List[string]]::new()
$seenRoots = [Collections.Generic.HashSet[string]]::new(
    [StringComparer]::OrdinalIgnoreCase
)
foreach ($root in @($TargetRoot) + @($AdditionalTargetRoots)) {
    $resolved = (Resolve-Path -LiteralPath $root).Path
    if ($seenRoots.Add($resolved)) {
        $allTargetRoots.Add($resolved)
    }
}
if ($allTargetRoots.Count -eq 0) {
    throw "At least one target root is required."
}

$installParameters = @{
    LabRoot = $lab
    EngineVersion = $EngineVersion
    EngineRoot = $EngineRoot
    TargetRoot = $allTargetRoots[0]
    EvidenceRoot = $EvidenceRoot
    InstallPrerequisites = $InstallPrerequisites
}
if ($OfflineSourceDir) { $installParameters.OfflineSourceDir = $OfflineSourceDir }
if ($PrepareEstate) { $installParameters.PrepareEstate = $true }
if ($PrepareLinuxSandboxImages) {
    $installParameters.PrepareLinuxSandboxImages = $true
}
if ($SkipExportTemplates) { $installParameters.SkipExportTemplates = $true }
if ($ForceEngineInstall) { $installParameters.ForceEngineInstall = $true }
if ($NoUserPath) { $installParameters.NoUserPath = $true }
if ($RequireFullMediaToolchain) {
    $installParameters.RequireFullMediaToolchain = $true
}

Write-Host "[godot-lab] Installing and preparing the governed agent host."
& $installer @installParameters

$labSha = (& git -C $lab rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $labSha -notmatch '^[0-9a-f]{40}$') {
    throw "Unable to resolve the exact Lab SHA after installation."
}
$workerOffline = $EngineOffline -or [bool]$OfflineSourceDir
$registerParameters = @{
    LabRoot = $lab
    AllowedTargetRoots = @($allTargetRoots)
    EvidenceRoot = $EvidenceRoot
    EngineRoot = $EngineRoot
    TaskName = $TaskName
    Port = $Port
    StartNow = $true
}
if ($workerOffline) {
    $registerParameters.EngineOffline = $true
}

Write-Host "[godot-lab] Registering and starting the exact loopback MCP worker."
& $registerWorker @registerParameters

if (-not $SkipWorkerProbe) {
    $workerProbeParameters = @{
        LabRoot = $lab
        AllowedTargetRoots = @($allTargetRoots)
        EvidenceRoot = $EvidenceRoot
        EngineRoot = $EngineRoot
        TaskName = $TaskName
        Port = $Port
        ExpectedLabSha = $labSha
        RequireScheduledTask = $true
    }
    if ($workerOffline) {
        $workerProbeParameters.EngineOffline = $true
    }
    Write-Host "[godot-lab] Proving the live worker through the MCP protocol."
    & $testWorker @workerProbeParameters
}

$acceptanceParameters = @{
    LabRoot = $lab
    AllowedTargetRoots = @($allTargetRoots)
    EvidenceRoot = $EvidenceRoot
    EngineRoot = $EngineRoot
    TaskName = $TaskName
    Port = $Port
    ExpectedLabSha = $labSha
    SkipWorkerProbe = $true
    AcceptanceMode = $AcceptanceMode
    ProjectSubpath = $ProjectSubpath
}
if ($AcceptanceRepositoryPath) {
    $acceptanceParameters.AcceptanceRepositoryPath = $AcceptanceRepositoryPath
}
if ($ExpectedTargetSha) { $acceptanceParameters.ExpectedTargetSha = $ExpectedTargetSha }
if ($NativeProfilePath) { $acceptanceParameters.NativeProfilePath = $NativeProfilePath }
if ($BotProfilePath) { $acceptanceParameters.BotProfilePath = $BotProfilePath }

Write-Host "[godot-lab] Running host, hardware, engine, and optional game acceptance."
& $acceptance @acceptanceParameters
Write-Host "[godot-lab] Agent host initialization and acceptance completed."
