[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Project,

    [Parameter(Mandatory = $true)]
    [string]$Request,

    [Parameter(Mandatory = $true)]
    [string]$Artifacts,

    [string]$Python = "python",
    [string]$Godot,
    [string]$DotNet,
    [string]$MinimumGodotVersion = "4.6.2",
    [ValidateRange(1, 3600)]
    [int]$TimeoutSeconds = 300,
    [ValidateRange(0, 600)]
    [int]$BootFrames = 5,
    [switch]$WarningsAsErrors,
    [switch]$NoRecoveryDiagnostic,
    [switch]$AllowMajorUpgrade,
    [string]$EngineRoot,
    [string]$EngineSourceDir,
    [switch]$OfflineEngine,
    [switch]$NoAutoProvisionEngine,
    [string]$Output
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$arguments = @(
    "-m",
    "godot_game_test_lab.localization_plural_runtime_cli",
    $Project,
    "--request", $Request,
    "--artifacts", $Artifacts,
    "--minimum-godot-version", $MinimumGodotVersion,
    "--timeout", [string]$TimeoutSeconds,
    "--boot-frames", [string]$BootFrames
)

if ($Godot) { $arguments += @("--godot", $Godot) }
if ($DotNet) { $arguments += @("--dotnet", $DotNet) }
if ($WarningsAsErrors) { $arguments += "--warnings-as-errors" }
if ($NoRecoveryDiagnostic) { $arguments += "--no-recovery-diagnostic" }
if ($AllowMajorUpgrade) { $arguments += "--allow-major-upgrade" }
if ($EngineRoot) { $arguments += @("--engine-root", $EngineRoot) }
if ($EngineSourceDir) { $arguments += @("--engine-source-dir", $EngineSourceDir) }
if ($OfflineEngine) { $arguments += "--offline-engine" }
if ($NoAutoProvisionEngine) { $arguments += "--no-auto-provision-engine" }
if ($Output) { $arguments += @("--output", $Output) }

& $Python @arguments
$exitCode = $LASTEXITCODE
if ($exitCode -ne 0) {
    throw "Godot plural localization validation failed with exit code $exitCode."
}
