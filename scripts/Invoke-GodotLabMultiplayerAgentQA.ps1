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

    [ValidateRange(60, 14400)]
    [int]$MaxTotalSeconds = 3600,

    [ValidateRange(1, 200)]
    [int]$MaxArtifactGiB = 20,

    [ValidatePattern('^-?[0-9]{1,5},-?[0-9]{1,5}$')]
    [string]$WindowPosition = "32,32",

    [ValidateRange(1, 8)]
    [int]$WindowColumns = 2,

    [ValidateRange(0, 4096)]
    [int]$WindowStepX = 48,

    [ValidateRange(0, 4096)]
    [int]$WindowStepY = 48,

    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._ -]{0,127}$')]
    [string]$SessionLabel = "evavo-multiplayer-session",

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
if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "Multiplayer native agent QA must run on Windows."
}

$currentSession = [System.Diagnostics.Process]::GetCurrentProcess().SessionId
$explorerSessions = @(
    Get-Process -Name explorer -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty SessionId -Unique
)
if (-not $AllowNonInteractive) {
    if ($currentSession -eq 0 -or $explorerSessions -notcontains $currentSession) {
        throw (
            "Multiplayer native visual QA requires Explorer in the worker's nonzero Windows session. " +
            "Do not run the approved worker as a conventional Session 0 service."
        )
    }
}
else {
    Write-Warning (
        "AllowNonInteractive is for contract tests only. This run cannot produce " +
        "native desktop evidence and will never emit the native PASS marker."
    )
}

$labRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
New-Item -ItemType Directory -Force -Path $AllowedArtifactRoot | Out-Null
$maxArtifactBytes = [int64]$MaxArtifactGiB * 1GB
$arguments = @(
    "-m", "godot_game_test_lab.multiplayer_qa",
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
    "--max-total-seconds", $MaxTotalSeconds.ToString(),
    "--max-artifact-bytes", $maxArtifactBytes.ToString(),
    "--window-position", $WindowPosition,
    "--window-columns", $WindowColumns.ToString(),
    "--window-step-x", $WindowStepX.ToString(),
    "--window-step-y", $WindowStepY.ToString(),
    "--session-label", $SessionLabel
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

Write-Host "[godot-lab] Running exact-SHA concurrent multiplayer Windows agent QA."
$global:LASTEXITCODE = 0
$OutputLines = @(& $PythonExecutable @arguments 2>&1 | ForEach-Object { [string]$_ })
$ExitCode = [int]$LASTEXITCODE
$OutputLines | ForEach-Object { Write-Host $_ }
if ($ExitCode -ne 0) {
    throw "Multiplayer Windows agent QA failed with exit code $ExitCode."
}
if ($OutputLines.Count -lt 1) {
    throw "Multiplayer Windows agent QA produced no summary output."
}

$Summary = $null
try {
    $Summary = $OutputLines[-1] | ConvertFrom-Json -ErrorAction Stop
}
catch {
    throw "Multiplayer Windows agent QA did not end with a valid JSON summary."
}
if ($null -eq $Summary) {
    throw "Multiplayer Windows agent QA summary was empty."
}
if ([string]$Summary.status -ne "passed") {
    throw "Multiplayer Windows agent QA summary did not report passed status."
}
if ([string]$Summary.labSha -ne $ExpectedLabSha) {
    throw "Multiplayer Windows agent QA summary Lab SHA does not match the requested exact SHA."
}
if ([string]$Summary.targetSha -ne $ExpectedTargetSha) {
    throw "Multiplayer Windows agent QA summary target SHA does not match the requested exact SHA."
}
if ([string]$Summary.sessionLabel -ne $SessionLabel) {
    throw "Multiplayer Windows agent QA summary session label does not match the requested session."
}
$RunId = [string]$Summary.runId
if ($RunId -notmatch '^multiplayer-[0-9]{8}T[0-9]{6}-[0-9a-f]{12}$') {
    throw "Multiplayer Windows agent QA summary run ID is malformed."
}

$SummaryPath = Join-Path $ArtifactPath "multiplayer-agent-summary.json"
if (-not (Test-Path -LiteralPath $SummaryPath -PathType Leaf)) {
    throw "Multiplayer Windows agent QA did not retain multiplayer-agent-summary.json."
}
try {
    $RetainedSummary = Get-Content -LiteralPath $SummaryPath -Raw -Encoding utf8 | ConvertFrom-Json -ErrorAction Stop
}
catch {
    throw "Retained multiplayer-agent-summary.json is not valid JSON."
}
foreach ($Field in @("runId", "status", "labSha", "targetSha", "sessionLabel")) {
    if ([string]$RetainedSummary.$Field -ne [string]$Summary.$Field) {
        throw "Retained multiplayer summary disagrees with process summary field '$Field'."
    }
}

$PeerExchangeArguments = @(
    "-m", "godot_game_test_lab.multiplayer_peer_exchange",
    "--summary", $SummaryPath,
    "--artifacts", $ArtifactPath
)
$global:LASTEXITCODE = 0
$PeerExchangeLines = @(
    & $PythonExecutable @PeerExchangeArguments 2>&1 | ForEach-Object { [string]$_ }
)
$PeerExchangeExitCode = [int]$LASTEXITCODE
$PeerExchangeLines | ForEach-Object { Write-Host $_ }
if ($PeerExchangeExitCode -ne 0) {
    throw "Configured multiplayer peer-exchange evidence did not prove reciprocal session participation."
}
$PeerExchangeMarkers = @(
    $PeerExchangeLines | Where-Object {
        $_ -match '^EVAVO_MULTIPLAYER_PEER_EXCHANGE=(PASS required_roles=[1-8]|NOT_CONFIGURED)$'
    }
)
if ($PeerExchangeMarkers.Count -ne 1) {
    throw "Multiplayer peer-exchange verifier did not emit exactly one admissible evidence marker."
}

if ($AllowNonInteractive) {
    Write-Host "EVAVO_MULTIPLAYER_AGENT_QA=CONTRACT_ONLY run_id=$RunId"
    Write-Host "[godot-lab] Multiplayer contract run completed without native desktop evidence."
    return
}

if ($Summary.nativeDesktopEvidence -ne $true -or $Summary.interactiveDesktopRequired -ne $true) {
    throw "Interactive multiplayer QA did not retain native desktop evidence."
}
$SummaryFindings = @($Summary.findings)
if ($SummaryFindings.Count -ne 0) {
    throw "Interactive multiplayer QA summary contains findings and cannot emit native PASS evidence."
}
if ($RetainedSummary.nativeDesktopEvidence -ne $true -or $RetainedSummary.interactiveDesktopRequired -ne $true) {
    throw "Retained multiplayer summary does not prove interactive native desktop evidence."
}

Write-Host "EVAVO_MULTIPLAYER_AGENT_QA=PASS run_id=$RunId"
Write-Host "[godot-lab] Multiplayer Windows agent QA passed with exact-SHA native evidence."
