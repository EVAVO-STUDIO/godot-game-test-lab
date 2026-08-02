[CmdletBinding()]
param(
    [string]$LabRoot = "C:\GitRepos\godot-game-test-lab",
    [string[]]$AllowedTargetRoots = @("C:\GitRepos"),
    [string]$EvidenceRoot = "C:\GodotLabEvidence",
    [string]$EngineRoot = "$env:LOCALAPPDATA\EVAVO\GodotGameTestLab\engines",
    [string]$HostAddress = "127.0.0.1",
    [int]$Port = 8765,
    [switch]$AllowNonInteractive
)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$resolvedLab = (Resolve-Path -LiteralPath $LabRoot).Path
$python = Join-Path $resolvedLab ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Run scripts\Install-GodotLab.ps1 before starting the MCP worker."
}
$arguments = @(
    "-m", "godot_game_test_lab.mcp_server",
    "--transport", "streamable-http",
    "--host", $HostAddress,
    "--port", $Port,
    "--lab-root", $resolvedLab,
    "--evidence-root", $EvidenceRoot,
    "--engine-root", $EngineRoot
)
foreach ($root in $AllowedTargetRoots) {
    $arguments += @("--allowed-root", (Resolve-Path -LiteralPath $root).Path)
}
if ($AllowNonInteractive) {
    $arguments += "--allow-noninteractive"
}
& $python @arguments
exit $LASTEXITCODE
