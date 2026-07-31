[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$TargetRepositoryPath,

    [Parameter(Mandatory = $true)]
    [string]$ProfilePath,

    [Parameter(Mandatory = $true)]
    [string]$ExpectedLabSha,

    [Parameter(Mandatory = $true)]
    [string]$ExpectedTargetSha,

    [Parameter(Mandatory = $true)]
    [string]$ArtifactPath,

    [Parameter(Mandatory = $true)]
    [string]$AllowedArtifactRoot,

    [string]$ProjectSubpath = ".",
    [string]$PythonExecutable = "python",
    [string]$GodotExecutable = "",
    [string]$DotnetExecutable = "",
    [string]$MinimumGodotVersion = "4.6.2",

    [ValidateRange(30, 7200)]
    [int]$TimeoutSeconds = 900,

    [ValidateRange(0, 3600)]
    [int]$BootFrames = 30,

    [ValidatePattern('^-?[0-9]{1,5},-?[0-9]{1,5}$')]
    [string]$WindowPosition = "32,32",

    [switch]$AllowNonInteractive
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ($ExpectedLabSha -notmatch '^[0-9a-f]{40}$') {
    throw "ExpectedLabSha must be an exact lowercase 40-character commit SHA."
}
if ($ExpectedTargetSha -notmatch '^[0-9a-f]{40}$') {
    throw "ExpectedTargetSha must be an exact lowercase 40-character commit SHA."
}
if ($MinimumGodotVersion -notmatch '^4\.[0-9]+\.[0-9]+$') {
    throw "MinimumGodotVersion must be an explicit Godot 4.x.y version."
}

$labRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
New-Item -ItemType Directory -Force -Path $AllowedArtifactRoot | Out-Null
$arguments = @(
    "-m", "godot_game_test_lab.native_qa",
    "--lab-root", $labRoot,
    "--target-repository", $TargetRepositoryPath,
    "--project-subpath", $ProjectSubpath,
    "--profile", $ProfilePath,
    "--expected-lab-sha", $ExpectedLabSha,
    "--expected-target-sha", $ExpectedTargetSha,
    "--artifacts", $ArtifactPath,
    "--allowed-artifact-root", $AllowedArtifactRoot,
    "--minimum-godot-version", $MinimumGodotVersion,
    "--timeout", $TimeoutSeconds.ToString(),
    "--boot-frames", $BootFrames.ToString(),
    "--window-position", $WindowPosition
)
if ($GodotExecutable) {
    $arguments += @("--godot", $GodotExecutable)
}
if ($DotnetExecutable) {
    $arguments += @("--dotnet", $DotnetExecutable)
}
if ($AllowNonInteractive) {
    $arguments += "--allow-noninteractive"
}

Write-Host "[godot-lab] Running exact-SHA native Windows agent QA."
& $PythonExecutable @arguments
if ($LASTEXITCODE -ne 0) {
    throw "Native Windows agent QA failed with exit code $LASTEXITCODE."
}
Write-Host "[godot-lab] Native Windows agent QA passed."
