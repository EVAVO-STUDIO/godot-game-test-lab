[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$TargetRepoRoot,
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-fA-F]{40}$')][string]$ExpectedTargetSha,
    [string]$ExpectedLabSha = '',
    [string]$BundleEmitterRelativePath = 'authority/scripts/emit_test_lab_peer_exchange_bundle.mjs',
    [int]$ExpectedRoleCount = 2,
    [string]$OutputRoot = ''
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Get-RepoState {
    param([Parameter(Mandatory = $true)][string]$Root, [Parameter(Mandatory = $true)][string]$Label)
    $branch = (& git -C $Root branch --show-current).Trim()
    if ($LASTEXITCODE -ne 0 -or $branch -cne 'main') { throw "$Label must be on main. Found: $branch" }
    $sha = (& git -C $Root rev-parse HEAD).Trim().ToLowerInvariant()
    if ($LASTEXITCODE -ne 0 -or $sha -notmatch '^[0-9a-f]{40}$') { throw "Could not resolve SHA for $Label." }
    $status = @(& git -C $Root status --porcelain=v1 --untracked-files=all)
    if ($LASTEXITCODE -ne 0) { throw "Could not resolve working tree state for $Label." }
    return [ordered]@{ branch = $branch; sha = $sha; dirty = ($status.Count -ne 0); status = @($status) }
}

function Assert-Unchanged {
    param([string]$Root, [System.Collections.IDictionary]$Before, [string]$Label)
    $after = Get-RepoState -Root $Root -Label $Label
    if ($after.sha -ne $Before.sha -or $after.branch -cne $Before.branch -or (($after.status -join "`n") -cne ($Before.status -join "`n"))) {
        throw "$Label changed during authority peer-exchange cross-check."
    }
}

function Resolve-Python {
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($null -ne $python) { return [ordered]@{ exe = $python.Source; prefix = @() } }
    $py = Get-Command py -ErrorAction Stop
    return [ordered]@{ exe = $py.Source; prefix = @('-3') }
}

function Invoke-LabModule {
    param([System.Collections.IDictionary]$Python, [string]$LabRoot, [string]$Module, [string[]]$Arguments)
    $previous = $env:PYTHONPATH
    try {
        $src = Join-Path $LabRoot 'src'
        $env:PYTHONPATH = if ([string]::IsNullOrWhiteSpace($previous)) { $src } else { $src + [IO.Path]::PathSeparator + $previous }
        $args = @($Python.prefix) + @('-m', $Module) + $Arguments
        $output = @(& $Python.exe @args 2>&1)
        return [ordered]@{ exitCode = $LASTEXITCODE; output = @($output | ForEach-Object { [string]$_ }) }
    } finally {
        $env:PYTHONPATH = $previous
    }
}

if ($ExpectedRoleCount -lt 2 -or $ExpectedRoleCount -gt 32) { throw 'ExpectedRoleCount must be between 2 and 32.' }
if ($ExpectedLabSha -and $ExpectedLabSha -notmatch '^[0-9a-fA-F]{40}$') { throw 'ExpectedLabSha must be an exact 40-character SHA.' }

$labRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$targetRoot = (Resolve-Path $TargetRepoRoot).Path
$expectedTarget = $ExpectedTargetSha.ToLowerInvariant()
$expectedLab = $ExpectedLabSha.ToLowerInvariant()

$null = Get-Command git -ErrorAction Stop
$node = (Get-Command node -ErrorAction Stop).Source
$python = Resolve-Python
$nodeVersion = (& $node --version).Trim()
if ($LASTEXITCODE -ne 0 -or $nodeVersion -notmatch '^v(?<Major>\d+)\.\d+\.\d+$' -or [int]$Matches['Major'] -lt 20) {
    throw "Node.js 20+ is required. Found: $nodeVersion"
}

$targetState = Get-RepoState -Root $targetRoot -Label 'Target repository'
$labState = Get-RepoState -Root $labRoot -Label 'godot-game-test-lab'
if ($targetState.sha -ne $expectedTarget) { throw "Target SHA mismatch. Expected $expectedTarget, found $($targetState.sha)" }
if ($expectedLab -and $labState.sha -ne $expectedLab) { throw "Test Lab SHA mismatch. Expected $expectedLab, found $($labState.sha)" }
if ($targetState.dirty) { throw 'Target repository must be clean.' }
if ($labState.dirty) { throw 'godot-game-test-lab must be clean.' }

$emitterPath = [IO.Path]::GetFullPath((Join-Path $targetRoot $BundleEmitterRelativePath))
$relativeEmitter = [IO.Path]::GetRelativePath($targetRoot, $emitterPath)
if (
    [IO.Path]::IsPathRooted($relativeEmitter) -or
    $relativeEmitter -eq '..' -or
    $relativeEmitter.StartsWith('..' + [IO.Path]::DirectorySeparatorChar, [StringComparison]::Ordinal) -or
    $relativeEmitter.StartsWith('..' + [IO.Path]::AltDirectorySeparatorChar, [StringComparison]::Ordinal)
) {
    throw 'Bundle emitter must remain inside the target repository.'
}
if (-not (Test-Path -LiteralPath $emitterPath -PathType Leaf)) { throw "Bundle emitter not found: $BundleEmitterRelativePath" }

if ([string]::IsNullOrWhiteSpace($OutputRoot)) {
    $OutputRoot = Join-Path ([IO.Path]::GetTempPath()) 'evavo-authority-peer-exchange-crosscheck'
}
[IO.Directory]::CreateDirectory($OutputRoot) | Out-Null
$runId = [DateTimeOffset]::UtcNow.ToString('yyyyMMddTHHmmssfffZ') + '-' + $targetState.sha.Substring(0, 12) + '-' + $labState.sha.Substring(0, 12)
$runRoot = Join-Path $OutputRoot $runId
if (Test-Path -LiteralPath $runRoot) { throw "Cross-check run root already exists: $runRoot" }
[IO.Directory]::CreateDirectory($runRoot) | Out-Null
$bundleRoot = Join-Path $runRoot 'bundle'

$emitterOutput = @(& $node $emitterPath $bundleRoot 2>&1 | ForEach-Object { [string]$_ })
$emitterExit = $LASTEXITCODE
$bundleMarkerPattern = '^EVAVO_AUTHORITY_TEST_LAB_PEER_EXCHANGE_BUNDLE=PASS required_roles=(?<Roles>\d+) output=.+$'
$bundleMarkers = @($emitterOutput | Where-Object { $_ -match $bundleMarkerPattern })
if ($emitterExit -ne 0 -or $bundleMarkers.Count -ne 1) {
    $emitterOutput | ForEach-Object { Write-Host $_ }
    throw "Authority Test Lab bundle emitter failed or emitted ambiguous evidence. Exit=$emitterExit Markers=$($bundleMarkers.Count)"
}
$null = $bundleMarkers[0] -match $bundleMarkerPattern
$reportedRoleCount = [int]$Matches['Roles']
if ($reportedRoleCount -ne $ExpectedRoleCount) { throw "Bundle role count mismatch. Expected $ExpectedRoleCount, found $reportedRoleCount" }

$crosscheck = Invoke-LabModule -Python $python -LabRoot $labRoot -Module 'godot_game_test_lab.authority_peer_exchange_crosscheck' -Arguments @($bundleRoot)
$crosscheckMarker = "EVAVO_AUTHORITY_PEER_EXCHANGE_CROSSCHECK=PASS roles=$ExpectedRoleCount"
$crosscheckMarkers = @($crosscheck.output | Where-Object { $_ -ceq $crosscheckMarker })
$jsonLines = @($crosscheck.output | Where-Object { $_ -match '^\{' -and $_ -notmatch '"status"\s*:\s*"blocked"' })
if ($crosscheck.exitCode -ne 0 -or $crosscheckMarkers.Count -ne 1 -or $jsonLines.Count -ne 1) {
    $crosscheck.output | ForEach-Object { Write-Host $_ }
    throw "Authority peer-exchange cross-check failed or emitted ambiguous evidence. Exit=$($crosscheck.exitCode) Markers=$($crosscheckMarkers.Count) Results=$($jsonLines.Count)"
}
$result = $jsonLines[0] | ConvertFrom-Json
if (
    $result.proven -ne $true -or
    $result.semanticViewsAgree -ne $true -or
    $result.authorityLifecycleProven -ne $true -or
    $result.authoritySafetyProven -ne $true -or
    $result.standardPeerExchangeProven -ne $true -or
    [int]$result.dynamicCaptureRoleCount -ne $ExpectedRoleCount -or
    $result.transportProven -ne $false -or
    $result.browserTransportProven -ne $false
) {
    throw 'Cross-check structured result did not satisfy the source-bound semantic contract.'
}

Assert-Unchanged -Root $targetRoot -Before $targetState -Label 'Target repository'
Assert-Unchanged -Root $labRoot -Before $labState -Label 'godot-game-test-lab'

$sourceReceipt = Join-Path $bundleRoot 'authority-peer-exchange-lifecycle.json'
$profile = Join-Path $bundleRoot 'profile.normalized.json'
$summary = Join-Path $bundleRoot 'multiplayer-agent-summary.json'
foreach ($file in @($sourceReceipt, $profile, $summary)) {
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { throw "Required retained evidence file missing: $file" }
}

$acceptance = [ordered]@{
    schemaVersion = '1.0'
    kind = 'evavo-authority-peer-exchange-semantic-crosscheck'
    status = 'passed'
    runId = $runId
    testLab = [ordered]@{ sha = $labState.sha; branch = 'main'; dirty = $false }
    target = [ordered]@{ sha = $targetState.sha; branch = 'main'; dirty = $false }
    nodeVersion = $nodeVersion
    emitter = [ordered]@{
        relativePath = $BundleEmitterRelativePath.Replace('\', '/')
        marker = [string]$bundleMarkers[0]
        markerOccurrences = 1
        requiredRoleCount = $reportedRoleCount
    }
    verifier = [ordered]@{
        marker = $crosscheckMarker
        markerOccurrences = 1
        requiredRoleCount = [int]$result.requiredRoleCount
        dynamicCaptureRoleCount = [int]$result.dynamicCaptureRoleCount
        semanticViewsAgree = $true
        authorityLifecycleProven = $true
        authoritySafetyProven = $true
        standardPeerExchangeProven = $true
        transportProven = $false
        browserTransportProven = $false
    }
    evidence = [ordered]@{
        authorityReceiptSha256 = (Get-FileHash -LiteralPath $sourceReceipt -Algorithm SHA256).Hash.ToLowerInvariant()
        profileSha256 = (Get-FileHash -LiteralPath $profile -Algorithm SHA256).Hash.ToLowerInvariant()
        summarySha256 = (Get-FileHash -LiteralPath $summary -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    sourceUnchanged = $true
    truthBoundary = [string]$result.truthBoundary
}
$acceptancePath = Join-Path $runRoot 'acceptance.json'
$acceptance | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $acceptancePath -Encoding utf8NoBOM

Write-Host $crosscheckMarker
Write-Host "EVAVO_AUTHORITY_PEER_EXCHANGE_CROSSCHECK_ACCEPTANCE=PASS target_sha=$($targetState.sha) lab_sha=$($labState.sha) receipt=$acceptancePath"
