[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$TargetRepoRoot,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-fA-F]{40}$')]
    [string]$ExpectedTargetSha,

    [string]$EmitterRelativePath = 'authority/scripts/emit_peer_exchange_evidence.mjs',

    [string]$OutputRoot = ''
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$labRoot = (Resolve-Path (Join-Path $scriptRoot '..')).Path
$targetRoot = (Resolve-Path $TargetRepoRoot).Path
$expectedSha = $ExpectedTargetSha.ToLowerInvariant()

$git = (Get-Command git -ErrorAction Stop).Source
$node = (Get-Command node -ErrorAction Stop).Source
$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
if ($null -eq $pythonCommand) { $pythonCommand = Get-Command py -ErrorAction Stop }
$python = $pythonCommand.Source

$head = (& $git -C $targetRoot rev-parse HEAD).Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $head -ne $expectedSha) {
    throw "Target HEAD mismatch. Expected $expectedSha, found $head"
}
$status = @(& $git -C $targetRoot status --porcelain=v1 --untracked-files=all)
if ($LASTEXITCODE -ne 0 -or $status.Count -ne 0) {
    throw 'Target repository must be clean before authority peer-exchange acceptance.'
}

$emitter = Join-Path $targetRoot $EmitterRelativePath
if (-not (Test-Path -LiteralPath $emitter -PathType Leaf)) {
    throw "Authority peer-exchange emitter not found: $EmitterRelativePath"
}

if ([string]::IsNullOrWhiteSpace($OutputRoot)) {
    $OutputRoot = Join-Path ([System.IO.Path]::GetTempPath()) 'evavo-authority-peer-exchange'
}
[System.IO.Directory]::CreateDirectory($OutputRoot) | Out-Null
$runId = [DateTimeOffset]::UtcNow.ToString('yyyyMMddTHHmmssfffZ') + '-' + $head.Substring(0, 12)
$runRoot = Join-Path $OutputRoot $runId
[System.IO.Directory]::CreateDirectory($runRoot) | Out-Null
$receiptPath = Join-Path $runRoot 'authority-peer-exchange.json'
$emitterStderr = Join-Path $runRoot 'emitter.stderr.txt'
$verifierStdout = Join-Path $runRoot 'verifier.stdout.txt'
$verifierStderr = Join-Path $runRoot 'verifier.stderr.txt'

Push-Location $targetRoot
try {
    & $node $emitter 1> $receiptPath 2> $emitterStderr
    $emitterExit = $LASTEXITCODE
} finally {
    Pop-Location
}
$emitterLog = Get-Content -LiteralPath $emitterStderr -Raw
if ($emitterExit -ne 0 -or $emitterLog -notmatch '(?m)^EVAVO_AUTHORITY_PEER_EXCHANGE_RECEIPT=PASS\s*$') {
    throw "Authority peer-exchange emitter failed. Exit=$emitterExit"
}

$previousPythonPath = $env:PYTHONPATH
try {
    $srcPath = Join-Path $labRoot 'src'
    if ([string]::IsNullOrWhiteSpace($previousPythonPath)) {
        $env:PYTHONPATH = $srcPath
    } else {
        $env:PYTHONPATH = $srcPath + [System.IO.Path]::PathSeparator + $previousPythonPath
    }
    Push-Location $labRoot
    try {
        if ([System.IO.Path]::GetFileNameWithoutExtension($python).ToLowerInvariant() -eq 'py') {
            & $python -3 -m godot_game_test_lab.authority_peer_exchange $receiptPath 1> $verifierStdout 2> $verifierStderr
        } else {
            & $python -m godot_game_test_lab.authority_peer_exchange $receiptPath 1> $verifierStdout 2> $verifierStderr
        }
        $verifyExit = $LASTEXITCODE
    } finally {
        Pop-Location
    }
} finally {
    $env:PYTHONPATH = $previousPythonPath
}
$verifyLog = Get-Content -LiteralPath $verifierStdout -Raw
if ($verifyExit -ne 0 -or $verifyLog -notmatch '(?m)^EVAVO_AUTHORITY_PEER_EXCHANGE=PASS roles=\d+\s*$') {
    throw "Test Lab authority peer-exchange verifier failed. Exit=$verifyExit"
}

$finalHead = (& $git -C $targetRoot rev-parse HEAD).Trim().ToLowerInvariant()
$finalStatus = @(& $git -C $targetRoot status --porcelain=v1 --untracked-files=all)
if ($LASTEXITCODE -ne 0 -or $finalHead -ne $expectedSha -or $finalStatus.Count -ne 0) {
    throw 'Target repository changed during authority peer-exchange acceptance.'
}

$receiptHash = (Get-FileHash -LiteralPath $receiptPath -Algorithm SHA256).Hash.ToLowerInvariant()
$manifest = [ordered]@{
    schemaVersion = '1.0'
    kind = 'evavo-authority-peer-exchange-acceptance'
    status = 'passed'
    targetRepoRoot = $targetRoot
    targetSha = $expectedSha
    emitterRelativePath = $EmitterRelativePath.Replace('\', '/')
    receipt = [ordered]@{
        path = 'authority-peer-exchange.json'
        sha256 = $receiptHash
        bytes = (Get-Item -LiteralPath $receiptPath).Length
    }
    emitterMarker = 'EVAVO_AUTHORITY_PEER_EXCHANGE_RECEIPT=PASS'
    verifierMarker = 'EVAVO_AUTHORITY_PEER_EXCHANGE=PASS'
    targetUnchanged = $true
}
$manifestPath = Join-Path $runRoot 'acceptance.json'
$manifestJson = $manifest | ConvertTo-Json -Depth 8
[System.IO.File]::WriteAllText($manifestPath, $manifestJson + "`n", (New-Object System.Text.UTF8Encoding($false)))

Write-Output "EVAVO_AUTHORITY_PEER_EXCHANGE_ACCEPTANCE=PASS target_sha=$expectedSha"
Write-Output $manifestPath
