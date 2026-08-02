[CmdletBinding()]
param(
    [string]$LabRoot = "C:\GitRepos\godot-game-test-lab",
    [string]$PythonExecutable = "",
    [string[]]$AllowedTargetRoots = @("C:\GitRepos"),
    [string]$EvidenceRoot = "C:\GodotLabEvidence",
    [string]$EngineRoot = "$env:LOCALAPPDATA\EVAVO\GodotGameTestLab\engines",
    [string]$ServerName = "evavo-godot-game-test-lab",
    [string]$OutputPath = "",
    [switch]$AllowNonInteractive,
    [switch]$NoAutoProvision
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$resolvedLab = (Resolve-Path -LiteralPath $LabRoot).Path
if (-not $PythonExecutable) {
    $PythonExecutable = Join-Path $resolvedLab ".venv\Scripts\python.exe"
}
$resolvedPython = (Resolve-Path -LiteralPath $PythonExecutable).Path
if (-not (Test-Path -LiteralPath $resolvedPython -PathType Leaf)) {
    throw "PythonExecutable must identify the Lab virtual-environment Python executable."
}

$resolvedRoots = @()
foreach ($root in $AllowedTargetRoots) {
    $resolved = (Resolve-Path -LiteralPath $root).Path
    if (-not (Test-Path -LiteralPath $resolved -PathType Container)) {
        throw "Allowed target root is not a directory: $resolved"
    }
    $resolvedRoots += $resolved
}
if ($resolvedRoots.Count -eq 0) {
    throw "At least one AllowedTargetRoots value is required."
}
New-Item -ItemType Directory -Force -Path $EvidenceRoot, $EngineRoot | Out-Null
$resolvedEvidence = (Resolve-Path -LiteralPath $EvidenceRoot).Path
$resolvedEngine = (Resolve-Path -LiteralPath $EngineRoot).Path
if ($resolvedEngine.StartsWith($resolvedLab, [StringComparison]::OrdinalIgnoreCase)) {
    throw "EngineRoot must remain outside the Lab checkout."
}
foreach ($root in $resolvedRoots) {
    if ($resolvedEngine.StartsWith($root, [StringComparison]::OrdinalIgnoreCase)) {
        throw "EngineRoot must remain outside allowed target roots."
    }
}

$arguments = @(
    "-m",
    "godot_game_test_lab.mcp_server",
    "--transport",
    "stdio",
    "--lab-root",
    $resolvedLab,
    "--evidence-root",
    $resolvedEvidence,
    "--engine-root",
    $resolvedEngine
)
foreach ($root in $resolvedRoots) {
    $arguments += @("--allowed-root", $root)
}
if ($AllowNonInteractive) {
    $arguments += "--allow-noninteractive"
}
if ($NoAutoProvision) {
    $arguments += "--no-auto-provision"
}

$server = [ordered]@{
    command = $resolvedPython
    args = $arguments
}
$config = [ordered]@{
    mcpServers = [ordered]@{
        $ServerName = $server
    }
}
$json = $config | ConvertTo-Json -Depth 8

if ($OutputPath) {
    $destination = [System.IO.Path]::GetFullPath($OutputPath)
    $parent = Split-Path -Parent $destination
    if ($parent) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
    [System.IO.File]::WriteAllText(
        $destination,
        $json + [Environment]::NewLine,
        [System.Text.UTF8Encoding]::new($false)
    )
    Write-Host "[godot-lab] MCP configuration written to $destination"
}
else {
    $json
}
