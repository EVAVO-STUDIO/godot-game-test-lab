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
        status = @($status | ForEach-Object { [string]$_ })
    }
}

function Assert-RepoStateUnchanged {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][System.Collections.IDictionary]$Before,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $after = Get-RepoState -Path $Path
    if ($after.branch -ne $Before.branch -or $after.sha -ne $Before.sha) {
        throw "$Label branch or HEAD changed during authority peer-exchange verification."
    }
    if (($after.status -join "`n") -ne ($Before.status -join "`n")) {
        throw "$Label working-tree status changed during authority peer-exchange verification."
    }
    return $after
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

function Invoke-TestLabModule {
    param(
        [Parameter(Mandatory = $true)][System.Collections.IDictionary]$Python,
        [Parameter(Mandatory = $true)][string]$TestLabRoot,
        [Parameter(Mandatory = $true)][string]$Module,
        [Parameter(Mandatory = $true)][string]$Path
    )

    $oldPythonPath = $env:PYTHONPATH
    $env:PYTHONPATH = if ([string]::IsNullOrWhiteSpace($oldPythonPath)) {
        Join-Path $TestLabRoot "src"
    } else {
        "$(Join-Path $TestLabRoot 'src')$([IO.Path]::PathSeparator)$oldPythonPath"
    }
    try {
        $pythonArgs = @($Python.prefix) + @("-m", $Module, $Path)
        $output = @(& $Python.executable @pythonArgs 2>&1)
        $exitCode = $LASTEXITCODE
    } finally {
        $env:PYTHONPATH = $oldPythonPath
    }
    return [ordered]@{ output = $output; exitCode = $exitCode }
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
$AcceptanceModule = Join-Path $TestLabRoot "src\godot_game_test_lab\authority_peer_exchange_acceptance.py"
foreach ($required in @($VerifierModule, $AcceptanceModule)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Required Test Lab authority verifier is missing: $required"
    }
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
$Python = Resolve-PythonInvocation

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
$RunId = "authority-$($TargetState.sha.Substring(0, 12))-$($LabState.sha.Substring(0, 12))"
$RunRoot = Join-Path $ArtifactRoot $RunId
if (Test-Path -LiteralPath $RunRoot) {
    Assert-NotLink -Path $RunRoot -Label "Existing authority peer-exchange run directory"
    Remove-Item -LiteralPath $RunRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $RunRoot -Force | Out-Null
Assert-NotLink -Path $RunRoot -Label "Authority peer-exchange run directory"
$ReceiptPath = Join-Path $RunRoot "authority-peer-exchange.json"
$EmitterStderrPath = Join-Path $RunRoot "emitter.stderr.log"
$VerificationPath = Join-Path $RunRoot "verification.json"
$AcceptancePath = Join-Path $RunRoot "acceptance.json"

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

$VerifierRun = Invoke-TestLabModule -Python $Python -TestLabRoot $TestLabRoot -Module "godot_game_test_lab.authority_peer_exchange" -Path $ReceiptPath
if ($VerifierRun.exitCode -ne 0) {
    $VerifierRun.output | ForEach-Object { Write-Host $_ }
    throw "Test Lab authority peer-exchange verifier failed with exit code $($VerifierRun.exitCode)."
}
$ExpectedVerifierSentinel = "EVAVO_AUTHORITY_PEER_EXCHANGE=PASS roles=$ExpectedRoleCount"
$VerifierMarkers = @($VerifierRun.output | Where-Object { $_ -eq $ExpectedVerifierSentinel })
if ($VerifierMarkers.Count -ne 1) {
    $VerifierRun.output | ForEach-Object { Write-Host $_ }
    throw "Test Lab verifier did not produce exactly one expected PASS sentinel."
}
$JsonLine = $VerifierRun.output | Where-Object { $_ -match '^\{' } | Select-Object -First 1
if ([string]::IsNullOrWhiteSpace($JsonLine)) {
    throw "Test Lab verifier did not emit its JSON result."
}
$Verified = $JsonLine | ConvertFrom-Json
if (
    $Verified.proven -ne $true -or
    $Verified.receiptSchemaVersion -ne 2 -or
    $Verified.authoritySafetyProven -ne $true -or
    $Verified.authorityLifecycleProven -ne $true -or
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

[void](Assert-RepoStateUnchanged -Path $TargetRepoRoot -Before $TargetState -Label "Target repository")
[void](Assert-RepoStateUnchanged -Path $TestLabRoot -Before $LabState -Label "Test Lab repository")

$ReceiptItem = Get-Item -LiteralPath $ReceiptPath
$ReceiptDigest = (Get-FileHash -LiteralPath $ReceiptPath -Algorithm SHA256).Hash.ToLowerInvariant()
$EvidenceGrade = "diagnostic"
if (-not $AllowDirty) {
    $Acceptance = [ordered]@{
        schemaVersion = "3.0"
        kind = "evavo-authority-peer-exchange-acceptance"
        status = "passed"
        runId = $RunId
        testLab = [ordered]@{ sha = $LabState.sha; branch = "main"; dirty = $false }
        target = [ordered]@{ sha = $TargetState.sha; branch = "main"; dirty = $false }
        nodeVersion = "v$NodeVersionText"
        emitter = [ordered]@{
            relativePath = $EmitterRelativePath.Replace('\', '/')
            marker = "EVAVO_AUTHORITY_PEER_EXCHANGE_RECEIPT=PASS"
            markerOccurrences = 1
        }
        receipt = [ordered]@{
            path = "authority-peer-exchange.json"
            sha256 = $ReceiptDigest
            bytes = [int64]$ReceiptItem.Length
        }
        verifier = [ordered]@{
            marker = $ExpectedVerifierSentinel
            markerOccurrences = 1
            proven = $true
            privacySafe = $true
            stablePeerMapping = $true
            requiredRoleCount = [int]$Verified.requiredRoleCount
            gameId = [string]$Verified.gameId
            authority = [string]$Verified.authority
            protocol = [string]$Verified.protocol
            sessionId = [string]$Verified.sessionId
            receiptSchemaVersion = [int]$Verified.receiptSchemaVersion
            authoritySafetyProven = $true
            authorityLifecycleProven = $true
            transportProven = $false
            browserTransportProven = $false
        }
        sourceUnchanged = $true
    }
    $Acceptance | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $AcceptancePath -Encoding utf8NoBOM
    Assert-NotLink -Path $AcceptancePath -Label "Authority peer-exchange acceptance manifest"

    $AcceptanceRun = Invoke-TestLabModule -Python $Python -TestLabRoot $TestLabRoot -Module "godot_game_test_lab.authority_peer_exchange_acceptance" -Path $AcceptancePath
    if ($AcceptanceRun.exitCode -ne 0) {
        $AcceptanceRun.output | ForEach-Object { Write-Host $_ }
        throw "Test Lab authority acceptance verifier failed with exit code $($AcceptanceRun.exitCode)."
    }
    $ExpectedAcceptanceSentinel = "EVAVO_AUTHORITY_PEER_EXCHANGE_ACCEPTANCE_VERIFY=PASS target_sha=$($TargetState.sha) lab_sha=$($LabState.sha)"
    $AcceptanceMarkers = @($AcceptanceRun.output | Where-Object { $_ -eq $ExpectedAcceptanceSentinel })
    if ($AcceptanceMarkers.Count -ne 1) {
        $AcceptanceRun.output | ForEach-Object { Write-Host $_ }
        throw "Test Lab authority acceptance verifier did not produce exactly one expected PASS sentinel."
    }
    $AcceptanceJsonLine = $AcceptanceRun.output | Where-Object { $_ -match '^\{' } | Select-Object -First 1
    if ([string]::IsNullOrWhiteSpace($AcceptanceJsonLine)) {
        throw "Test Lab authority acceptance verifier did not emit its JSON result."
    }
    $Accepted = $AcceptanceJsonLine | ConvertFrom-Json
    if (
        $Accepted.acceptanceSchemaVersion -ne 3 -or
        $Accepted.receiptSchemaVersion -ne 2 -or
        $Accepted.proven -ne $true -or
        $Accepted.authorityLifecycleProven -ne $true -or
        $Accepted.authoritySafetyProven -ne $true -or
        $Accepted.transportProven -ne $false -or
        $Accepted.browserTransportProven -ne $false -or
        $Accepted.sourceBound -ne $true -or
        [string]$Accepted.receiptSha256 -ne $ReceiptDigest
    ) {
        throw "Test Lab authority acceptance result does not satisfy the source-bound v3 contract."
    }
    $AcceptanceRun.output | ForEach-Object { Write-Host $_ }
    $EvidenceGrade = "source-bound-v3"
}
else {
    $Diagnostic = [ordered]@{
        schemaVersion = 1
        kind = "evavo-authority-peer-exchange-diagnostic"
        target = [ordered]@{ branch = $TargetState.branch; sha = $TargetState.sha; dirty = $TargetState.dirty }
        testLab = [ordered]@{ branch = $LabState.branch; sha = $LabState.sha; dirty = $LabState.dirty }
        receiptSha256 = $ReceiptDigest
        gameId = [string]$Verified.gameId
        authority = [string]$Verified.authority
        protocol = [string]$Verified.protocol
        requiredRoleCount = [int]$Verified.requiredRoleCount
        authorityLifecycleProven = $true
        authoritySafetyProven = $true
        transportProven = $false
        browserTransportProven = $false
        sourceBound = $false
    }
    $Diagnostic | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $VerificationPath -Encoding utf8NoBOM
}

[void](Assert-RepoStateUnchanged -Path $TargetRepoRoot -Before $TargetState -Label "Target repository")
[void](Assert-RepoStateUnchanged -Path $TestLabRoot -Before $LabState -Label "Test Lab repository")

$VerifierRun.output | ForEach-Object { Write-Host $_ }
Write-Host "EVAVO_AUTHORITY_PEER_EXCHANGE_TARGET=PASS target_sha=$($TargetState.sha) test_lab_sha=$($LabState.sha) roles=$ExpectedRoleCount evidence_grade=$EvidenceGrade"
Write-Host "Authority receipt: $ReceiptPath"
if (-not $AllowDirty) {
    Write-Host "Acceptance manifest: $AcceptancePath"
} else {
    Write-Host "Diagnostic receipt: $VerificationPath"
}
