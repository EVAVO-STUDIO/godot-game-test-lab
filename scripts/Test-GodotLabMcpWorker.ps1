[CmdletBinding()]
param(
    [string]$LabRoot = "",
    [string[]]$AllowedTargetRoots = @("C:\GitRepos"),
    [string]$EvidenceRoot = "C:\GodotLabEvidence",
    [string]$EngineRoot = "$env:LOCALAPPDATA\EVAVO\GodotGameTestLab\engines",
    [string]$TaskName = "EVAVO Godot Game Test Lab MCP",
    [ValidateRange(1, 65535)]
    [int]$Port = 8765,
    [ValidateRange(1, 120)]
    [int]$TimeoutSeconds = 30,
    [string]$ExpectedLabSha = "",
    [string]$OutputPath = "",
    [switch]$EngineOffline,
    [switch]$RequireScheduledTask
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Assert-NoReparsePoint {
    param([Parameter(Mandatory = $true)][string]$Path)
    $item = Get-Item -LiteralPath $Path -Force
    while ($null -ne $item) {
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Path traverses a reparse point: $Path"
        }
        $item = $item.Parent
    }
}

function Get-GitText {
    param([string]$Root, [string[]]$Arguments, [string]$Label)
    $lines = @(& git -C $Root @Arguments 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed: $($lines -join [Environment]::NewLine)"
    }
    return ($lines -join "`n").TrimEnd()
}

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw "MCP worker acceptance must run on Windows."
}
if (-not $LabRoot) {
    $LabRoot = Split-Path -Parent $PSScriptRoot
}
$lab = (Resolve-Path -LiteralPath $LabRoot).Path
$python = Join-Path $lab ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Run scripts\Install-GodotLab.ps1 before MCP worker acceptance."
}
Assert-NoReparsePoint -Path $lab
Assert-NoReparsePoint -Path $python

New-Item -ItemType Directory -Force -Path $EvidenceRoot, $EngineRoot | Out-Null
$evidence = (Resolve-Path -LiteralPath $EvidenceRoot).Path
$engines = (Resolve-Path -LiteralPath $EngineRoot).Path
Assert-NoReparsePoint -Path $evidence
Assert-NoReparsePoint -Path $engines

$resolvedRoots = [Collections.Generic.List[string]]::new()
$seenRoots = [Collections.Generic.HashSet[string]]::new(
    [StringComparer]::OrdinalIgnoreCase
)
foreach ($root in $AllowedTargetRoots) {
    $resolved = (Resolve-Path -LiteralPath $root).Path
    Assert-NoReparsePoint -Path $resolved
    if ($seenRoots.Add($resolved)) {
        $resolvedRoots.Add($resolved)
    }
}
if ($resolvedRoots.Count -eq 0) {
    throw "At least one allowed target root is required."
}

$labSha = Get-GitText -Root $lab -Arguments @("rev-parse", "HEAD") -Label "Resolve Lab SHA"
if (-not $ExpectedLabSha) {
    $ExpectedLabSha = $labSha
}
if ($ExpectedLabSha -notmatch '^[0-9a-f]{40}$' -or $labSha -ne $ExpectedLabSha) {
    throw "The Lab checkout does not match ExpectedLabSha."
}
$labStatus = Get-GitText -Root $lab -Arguments @(
    "status", "--porcelain=v1", "--untracked-files=all"
) -Label "Read complete Lab status"
if ($labStatus) {
    throw "The Lab checkout has tracked or untracked source changes."
}

if ($RequireScheduledTask) {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $task) {
        throw "The expected MCP scheduled task is not registered: $TaskName"
    }
}

if (-not $OutputPath) {
    $stamp = [DateTimeOffset]::UtcNow.ToString("yyyyMMdd-HHmmssfff")
    $directory = Join-Path $evidence "worker-acceptance\$stamp"
    New-Item -ItemType Directory -Path $directory | Out-Null
    $OutputPath = Join-Path $directory "mcp-worker-acceptance.json"
}
else {
    $destination = [IO.Path]::GetFullPath($OutputPath)
    $parent = Split-Path -Parent $destination
    if ($parent) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
    $OutputPath = $destination
}

$arguments = @(
    "-m", "godot_game_test_lab.mcp_probe",
    "--endpoint", "http://127.0.0.1:$Port/mcp",
    "--expected-lab-root", $lab,
    "--expected-evidence-root", $evidence,
    "--expected-engine-root", $engines,
    "--timeout-seconds", $TimeoutSeconds.ToString(),
    "--output", $OutputPath
)
foreach ($root in $resolvedRoots) {
    $arguments += @("--expected-allowed-root", $root)
}
if ($EngineOffline) {
    $arguments += "--expect-no-auto-provision"
}

Write-Host "[godot-lab] Probing the exact loopback MCP protocol identity."
& $python @arguments
if ($LASTEXITCODE -ne 0) {
    throw "The loopback endpoint did not prove the expected Godot Lab MCP identity."
}

$probe = Get-Content -Raw -LiteralPath $OutputPath | ConvertFrom-Json
if ($probe.status -ne "passed" -or
    $probe.capabilities.bridge -ne "evavo-godot-lab-agent") {
    throw "The MCP worker probe receipt is not an accepted EVAVO Godot Lab result."
}
Write-Host "[godot-lab] MCP worker identity accepted. Receipt: $OutputPath"
