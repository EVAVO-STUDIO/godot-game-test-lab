[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$TargetRepoRoot,
    [Parameter(Mandatory = $true)][string]$EmitterRelativePath,
    [string]$ExpectedGameId = "",
    [int]$ExpectedRoleCount = 2,
    [string]$ArtifactRelativePath = "artifacts/authority-peer-exchange",
    [switch]$AllowDirty
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Get-RepoState {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath (Join-Path $Path ".git"))) {
        throw "Not a Git repository: $Path"
    }
    $branch = (& git -C $Path branch --show-current).Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($branch)) {
        throw "Unable to resolve Git branch for $Path"
    }
    $sha = (& git -C $Path rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or $sha -notmatch '^[0-9a-f]{40}$') {
        throw "Unable to resolve Git SHA for $Path"
    }
    $status = @(& git -C $Path status --porcelain=v1 --untracked-files=normal)
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to resolve Git status for $Path"
    }
    return [ordered]@{
        branch = $branch
        sha = $sha
        dirty = ($status.Count -gt 0)
    }
}

function Resolve-PythonInvocation {
    if (Get-Command python -ErrorAction SilentlyContinue) {
        return [ordered]@{ executable = "python"; prefix = @() }
    }
    if (Get-Command py -ErrorAction SilentlyContinue) {
        return [ordered]@{ executable = "py"; prefix = @("-3") }
    }
    throw "Python 3.11+ is required to run the Test Lab verifier."
}

function Assert-ContainedPath {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$Candidate,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $relative = [IO.Path]::GetRelativePath($Root, $Candidate)
    if (
        [IO.Path]::IsPathRooted($relative) -or
        $relative -eq ".." -or
        $relative.StartsWith("..$([IO.Path]::DirectorySeparatorChar)", [StringComparison]::Ordinal) -or
        $relative.StartsWith("..$([IO.Path]::AltDirectorySeparatorChar)", [StringComparison]::Ordinal)
    ) {
        throw "$Label must remain inside the target repository."
    }
}

function Assert-NotLink {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label
    )

    if (-not (Test-Path -LiteralPath $Path)) { return }
    $item = Get-Item -LiteralPath $Path -Force
    if (-not [string]::IsNullOrWhiteSpace([string]$item.LinkType)) {
        throw "$Label must not be a symbolic link or junction."
    }
}

if ($ExpectedRoleCount -lt 2 -or $ExpectedRoleCount -gt 32) {
    throw "ExpectedRoleCount must be between 2 and 32."
}

$TestLabRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$TargetRepoRoot = (Resolve-Path -LiteralPath $TargetRepoRoot).Path
Assert-NotLink -Path $TargetRepoRoot -Label "Target repository root"
$EmitterPath = [IO.Path]::GetFullPath((Join-Path $TargetRepoRoot $EmitterRelativePath))
Assert-ContainedPath -Root $TargetRepoRoot -Candidate $EmitterPath -Label "EmitterRelativePath"
if (-not (Test-Path -LiteralPath $EmitterPath -PathType Leaf)) {
    throw "Authority peer-exchange emitter is missing: $EmitterPath"
}
Assert-NotLink -Path $EmitterPath -Label "Authority peer-exchange emitter"
if ([IO.Path]::GetExtension($EmitterPath) -ne ".mjs") {
    throw "Authority peer-exchange emitter must be an .mjs file."
}
$VerifierModule = Join-Path $TestLabRoot "src\godot_game_test_lab\authority_peer_exchange.py"
if (-not (Test-Path -LiteralPath $VerifierModule -PathType Leaf)) {
    throw "Test Lab authority peer-exchange verifier is missing."
}
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    throw "Node.js 20+ is required to run the authority emitter."
}
$NodeVersionText = (& node -p "process.versions.node").Trim()
if ($LASTEXITCODE -ne 0 -or $NodeVersionText -notmatch '^(\d+)\.') {
    throw "Unable to determine Node.js version."
}
if ([int]$Matches[1] -lt 20) {
    throw "Node.js 20+ is required to run the authority emitter; found $NodeVersionText."
}

$TargetState = Get-RepoState -Path $TargetRepoRoot
$LabState = Get-RepoState -Path $TestLabRoot
foreach ($entry in @(
    @{ name = "target"; state = $TargetState },
    @{ name = "godot-game-test-lab"; state = $LabState }
)) {
    if ($entry.state.branch -ne "main") {
        throw "$($entry.name) must be on main; found $($entry.state.branch)."
    }
    if (-not $AllowDirty -and $entry.state.dirty) {
        throw "$($entry.name) has uncommitted changes. Use -AllowDirty only for diagnostic evidence."
    }
}

$ArtifactRoot = [IO.Path]::GetFullPath((Join-Path $TargetRepoRoot $ArtifactRelativePath))
Assert-ContainedPath -Root $TargetRepoRoot -Candidate $ArtifactRoot -Label "ArtifactRelativePath"
New-Item -ItemType Directory -Path $ArtifactRoot -Force | Out-Null
Assert-NotLink -Path $ArtifactRoot -Label "Authority peer-exchange artifact directory"
$ReceiptPath = Join-Path $ArtifactRoot "authority-peer-exchange.json"
$EmitterStderrPath = Join-Path $ArtifactRoot "emitter.stderr.log"
$VerificationPath = Join-Path $ArtifactRoot "verification.json"

& node $EmitterPath 1> $ReceiptPath 2> $EmitterStderrPath
$EmitterExit = $LASTEXITCODE
if ($EmitterExit -ne 0) {
    throw "Authority peer-exchange emitter failed with exit code $EmitterExit."
}
$EmitterMarkers = @(
    Get-Content -LiteralPath $EmitterStderrPath |
        Where-Object { $_ -eq "EVAVO_AUTHORITY_PEER_EXCHANGE_RECEIPT=PASS" }
)
if ($EmitterMarkers.Count -ne 1) {
    throw "Authority emitter did not produce exactly one PASS sentinel."
}
if (-not (Test-Path -LiteralPath $ReceiptPath) -or (Get-Item -LiteralPath $ReceiptPath).Length -lt 2) {
    throw "Authority peer-exchange receipt was not retained."
}
Assert-NotLink -Path $ReceiptPath -Label "Authority peer-exchange receipt"

$Python = Resolve-PythonInvocation
$OldPythonPath = $env:PYTHONPATH
$env:PYTHONPATH = if ([string]::IsNullOrWhiteSpace($OldPythonPath)) {
    Join-Path $TestLabRoot "src"
} else {
    "$(Join-Path $TestLabRoot 'src')$([IO.Path]::PathSeparator)$OldPythonPath"
}
try {
    $PythonArgs = @($Python.prefix) + @(
        "-m",
        "godot_game_test_lab.authority_peer_exchange",
        $ReceiptPath
    )
    $VerifierOutput = @(& $Python.executable @PythonArgs 2>&1)
    $VerifierExit = $LASTEXITCODE
} finally {
    $env:PYTHONPATH = $OldPythonPath
}
if ($VerifierExit -ne 0) {
    $VerifierOutput | ForEach-Object { Write-Host $_ }
    throw "Test Lab authority peer-exchange verifier failed with exit code $VerifierExit."
}
$ExpectedVerifierSentinel = "EVAVO_AUTHORITY_PEER_EXCHANGE=PASS roles=$ExpectedRoleCount"
$VerifierMarkers = @($VerifierOutput | Where-Object { $_ -eq $ExpectedVerifierSentinel })
if ($VerifierMarkers.Count -ne 1) {
    $VerifierOutput | ForEach-Object { Write-Host $_ }
    throw "Test Lab verifier did not produce exactly one expected PASS sentinel."
}

$JsonLine = $VerifierOutput | Where-Object { $_ -match '^\{' } | Select-Object -First 1
if ([string]::IsNullOrWhiteSpace($JsonLine)) {
    throw "Test Lab verifier did not emit its JSON result."
}
$Verified = $JsonLine | ConvertFrom-Json
if (
    $Verified.proven -ne $true -or
    $Verified.receiptSchemaVersion -ne 2 -or
    $Verified.authoritySafetyProven -ne $true -or
    $Verified.departureRevocationProven -ne $true -or
    $Verified.reconnectPeerSemanticsProven -ne $true -or
    $Verified.transportProven -ne $false -or
    $Verified.browserTransportProven -ne $false -or
    [int]$Verified.requiredRoleCount -ne $ExpectedRoleCount
) {
    throw "Test Lab verifier result does not satisfy the authority lifecycle contract."
}
if (-not [string]::IsNullOrWhiteSpace($ExpectedGameId) -and [string]$Verified.gameId -ne $ExpectedGameId) {
    throw "Authority peer-exchange game ID mismatch: expected '$ExpectedGameId', found '$($Verified.gameId)'."
}

$Combined = [ordered]@{
    schemaVersion = 1
    kind = "evavo-authority-peer-exchange-target-verification"
    target = [ordered]@{
        branch = $TargetState.branch
        sha = $TargetState.sha
        dirty = $TargetState.dirty
    }
    testLab = [ordered]@{
        branch = $LabState.branch
        sha = $LabState.sha
        dirty = $LabState.dirty
    }
    allowDirty = [bool]$AllowDirty
    emitterRelativePath = $EmitterRelativePath.Replace('\', '/')
    emitterSentinel = "EVAVO_AUTHORITY_PEER_EXCHANGE_RECEIPT=PASS"
    verifierSentinel = $ExpectedVerifierSentinel
    gameId = [string]$Verified.gameId
    authority = [string]$Verified.authority
    protocol = [string]$Verified.protocol
    requiredRoleCount = [int]$Verified.requiredRoleCount
    authorityLifecycleProven = $true
    authoritySafetyProven = $true
    browserTransportProven = $false
    transportProven = $false
    receipt = (Resolve-Path -LiteralPath $ReceiptPath).Path
    verifiedAtUtc = [DateTime]::UtcNow.ToString("o")
}
$Combined | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $VerificationPath -Encoding utf8NoBOM

$VerifierOutput | ForEach-Object { Write-Host $_ }
Write-Host "EVAVO_AUTHORITY_PEER_EXCHANGE_TARGET=PASS target_sha=$($TargetState.sha) test_lab_sha=$($LabState.sha) roles=$ExpectedRoleCount"
Write-Host "Verification receipt: $VerificationPath"
