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

function Test-IsWithinPath {
    param([string]$Candidate, [string]$Parent)
    $candidateFull = [IO.Path]::GetFullPath($Candidate).TrimEnd('\', '/')
    $parentFull = [IO.Path]::GetFullPath($Parent).TrimEnd('\', '/')
    return (
        $candidateFull.Equals($parentFull, [StringComparison]::OrdinalIgnoreCase) -or
        $candidateFull.StartsWith(
            $parentFull + [IO.Path]::DirectorySeparatorChar,
            [StringComparison]::OrdinalIgnoreCase
        )
    )
}

function Test-PathsOverlap {
    param([string]$Left, [string]$Right)
    return (
        (Test-IsWithinPath -Candidate $Left -Parent $Right) -or
        (Test-IsWithinPath -Candidate $Right -Parent $Left)
    )
}

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

function Assert-NoReparsePointForCandidate {
    param([Parameter(Mandatory = $true)][string]$Path)
    $cursor = [IO.Path]::GetFullPath($Path)
    while (-not (Test-Path -LiteralPath $cursor)) {
        $parent = [IO.Directory]::GetParent($cursor)
        if ($null -eq $parent) {
            return
        }
        $cursor = $parent.FullName
    }
    Assert-NoReparsePoint -Path $cursor
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

$candidateEvidence = [IO.Path]::GetFullPath($EvidenceRoot)
$candidateEngine = [IO.Path]::GetFullPath($EngineRoot)
Assert-NoReparsePointForCandidate -Path $candidateEvidence
Assert-NoReparsePointForCandidate -Path $candidateEngine

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

if (Test-PathsOverlap -Left $candidateEvidence -Right $lab) {
    throw "EvidenceRoot must remain disjoint from the Lab checkout."
}
foreach ($root in $resolvedRoots) {
    if (Test-PathsOverlap -Left $candidateEvidence -Right $root) {
        throw "EvidenceRoot must remain disjoint from every allowed target root."
    }
}
foreach ($protected in @($lab, $candidateEvidence) + @($resolvedRoots)) {
    if (Test-PathsOverlap -Left $candidateEngine -Right $protected) {
        throw "EngineRoot must remain disjoint from Lab, target, and evidence roots."
    }
}

New-Item -ItemType Directory -Force -Path $candidateEvidence, $candidateEngine |
    Out-Null
$evidence = (Resolve-Path -LiteralPath $candidateEvidence).Path
$engines = (Resolve-Path -LiteralPath $candidateEngine).Path
Assert-NoReparsePoint -Path $evidence
Assert-NoReparsePoint -Path $engines

if (Test-PathsOverlap -Left $evidence -Right $lab) {
    throw "EvidenceRoot must remain disjoint from the Lab checkout."
}
foreach ($root in $resolvedRoots) {
    if (Test-PathsOverlap -Left $evidence -Right $root) {
        throw "EvidenceRoot must remain disjoint from every allowed target root."
    }
}
foreach ($protected in @($lab, $evidence) + @($resolvedRoots)) {
    if (Test-PathsOverlap -Left $engines -Right $protected) {
        throw "EngineRoot must remain disjoint from Lab, target, and evidence roots."
    }
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
    if ([IO.Path]::GetExtension($destination) -ne ".json") {
        throw "Worker acceptance output must use a .json extension."
    }
    if (-not (Test-IsWithinPath -Candidate $destination -Parent $evidence) -or
        $destination.Equals($evidence, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Worker acceptance output must remain beneath EvidenceRoot."
    }
    if (Test-Path -LiteralPath $destination) {
        throw "Worker acceptance output already exists: $destination"
    }
    Assert-NoReparsePointForCandidate -Path $destination
    $parent = Split-Path -Parent $destination
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    $resolvedParent = (Resolve-Path -LiteralPath $parent).Path
    Assert-NoReparsePoint -Path $resolvedParent
    if (-not (Test-IsWithinPath -Candidate $resolvedParent -Parent $evidence)) {
        throw "Worker acceptance output parent escaped EvidenceRoot."
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
