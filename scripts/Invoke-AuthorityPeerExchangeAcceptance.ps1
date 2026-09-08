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

$emitterExit = Invoke-CapturedNativeProcess -FilePath $node -Arguments @($emitter) -WorkingDirectory $targetRoot -StdoutPath $receiptPath -StderrPath $emitterStderr
$emitterLog = [System.IO.File]::ReadAllText($emitterStderr, [System.Text.Encoding]::UTF8)
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
    $pythonArguments = @('-m', 'godot_game_test_lab.authority_peer_exchange', $receiptPath)
    if ([System.IO.Path]::GetFileNameWithoutExtension($python).ToLowerInvariant() -eq 'py') {
        $pythonArguments = @('-3') + $pythonArguments
    }
    $verifyExit = Invoke-CapturedNativeProcess -FilePath $python -Arguments $pythonArguments -WorkingDirectory $labRoot -StdoutPath $verifierStdout -StderrPath $verifierStderr
} finally {
    $env:PYTHONPATH = $previousPythonPath
}
$verifyLog = [System.IO.File]::ReadAllText($verifierStdout, [System.Text.Encoding]::UTF8)
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
