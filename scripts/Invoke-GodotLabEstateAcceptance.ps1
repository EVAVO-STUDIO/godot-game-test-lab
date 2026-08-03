[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ManifestPath,
    [string]$LabRoot = "",
    [string[]]$AllowedTargetRoots = @("C:\GitRepos"),
    [string]$EvidenceRoot = "C:\GodotLabEvidence",
    [string]$EngineRoot = "$env:LOCALAPPDATA\EVAVO\GodotGameTestLab\engines",
    [string]$TaskName = "EVAVO Godot Game Test Lab MCP",
    [ValidateRange(1, 65535)]
    [int]$Port = 8765,
    [ValidateRange(1, 120)]
    [int]$WorkerStartupTimeoutSeconds = 30,
    [ValidateRange(1, 600)]
    [int]$EstateLockTimeoutSeconds = 30,
    [string]$ExpectedLabSha = "",
    [switch]$EngineOffline,
    [switch]$RegisterWorker,
    [switch]$StartWorker
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$moduleNames = @(
    "GodotLabEstateAcceptance.Common.ps1",
    "GodotLabEstateAcceptance.Receipt.ps1",
    "GodotLabEstateAcceptance.Preflight.ps1",
    "GodotLabEstateAcceptance.Execute.ps1"
)
$modulePaths = [ordered]@{}
foreach ($moduleName in $moduleNames) {
    $modulePath = Join-Path $PSScriptRoot $moduleName
    if (-not (Test-Path -LiteralPath $modulePath -PathType Leaf)) {
        throw "Required estate acceptance module is missing: $modulePath"
    }
    $modulePaths[$moduleName] = $modulePath
}

. $modulePaths["GodotLabEstateAcceptance.Common.ps1"]
. $modulePaths["GodotLabEstateAcceptance.Receipt.ps1"]

$mutexAcquired = $false
$mutexAbandoned = $false
$estateMutex = [Threading.Mutex]::new(
    $false,
    "Global\EVAVO.GodotLab.EstateAcceptance"
)
try {
    try {
        $mutexAcquired = $estateMutex.WaitOne(
            [TimeSpan]::FromSeconds($EstateLockTimeoutSeconds)
        )
    }
    catch [Threading.AbandonedMutexException] {
        $mutexAcquired = $true
        $mutexAbandoned = $true
    }
    if (-not $mutexAcquired) {
        throw "Another Godot estate acceptance owns the machine-wide lease."
    }

    . $modulePaths["GodotLabEstateAcceptance.Preflight.ps1"]
    $receipt.abandonedMutexRecovered = $mutexAbandoned
    . $modulePaths["GodotLabEstateAcceptance.Execute.ps1"]
}
finally {
    if ($mutexAcquired) {
        try {
            $estateMutex.ReleaseMutex()
        }
        catch [ApplicationException] {
        }
    }
    $estateMutex.Dispose()
}
