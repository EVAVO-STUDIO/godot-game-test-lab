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

$estateModules = @(
    "GodotLabEstateAcceptance.Common.ps1",
    "GodotLabEstateAcceptance.Receipt.ps1",
    "GodotLabEstateAcceptance.Preflight.ps1",
    "GodotLabEstateAcceptance.Execute.ps1"
)
foreach ($moduleName in $estateModules) {
    $modulePath = Join-Path $PSScriptRoot $moduleName
    if (-not (Test-Path -LiteralPath $modulePath -PathType Leaf)) {
        throw "Required estate acceptance module is missing: $modulePath"
    }
    . $modulePath
}
