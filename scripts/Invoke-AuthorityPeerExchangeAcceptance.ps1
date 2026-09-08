[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$TargetRepoRoot,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-fA-F]{40}$')]
    [string]$ExpectedTargetSha,

    [string]$ExpectedLabSha = '',

    [string]$EmitterRelativePath = 'authority/scripts/emit_peer_exchange_evidence.mjs',

    [string]$OutputRoot = ''
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

function ConvertTo-WindowsCommandLineArgument {
    param([AllowEmptyString()][string]$Value)

    if ($Value.Length -gt 0 -and $Value -notmatch '[\s"]') {
        return $Value
    }

    $builder = New-Object System.Text.StringBuilder
    [void]$builder.Append([char]34)
    $slashes = 0
    foreach ($character in $Value.ToCharArray()) {
        if ($character -eq '\') {
            $slashes += 1
            continue
        }
        if ($character -eq [char]34) {
            if ($slashes -gt 0) { [void]$builder.Append(('\' * ($slashes * 2))) }
            [void]$builder.Append('\"')
            $slashes = 0
            continue
        }
        if ($slashes -gt 0) {
            [void]$builder.Append(('\' * $slashes))
            $slashes = 0
        }
        [void]$builder.Append($character)
    }
    if ($slashes -gt 0) { [void]$builder.Append(('\' * ($slashes * 2))) }
    [void]$builder.Append([char]34)
    return $builder.ToString()
}

function Invoke-CapturedNativeProcess {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [Parameter(Mandatory = $true)][string]$StdoutPath,
        [Parameter(Mandatory = $true)][string]$StderrPath
    )

    $start = New-Object System.Diagnostics.ProcessStartInfo
    $start.FileName = $FilePath
    $start.Arguments = (($Arguments | ForEach-Object { ConvertTo-WindowsCommandLineArgument $_ }) -join ' ')
    $start.WorkingDirectory = $WorkingDirectory
    $start.UseShellExecute = $false
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    $start.CreateNoWindow = $true

    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $start
    if (-not $process.Start()) { throw "Failed to start native process: $FilePath" }
    $stdoutTask = $process.StandardOutput.ReadToEndAsync()
    $stderrTask = $process.StandardError.ReadToEndAsync()
    $process.WaitForExit()
    $stdout = $stdoutTask.GetAwaiter().GetResult()
    $stderr = $stderrTask.GetAwaiter().GetResult()
    $exitCode = $process.ExitCode
    $process.Dispose()

    $utf8 = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($StdoutPath, $stdout, $utf8)
    [System.IO.File]::WriteAllText($StderrPath, $stderr, $utf8)
    return $exitCode
}

function Get-RepositoryState {
    param(
        [Parameter(Mandatory = $true)][string]$GitPath,
        [Parameter(Mandatory = $true)][string]$RepositoryRoot,
        [Parameter(Mandatory = $true)][string]$Name
    )

    $sha = (& $GitPath -C $RepositoryRoot rev-parse HEAD).Trim().ToLowerInvariant()
    if ($LASTEXITCODE -ne 0 -or $sha -notmatch '^[0-9a-f]{40}$') {
        throw "Could not resolve exact SHA for $Name."
    }
    $branch = (& $GitPath -C $RepositoryRoot branch --show-current).Trim()
    if ($LASTEXITCODE -ne 0 -or $branch -cne 'main') {
        throw "$Name authority acceptance requires branch main. Found: $branch"
    }
    $status = @(& $GitPath -C $RepositoryRoot status --porcelain=v1 --untracked-files=all)
    if ($LASTEXITCODE -ne 0) {
        throw "Could not inspect working tree state for $Name."
    }
    return [ordered]@{
        sha = $sha
        branch = $branch
        dirty = ($status.Count -ne 0)
    }
}

function Get-ExactLineCount {
    param(
        [Parameter(Mandatory = $true)][string]$Text,
        [Parameter(Mandatory = $true)][string]$ExpectedLine
    )
    return @($Text -split "`r?`n" | Where-Object { $_ -ceq $ExpectedLine }).Count
}

function Write-Utf8CreateOnly {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Text
    )
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    $stream = New-Object System.IO.FileStream($Path, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
    try {
        $bytes = $utf8.GetBytes($Text)
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush($true)
    } finally {
        $stream.Dispose()
    }
}

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$labRoot = (Resolve-Path (Join-Path $scriptRoot '..')).Path
$targetRoot = (Resolve-Path $TargetRepoRoot).Path
$expectedSha = $ExpectedTargetSha.ToLowerInvariant()
if ($ExpectedLabSha -and $ExpectedLabSha -notmatch '^[0-9a-fA-F]{40}$') {
    throw 'ExpectedLabSha must be an exact 40-character SHA when supplied.'
}
$expectedLab = if ($ExpectedLabSha) { $ExpectedLabSha.ToLowerInvariant() } else { '' }

$git = (Get-Command git -ErrorAction Stop).Source
$node = (Get-Command node -ErrorAction Stop).Source
$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
if ($null -eq $pythonCommand) { $pythonCommand = Get-Command py -ErrorAction Stop }
$python = $pythonCommand.Source

$targetInitial = Get-RepositoryState -GitPath $git -RepositoryRoot $targetRoot -Name 'Target repository'
if ($targetInitial.sha -ne $expectedSha) {
    throw "Target HEAD mismatch. Expected $expectedSha, found $($targetInitial.sha)"
}
if ($targetInitial.dirty) {
    throw 'Target repository must be clean before authority peer-exchange acceptance.'
}
$labInitial = Get-RepositoryState -GitPath $git -RepositoryRoot $labRoot -Name 'godot-game-test-lab'
if ($labInitial.dirty) {
    throw 'godot-game-test-lab must be clean before authority peer-exchange acceptance.'
}
if ($expectedLab -and $labInitial.sha -ne $expectedLab) {
    throw "Test Lab HEAD mismatch. Expected $expectedLab, found $($labInitial.sha)"
}

$nodeVersion = (& $node --version 2>&1 | Select-Object -First 1).ToString().Trim()
if ($LASTEXITCODE -ne 0 -or $nodeVersion -notmatch '^v(?<Major>\d+)\.(?<Minor>\d+)\.(?<Patch>\d+)$') {
    throw "Could not resolve a stable Node.js version. Found: $nodeVersion"
}
if ([int]$Matches.Major -lt 20) {
    throw "Authority peer-exchange acceptance requires Node.js 20 or newer. Found: $nodeVersion"
}

$emitter = Join-Path $targetRoot $EmitterRelativePath
if (-not (Test-Path -LiteralPath $emitter -PathType Leaf)) {
    throw "Authority peer-exchange emitter not found: $EmitterRelativePath"
}

if ([string]::IsNullOrWhiteSpace($OutputRoot)) {
    $OutputRoot = Join-Path ([System.IO.Path]::GetTempPath()) 'evavo-authority-peer-exchange'
}
[System.IO.Directory]::CreateDirectory($OutputRoot) | Out-Null
$runId = [DateTimeOffset]::UtcNow.ToString('yyyyMMddTHHmmssfffZ') + '-' + $expectedSha.Substring(0, 12) + '-' + ([Guid]::NewGuid().ToString('N').Substring(0, 8))
$runRoot = Join-Path $OutputRoot $runId
if (Test-Path -LiteralPath $runRoot) {
    throw "Authority peer-exchange run root already exists: $runRoot"
}
[System.IO.Directory]::CreateDirectory($runRoot) | Out-Null
$receiptPath = Join-Path $runRoot 'authority-peer-exchange.json'
$emitterStderr = Join-Path $runRoot 'emitter.stderr.txt'
$verifierStdout = Join-Path $runRoot 'verifier.stdout.txt'
$verifierStderr = Join-Path $runRoot 'verifier.stderr.txt'

$emitterExit = Invoke-CapturedNativeProcess -FilePath $node -Arguments @($emitter) -WorkingDirectory $targetRoot -StdoutPath $receiptPath -StderrPath $emitterStderr
$emitterLog = [System.IO.File]::ReadAllText($emitterStderr, [System.Text.Encoding]::UTF8)
$emitterMarker = 'EVAVO_AUTHORITY_PEER_EXCHANGE_RECEIPT=PASS'
$emitterMarkerCount = Get-ExactLineCount -Text $emitterLog -ExpectedLine $emitterMarker
if ($emitterExit -ne 0 -or $emitterMarkerCount -ne 1 -or $emitterLog -match '(?m)^EVAVO_AUTHORITY_PEER_EXCHANGE_RECEIPT=FAIL') {
    throw "Authority peer-exchange emitter failed or emitted ambiguous evidence. Exit=$emitterExit MarkerCount=$emitterMarkerCount"
}

$previousPythonPath = $env:PYTHONPATH
try {
    $srcPath = Join-Path $labRoot 'src'
    if ([string]::IsNullOrWhiteSpace($previousPythonPath)) {
        $env:PYTHONPATH = $srcPath
    } else {
        $env:PYTHONPATH = $srcPath + [System.IO.Path]::PathSeparator + $previousPythonPath
    }
    $pythonArguments = @('-m', 'godot_game_test_lab.authority_peer_exchange', $receiptPath)
    if ([System.IO.Path]::GetFileNameWithoutExtension($python).ToLowerInvariant() -eq 'py') {
        $pythonArguments = @('-3') + $pythonArguments
    }
    $verifyExit = Invoke-CapturedNativeProcess -FilePath $python -Arguments $pythonArguments -WorkingDirectory $labRoot -StdoutPath $verifierStdout -StderrPath $verifierStderr
} finally {
    $env:PYTHONPATH = $previousPythonPath
}
$verifyLog = [System.IO.File]::ReadAllText($verifierStdout, [System.Text.Encoding]::UTF8)
$verifyLines = @($verifyLog -split "`r?`n" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
$verifyMarkerLines = @($verifyLines | Where-Object { $_ -match '^EVAVO_AUTHORITY_PEER_EXCHANGE=PASS roles=\d+$' })
$resultLines = @($verifyLines | Where-Object { $_ -notmatch '^EVAVO_AUTHORITY_PEER_EXCHANGE=' })
if ($verifyExit -ne 0 -or $verifyMarkerLines.Count -ne 1 -or $resultLines.Count -ne 1) {
    throw "Test Lab authority peer-exchange verifier failed or emitted ambiguous evidence. Exit=$verifyExit MarkerCount=$($verifyMarkerLines.Count) ResultCount=$($resultLines.Count)"
}
try {
    $verifiedResult = $resultLines[0] | ConvertFrom-Json
} catch {
    throw 'Test Lab authority peer-exchange verifier did not emit one valid structured result.'
}
if ($verifiedResult.proven -ne $true -or $verifiedResult.privacySafe -ne $true -or $verifiedResult.stablePeerMapping -ne $true) {
    throw 'Test Lab authority peer-exchange structured result did not prove the required lifecycle guarantees.'
}

$targetFinal = Get-RepositoryState -GitPath $git -RepositoryRoot $targetRoot -Name 'Target repository'
$labFinal = Get-RepositoryState -GitPath $git -RepositoryRoot $labRoot -Name 'godot-game-test-lab'
if ($targetFinal.sha -ne $targetInitial.sha -or $targetFinal.dirty -or $targetFinal.branch -cne $targetInitial.branch) {
    throw 'Target repository changed during authority peer-exchange acceptance.'
}
if ($labFinal.sha -ne $labInitial.sha -or $labFinal.dirty -or $labFinal.branch -cne $labInitial.branch) {
    throw 'godot-game-test-lab changed during authority peer-exchange acceptance.'
}

$receiptHash = (Get-FileHash -LiteralPath $receiptPath -Algorithm SHA256).Hash.ToLowerInvariant()
$manifest = [ordered]@{
    schemaVersion = '2.0'
    kind = 'evavo-authority-peer-exchange-acceptance'
    status = 'passed'
    runId = $runId
    testLab = [ordered]@{
        sha = $labInitial.sha
        branch = $labInitial.branch
        dirty = $false
    }
    target = [ordered]@{
        sha = $targetInitial.sha
        branch = $targetInitial.branch
        dirty = $false
    }
    nodeVersion = $nodeVersion
    emitter = [ordered]@{
        relativePath = $EmitterRelativePath.Replace('\', '/')
        marker = $emitterMarker
        markerOccurrences = $emitterMarkerCount
    }
    receipt = [ordered]@{
        path = 'authority-peer-exchange.json'
        sha256 = $receiptHash
        bytes = (Get-Item -LiteralPath $receiptPath).Length
    }
    verifier = [ordered]@{
        marker = [string]$verifyMarkerLines[0]
        markerOccurrences = $verifyMarkerLines.Count
        proven = [bool]$verifiedResult.proven
        privacySafe = [bool]$verifiedResult.privacySafe
        stablePeerMapping = [bool]$verifiedResult.stablePeerMapping
        requiredRoleCount = [int]$verifiedResult.requiredRoleCount
        gameId = [string]$verifiedResult.gameId
        authority = [string]$verifiedResult.authority
        protocol = [string]$verifiedResult.protocol
        sessionId = [string]$verifiedResult.sessionId
    }
    sourceUnchanged = $true
}
$manifestPath = Join-Path $runRoot 'acceptance.json'
$manifestJson = $manifest | ConvertTo-Json -Depth 10
Write-Utf8CreateOnly -Path $manifestPath -Text ($manifestJson + "`n")

Write-Output "EVAVO_AUTHORITY_PEER_EXCHANGE_ACCEPTANCE=PASS target_sha=$expectedSha lab_sha=$($labInitial.sha)"
Write-Output $manifestPath
