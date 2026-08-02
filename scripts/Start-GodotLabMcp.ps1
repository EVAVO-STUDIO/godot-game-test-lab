[CmdletBinding()]
param(
    [string]$ConfigurationPath = "",
    [string]$LabRoot = "C:\GitRepos\godot-game-test-lab",
    [string[]]$AllowedTargetRoots = @("C:\GitRepos"),
    [string]$EvidenceRoot = "C:\GodotLabEvidence",
    [string]$EngineRoot = "$env:LOCALAPPDATA\EVAVO\GodotGameTestLab\engines",
    [string]$HostAddress = "127.0.0.1",
    [ValidateRange(1, 65535)]
    [int]$Port = 8765,
    [string]$ExpectedLabSha = "",
    [switch]$EngineOffline,
    [switch]$AllowNonInteractive
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
    throw "Start-GodotLabMcp.ps1 must run on Windows."
}

if ($ConfigurationPath) {
    $configurationFile = (Resolve-Path -LiteralPath $ConfigurationPath).Path
    Assert-NoReparsePoint -Path $configurationFile
    $configuration = Get-Content -Raw -LiteralPath $configurationFile | ConvertFrom-Json
    if ($configuration.schemaVersion -ne "2.0") {
        throw "Unsupported MCP worker configuration schema."
    }
    $LabRoot = [string]$configuration.labRoot
    $AllowedTargetRoots = @($configuration.allowedTargetRoots | ForEach-Object {
        [string]$_
    })
    $EvidenceRoot = [string]$configuration.evidenceRoot
    $EngineRoot = [string]$configuration.engineRoot
    $HostAddress = [string]$configuration.hostAddress
    $Port = [int]$configuration.port
    $ExpectedLabSha = [string]$configuration.labSha
    $EngineOffline = -not [bool]$configuration.autoProvisionEngines
    if (-not [bool]$configuration.requireInteractiveDesktop) {
        $AllowNonInteractive = $true
    }
}

if ($HostAddress -notin @("127.0.0.1", "::1")) {
    throw "The MCP worker host must be an explicit loopback address."
}
if ($AllowedTargetRoots.Count -eq 0) {
    throw "At least one allowed target root is required."
}

$resolvedLab = (Resolve-Path -LiteralPath $LabRoot).Path
$python = Join-Path $resolvedLab ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Run scripts\Install-GodotLab.ps1 before starting the MCP worker."
}
Assert-NoReparsePoint -Path $resolvedLab
Assert-NoReparsePoint -Path $python

New-Item -ItemType Directory -Force -Path $EvidenceRoot, $EngineRoot | Out-Null
$resolvedEvidence = (Resolve-Path -LiteralPath $EvidenceRoot).Path
$resolvedEngine = (Resolve-Path -LiteralPath $EngineRoot).Path
Assert-NoReparsePoint -Path $resolvedEvidence
Assert-NoReparsePoint -Path $resolvedEngine

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
    throw "At least one distinct allowed target root is required."
}

$labSha = Get-GitText -Root $resolvedLab -Arguments @(
    "rev-parse", "HEAD"
) -Label "Resolve Lab SHA"
if (-not $ExpectedLabSha) {
    $ExpectedLabSha = $labSha
}
if ($ExpectedLabSha -notmatch '^[0-9a-f]{40}$' -or $labSha -ne $ExpectedLabSha) {
    throw "The MCP worker configuration does not match the checked-out Lab SHA."
}
$labStatus = Get-GitText -Root $resolvedLab -Arguments @(
    "status", "--porcelain=v1", "--untracked-files=all"
) -Label "Read complete Lab status"
if ($labStatus) {
    throw "The MCP worker refuses a Lab checkout with tracked or untracked changes."
}

if (-not $AllowNonInteractive) {
    $session = [Diagnostics.Process]::GetCurrentProcess().SessionId
    $explorerSessions = @(
        Get-Process -Name explorer -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty SessionId -Unique
    )
    if ($session -eq 0 -or $explorerSessions -notcontains $session) {
        throw "The MCP worker requires Explorer in the current nonzero Windows session."
    }
}

$arguments = @(
    "-m", "godot_game_test_lab.mcp_server",
    "--transport", "streamable-http",
    "--host", $HostAddress,
    "--port", $Port,
    "--lab-root", $resolvedLab,
    "--evidence-root", $resolvedEvidence,
    "--engine-root", $resolvedEngine
)
foreach ($root in $resolvedRoots) {
    $arguments += @("--allowed-root", $root)
}
if ($AllowNonInteractive) {
    $arguments += "--allow-noninteractive"
}
if ($EngineOffline) {
    $arguments += "--no-auto-provision"
}

& $python @arguments
exit $LASTEXITCODE
