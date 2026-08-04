[CmdletBinding()]
param(
    [string]$LabRoot = "C:\GitRepos\godot-game-test-lab",
    [string]$PythonExecutable = "",
    [string[]]$AllowedTargetRoots = @("C:\GitRepos"),
    [string]$EvidenceRoot = "C:\GodotLabEvidence",
    [string]$EngineRoot = "$env:LOCALAPPDATA\EVAVO\GodotGameTestLab\engines",
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$')]
    [string]$ServerName = "evavo-godot-game-test-lab",
    [string]$OutputPath = "",
    [switch]$AllowNonInteractive,
    [switch]$NoAutoProvision
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$common = Join-Path $PSScriptRoot "GodotLabEstateAcceptance.Common.ps1"
if (-not (Test-Path -LiteralPath $common -PathType Leaf)) {
    throw "The governed path-policy module is missing: $common"
}
$commonItem = Get-Item -LiteralPath $common -Force
if (($commonItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
    throw "The governed path-policy module may not be a reparse point: $common"
}
. $common

function Test-GeneratedMcpConfig {
    param(
        [Parameter(Mandatory = $true)][object]$Value,
        [Parameter(Mandatory = $true)][string]$ExpectedServerName
    )

    try {
        Assert-ExactProperties -Value $Value `
            -Expected @("mcpServers") `
            -Label "Existing MCP configuration"
        $servers = $Value.mcpServers
        Assert-JsonObject -Value $servers `
            -Label "Existing MCP configuration mcpServers"
        Assert-ExactProperties -Value $servers `
            -Expected @($ExpectedServerName) `
            -Label "Existing MCP configuration mcpServers"
        $server = $servers.PSObject.Properties[$ExpectedServerName].Value
        Assert-ExactProperties -Value $server `
            -Expected @("command", "args") `
            -Label "Existing MCP server"
        Assert-JsonString -Value $server.command `
            -Label "Existing MCP server command"
        Assert-JsonStringArray -Value $server.args `
            -Label "Existing MCP server args"
        return $true
    }
    catch {
        return $false
    }
}

function Write-AtomicUtf8Text {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Value
    )

    $parent = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
        throw "MCP configuration parent does not exist: $parent"
    }
    Assert-NoReparsePoint -Path $parent
    $temporary = Join-Path $parent (
        ".{0}.tmp-{1}-{2}" -f @(
            [IO.Path]::GetFileName($Path),
            $PID,
            [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
        )
    )
    try {
        [IO.File]::WriteAllText(
            $temporary,
            $Value,
            [Text.UTF8Encoding]::new($false)
        )
        Move-Item -LiteralPath $temporary -Destination $Path -Force
    }
    finally {
        if (Test-Path -LiteralPath $temporary) {
            Remove-Item -LiteralPath $temporary -Force
        }
    }
}

$labCandidate = [IO.Path]::GetFullPath($LabRoot)
if (-not (Test-Path -LiteralPath $labCandidate -PathType Container)) {
    throw "LabRoot must identify the Godot Game Test Lab directory."
}
Assert-NoReparsePoint -Path $labCandidate
$resolvedLab = (Resolve-Path -LiteralPath $labCandidate).Path

if (-not $PythonExecutable) {
    $PythonExecutable = Join-Path $resolvedLab ".venv\Scripts\python.exe"
}
$pythonCandidate = [IO.Path]::GetFullPath($PythonExecutable)
if (-not (Test-Path -LiteralPath $pythonCandidate -PathType Leaf)) {
    throw "PythonExecutable must identify the Lab virtual-environment Python executable."
}
Assert-NoReparsePoint -Path $pythonCandidate
$resolvedPython = (Resolve-Path -LiteralPath $pythonCandidate).Path

$resolvedRoots = [Collections.Generic.List[string]]::new()
$seenRoots = [Collections.Generic.HashSet[string]]::new(
    [StringComparer]::OrdinalIgnoreCase
)
foreach ($root in $AllowedTargetRoots) {
    if (-not $root) {
        throw "Allowed target roots may not contain an empty value."
    }
    $candidate = [IO.Path]::GetFullPath($root)
    if (-not (Test-Path -LiteralPath $candidate -PathType Container)) {
        throw "Allowed target root is not a directory: $candidate"
    }
    Assert-NoReparsePoint -Path $candidate
    $resolved = (Resolve-Path -LiteralPath $candidate).Path
    if ($seenRoots.Add($resolved)) {
        $resolvedRoots.Add($resolved)
    }
}
if ($resolvedRoots.Count -eq 0) {
    throw "At least one AllowedTargetRoots value is required."
}

if (-not [IO.Path]::IsPathRooted($EvidenceRoot)) {
    throw "EvidenceRoot must be an absolute path."
}
if (-not [IO.Path]::IsPathRooted($EngineRoot)) {
    throw "EngineRoot must be an absolute path."
}
$candidateEvidence = [IO.Path]::GetFullPath($EvidenceRoot)
$candidateEngine = [IO.Path]::GetFullPath($EngineRoot)
Assert-NoReparsePointForCandidate -Path $candidateEvidence
Assert-NoReparsePointForCandidate -Path $candidateEngine

if (Test-PathsOverlap -Left $candidateEvidence -Right $resolvedLab) {
    throw "EvidenceRoot must remain disjoint from the Lab checkout."
}
foreach ($root in $resolvedRoots) {
    if (Test-PathsOverlap -Left $candidateEvidence -Right $root) {
        throw "EvidenceRoot must remain disjoint from every allowed target root."
    }
}
foreach ($protected in @($resolvedLab, $candidateEvidence) + @($resolvedRoots)) {
    if (Test-PathsOverlap -Left $candidateEngine -Right $protected) {
        throw "EngineRoot must remain disjoint from Lab, target, and evidence roots."
    }
}

$destination = ""
if ($OutputPath) {
    if (-not [IO.Path]::IsPathRooted($OutputPath)) {
        throw "OutputPath must be an absolute path."
    }
    $destination = [IO.Path]::GetFullPath($OutputPath)
    Assert-NoReparsePointForCandidate -Path $destination
    if ($destination.Equals(
        $candidateEvidence,
        [StringComparison]::OrdinalIgnoreCase
    ) -or -not (Test-IsWithinPath `
        -Candidate $destination `
        -Parent $candidateEvidence)) {
        throw "OutputPath must remain strictly beneath EvidenceRoot."
    }
}

New-Item -ItemType Directory -Force -Path $candidateEvidence, $candidateEngine |
    Out-Null
$resolvedEvidence = (Resolve-Path -LiteralPath $candidateEvidence).Path
$resolvedEngine = (Resolve-Path -LiteralPath $candidateEngine).Path
Assert-NoReparsePoint -Path $resolvedEvidence
Assert-NoReparsePoint -Path $resolvedEngine

if (Test-PathsOverlap -Left $resolvedEvidence -Right $resolvedLab) {
    throw "EvidenceRoot must remain disjoint from the Lab checkout."
}
foreach ($root in $resolvedRoots) {
    if (Test-PathsOverlap -Left $resolvedEvidence -Right $root) {
        throw "EvidenceRoot must remain disjoint from every allowed target root."
    }
}
foreach ($protected in @($resolvedLab, $resolvedEvidence) + @($resolvedRoots)) {
    if (Test-PathsOverlap -Left $resolvedEngine -Right $protected) {
        throw "EngineRoot must remain disjoint from Lab, target, and evidence roots."
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
$json = ($config | ConvertTo-Json -Depth 8) + [Environment]::NewLine

if ($destination) {
    if (-not (Test-IsWithinPath `
        -Candidate $destination `
        -Parent $resolvedEvidence)) {
        throw "Resolved OutputPath must remain beneath EvidenceRoot."
    }
    $parent = Split-Path -Parent $destination
    if (-not $parent) {
        throw "OutputPath must have a parent directory."
    }
    Assert-NoReparsePointForCandidate -Path $parent
    if (-not (Test-IsWithinPath `
        -Candidate $parent `
        -Parent $resolvedEvidence)) {
        throw "OutputPath parent must remain beneath EvidenceRoot."
    }
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    $resolvedParent = (Resolve-Path -LiteralPath $parent).Path
    Assert-NoReparsePoint -Path $resolvedParent
    if (-not (Test-IsWithinPath `
        -Candidate $resolvedParent `
        -Parent $resolvedEvidence)) {
        throw "Resolved OutputPath parent must remain beneath EvidenceRoot."
    }

    if (Test-Path -LiteralPath $destination) {
        if (-not (Test-Path -LiteralPath $destination -PathType Leaf)) {
            throw "OutputPath must identify a regular file."
        }
        Assert-NoReparsePoint -Path $destination
        $existing = Read-StrictJsonFile `
            -Path $destination `
            -PythonExecutable $resolvedPython `
            -Label "Existing MCP configuration" `
            -MaximumBytes 1048576
        if (-not (Test-GeneratedMcpConfig `
            -Value $existing.Value `
            -ExpectedServerName $ServerName)) {
            throw (
                "OutputPath already exists and is not a standalone generated " +
                "Godot Lab MCP configuration. Refusing to overwrite it."
            )
        }
    }

    Write-AtomicUtf8Text -Path $destination -Value $json
    Assert-NoReparsePoint -Path $destination
    if (-not (Test-IsWithinPath `
        -Candidate (Resolve-Path -LiteralPath $destination).Path `
        -Parent $resolvedEvidence)) {
        throw "Written MCP configuration escaped EvidenceRoot."
    }
    Write-Host "[godot-lab] MCP configuration written to $destination"
}
else {
    $json.TrimEnd()
}
