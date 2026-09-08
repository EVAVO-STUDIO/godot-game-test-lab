[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$AuthorityRepo = "",

    [Parameter(Mandatory = $false)]
    [string]$Emitter = "authority/scripts/emit_peer_exchange_evidence.mjs",

    [Parameter(Mandatory = $false)]
    [switch]$AllowDirty
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Resolve-CommandPath([string]$Name) {
    $command = Get-Command $Name -ErrorAction Stop
    if (-not $command.Source) {
        throw "Unable to resolve command path for $Name"
    }
    return $command.Source
}

function Resolve-Repository([string]$Requested) {
    if ($Requested) {
        return (Resolve-Path -LiteralPath $Requested).Path
    }
    $labRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
    $candidate = Join-Path (Split-Path -Parent $labRoot) "godot-462-galactic-cycle-online"
    if (-not (Test-Path -LiteralPath $candidate -PathType Container)) {
        throw "Authority repo not supplied and sibling Galactic Cycle repo was not found: $candidate"
    }
    return (Resolve-Path -LiteralPath $candidate).Path
}

function Invoke-CapturedProcess(
    [string]$FilePath,
    [string[]]$ArgumentList,
    [string]$WorkingDirectory
) {
    $start = [System.Diagnostics.ProcessStartInfo]::new()
    $start.FileName = $FilePath
    $start.WorkingDirectory = $WorkingDirectory
    $start.UseShellExecute = $false
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    foreach ($argument in $ArgumentList) {
        [void]$start.ArgumentList.Add($argument)
    }
    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $start
    if (-not $process.Start()) {
        throw "Failed to start process: $FilePath"
    }
    $stdout = $process.StandardOutput.ReadToEnd()
    $stderr = $process.StandardError.ReadToEnd()
    $process.WaitForExit()
    return [pscustomobject]@{
        ExitCode = $process.ExitCode
        Stdout = $stdout
        Stderr = $stderr
    }
}

$repo = Resolve-Repository $AuthorityRepo
$emitterPath = Join-Path $repo $Emitter
if (-not (Test-Path -LiteralPath $emitterPath -PathType Leaf)) {
    throw "Authority lifecycle emitter not found: $emitterPath"
}

$git = Resolve-CommandPath "git"
$node = Resolve-CommandPath "node"
$python = Resolve-CommandPath "python"

$sha = (& $git -C $repo rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $sha -notmatch '^[0-9a-f]{40}$') {
    throw "Unable to resolve exact authority repo SHA."
}
$branch = (& $git -C $repo branch --show-current).Trim()
if ($LASTEXITCODE -ne 0 -or -not $branch) {
    throw "Unable to resolve authority repo branch."
}
$dirtyLines = @(& $git -C $repo status --porcelain=v1 --untracked-files=all)
if ($LASTEXITCODE -ne 0) {
    throw "Unable to inspect authority repo dirty state."
}
$dirty = $dirtyLines.Count -gt 0
if ($dirty -and -not $AllowDirty) {
    throw "Authority repo is dirty. Commit or stash changes, or pass -AllowDirty for diagnostic-only verification."
}

$emission = Invoke-CapturedProcess -FilePath $node -ArgumentList @($emitterPath) -WorkingDirectory $repo
if ($emission.ExitCode -ne 0) {
    throw "Authority lifecycle emitter failed with exit code $($emission.ExitCode).`n$($emission.Stderr)"
}
if ($emission.Stderr -notmatch '(?m)^EVAVO_AUTHORITY_PEER_EXCHANGE_RECEIPT=PASS\s*$') {
    throw "Authority lifecycle emitter did not produce the exact PASS sentinel."
}

try {
    $parsed = $emission.Stdout | ConvertFrom-Json -Depth 32
} catch {
    throw "Authority lifecycle emitter stdout was not valid JSON."
}
if ($null -eq $parsed -or $parsed.kind -ne "evavo-authority-peer-exchange-lifecycle") {
    throw "Authority lifecycle emitter returned an unexpected receipt kind."
}

$temp = Join-Path ([System.IO.Path]::GetTempPath()) ("evavo-authority-peer-lifecycle-{0}.json" -f [Guid]::NewGuid().ToString("N"))
try {
    [System.IO.File]::WriteAllText($temp, $emission.Stdout, [System.Text.UTF8Encoding]::new($false))
    $verification = Invoke-CapturedProcess -FilePath $python -ArgumentList @(
        "-m",
        "godot_game_test_lab.authority_peer_lifecycle",
        "--evidence",
        $temp
    ) -WorkingDirectory ((Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path)
    if ($verification.ExitCode -ne 0) {
        throw "Test Lab authority lifecycle verification failed.`n$($verification.Stdout)`n$($verification.Stderr)"
    }
    $verified = $verification.Stdout | ConvertFrom-Json -Depth 32
    if ($verified.proven -ne $true -or $verified.authorityLifecycleProven -ne $true) {
        throw "Test Lab did not prove the authority lifecycle receipt."
    }
    if ($verified.transportProven -ne $false -or $verified.browserTransportProven -ne $false) {
        throw "Authority lifecycle verification escalated into a transport claim."
    }

    $summary = [ordered]@{
        schemaVersion = 1
        kind = "evavo-authority-peer-lifecycle-local-verification"
        authorityRepo = $repo
        authoritySha = $sha
        authorityBranch = $branch
        authorityDirty = $dirty
        emitter = $Emitter
        emitterSentinel = "EVAVO_AUTHORITY_PEER_EXCHANGE_RECEIPT=PASS"
        authorityLifecycleProven = $true
        reciprocalPeerSemanticsProven = [bool]$verified.reciprocalPeerSemanticsProven
        reconnectPeerSemanticsProven = [bool]$verified.reconnectPeerSemanticsProven
        transportProven = $false
        browserTransportProven = $false
    }
    $summary | ConvertTo-Json -Depth 8
    Write-Host "EVAVO_AUTHORITY_PEER_LIFECYCLE=PASS sha=$sha"
} finally {
    Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue
}
