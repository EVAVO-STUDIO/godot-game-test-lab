[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$TargetRepositoryPath,
    [Parameter(Mandatory = $true)][string]$ArtifactPath,
    [string]$ProfilePath = ".evavo\godot-lab-linux.json",
    [string]$ProjectSubpath = "",
    [string]$LabRoot = "",
    [string]$PythonExecutable = "",
    [string]$DockerExecutable = "docker",
    [string]$AllowedTargetRoot = "C:\GitRepos",
    [string]$AllowedArtifactRoot = "C:\GodotLabEvidence",
    [string]$ExpectedLabSha = "",
    [string]$ExpectedTargetSha = "",
    [int]$TimeoutSeconds = 2700,
    [double]$Cpus = 4.0,
    [string]$Memory = "10g",
    [string]$MemorySwap = "10g",
    [int]$PidsLimit = 1024,
    [int]$NoFileLimit = 4096,
    [string]$ShmSize = "1g",
    [switch]$RebuildImage,
    [switch]$RemoveImage
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $LabRoot) {
    $LabRoot = Split-Path -Parent $PSScriptRoot
}
$resolvedLab = (Resolve-Path -LiteralPath $LabRoot).Path
if (-not $PythonExecutable) {
    $PythonExecutable = Join-Path $resolvedLab ".venv\Scripts\python.exe"
}
if (-not (Test-Path -LiteralPath $PythonExecutable -PathType Leaf)) {
    throw "The Godot Lab Python environment is missing: $PythonExecutable"
}

$resolvedTargetRoot = (Resolve-Path -LiteralPath $AllowedTargetRoot).Path
New-Item -ItemType Directory -Force -Path $AllowedArtifactRoot | Out-Null
$resolvedArtifactRoot = (Resolve-Path -LiteralPath $AllowedArtifactRoot).Path
$artifactFull = [IO.Path]::GetFullPath($ArtifactPath)
$artifactPrefix = $resolvedArtifactRoot.TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
if (-not $artifactFull.StartsWith($artifactPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "ArtifactPath must remain beneath AllowedArtifactRoot."
}

$arguments = @(
    "-m", "godot_game_test_lab.local_sandbox", "run",
    (Resolve-Path -LiteralPath $TargetRepositoryPath).Path,
    "--lab-root", $resolvedLab,
    "--profile", $ProfilePath,
    "--artifacts", $artifactFull,
    "--allowed-root", $resolvedTargetRoot,
    "--allowed-artifact-root", $resolvedArtifactRoot,
    "--docker", $DockerExecutable,
    "--timeout", [string]$TimeoutSeconds,
    "--cpus", [string]$Cpus,
    "--memory", $Memory,
    "--memory-swap", $MemorySwap,
    "--pids-limit", [string]$PidsLimit,
    "--nofile-limit", [string]$NoFileLimit,
    "--shm-size", $ShmSize
)
if ($ProjectSubpath) { $arguments += @("--project-subpath", $ProjectSubpath) }
if ($ExpectedLabSha) { $arguments += @("--expected-lab-sha", $ExpectedLabSha) }
if ($ExpectedTargetSha) { $arguments += @("--expected-target-sha", $ExpectedTargetSha) }
if ($RebuildImage) { $arguments += "--rebuild-image" }
if ($RemoveImage) { $arguments += "--remove-image" }

& $PythonExecutable @arguments
exit $LASTEXITCODE
