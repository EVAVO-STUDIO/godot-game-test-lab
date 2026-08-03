[CmdletBinding()]
param(
    [string]$LabRoot = "C:\GitRepos\godot-game-test-lab",
    [Alias("TargetRoot")]
    [string[]]$AllowedTargetRoots = @("C:\GitRepos"),
    [string]$EvidenceRoot = "C:\GodotLabEvidence",
    [string]$EngineRoot = "",
    [string]$TaskName = "EVAVO Godot Game Test Lab MCP",
    [ValidateRange(1, 65535)]
    [int]$Port = 8765,
    [ValidateRange(1, 120)]
    [int]$StopTimeoutSeconds = 15,
    [switch]$EngineOffline,
    [switch]$StartNow
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Test-IsWithinPath {
    param([string]$Candidate, [string]$Parent)
    $candidateFull = [IO.Path]::GetFullPath($Candidate).TrimEnd('\', '/')
    $parentFull = [IO.Path]::GetFullPath($Parent).TrimEnd('\', '/')
    return (
        $candidateFull.Equals($parentFull, [StringComparison]::OrdinalIgnoreCase) -or
        $candidateFull.StartsWith(
            $parentFull + [IO.Path]::DirectorySeparatorChar,
            [StringComparison]::OrdinalIgnoreCase
        )
    )
}

function Test-PathsOverlap {
    param([string]$Left, [string]$Right)
    return (
        (Test-IsWithinPath -Candidate $Left -Parent $Right) -or
        (Test-IsWithinPath -Candidate $Right -Parent $Left)
    )
}

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

function Assert-NoReparsePointForCandidate {
    param([Parameter(Mandatory = $true)][string]$Path)
    $cursor = [IO.Path]::GetFullPath($Path)
    while (-not (Test-Path -LiteralPath $cursor)) {
        $parent = [IO.Directory]::GetParent($cursor)
        if ($null -eq $parent) {
            return
        }
        $cursor = $parent.FullName
    }
    Assert-NoReparsePoint -Path $cursor
}

function Test-LoopbackPort {
    param([int]$PortNumber, [int]$TimeoutMilliseconds = 500)
    $client = [Net.Sockets.TcpClient]::new()
    try {
        $task = $client.ConnectAsync("127.0.0.1", $PortNumber)
        return $task.Wait($TimeoutMilliseconds) -and $client.Connected
    }
    catch {
        return $false
    }
    finally {
        $client.Dispose()
    }
}

function Write-AtomicJson {
    param([string]$Path, [object]$Value)
    $temporary = "$Path.tmp-$PID-$([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds())"
    [IO.File]::WriteAllText(
        $temporary,
        ($Value | ConvertTo-Json -Depth 12) + [Environment]::NewLine,
        [Text.UTF8Encoding]::new($false)
    )
    Move-Item -LiteralPath $temporary -Destination $Path -Force
}

function ConvertTo-QuotedArgument {
    param([Parameter(Mandatory = $true)][string]$Value)
    if ($Value.Contains('"')) {
        throw "Scheduled-task arguments may not contain a quotation mark."
    }
    return '"' + $Value + '"'
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
    throw "Register-GodotLabMcpWorker.ps1 must run on Windows."
}
$resolvedLab = (Resolve-Path -LiteralPath $LabRoot).Path
Assert-NoReparsePoint -Path $resolvedLab
$startScript = Join-Path $resolvedLab "scripts\Start-GodotLabMcp.ps1"
if (-not (Test-Path -LiteralPath $startScript -PathType Leaf)) {
    throw "The MCP start script is missing: $startScript"
}
$python = Join-Path $resolvedLab ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Run scripts\Install-GodotLab.ps1 before registering the worker."
}
Assert-NoReparsePoint -Path $startScript
Assert-NoReparsePoint -Path $python

$labSha = Get-GitText -Root $resolvedLab -Arguments @(
    "rev-parse", "HEAD"
) -Label "Resolve Lab SHA"
if ($labSha -notmatch '^[0-9a-f]{40}$') {
    throw "The Lab checkout did not return an exact commit SHA."
}
$labStatus = Get-GitText -Root $resolvedLab -Arguments @(
    "status", "--porcelain=v1", "--untracked-files=all"
) -Label "Read complete Lab status"
if ($labStatus) {
    throw "The Lab checkout has tracked or untracked source changes."
}

if (-not $EngineRoot) {
    $localData = [Environment]::GetFolderPath("LocalApplicationData")
    $EngineRoot = Join-Path $localData "EVAVO\GodotGameTestLab\engines"
}

$candidateEvidence = [IO.Path]::GetFullPath($EvidenceRoot)
$candidateEngine = [IO.Path]::GetFullPath($EngineRoot)
Assert-NoReparsePointForCandidate -Path $candidateEvidence
Assert-NoReparsePointForCandidate -Path $candidateEngine

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
    throw "At least one allowed target root is required."
}

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

$configurationPath = Join-Path $resolvedEvidence "godot-lab-mcp-worker-config.json"
$configuration = [ordered]@{
    schemaVersion = "2.0"
    labRoot = $resolvedLab
    labSha = $labSha
    allowedTargetRoots = @($resolvedRoots)
    evidenceRoot = $resolvedEvidence
    engineRoot = $resolvedEngine
    hostAddress = "127.0.0.1"
    port = $Port
    requireInteractiveDesktop = $true
    autoProvisionEngines = -not [bool]$EngineOffline
}
Write-AtomicJson -Path $configurationPath -Value $configuration
$configurationSha256 = (
    Get-FileHash -LiteralPath $configurationPath -Algorithm SHA256
).Hash.ToLowerInvariant()

$existingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existingTask) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    $deadline = [DateTimeOffset]::UtcNow.AddSeconds($StopTimeoutSeconds)
    do {
        $state = (Get-ScheduledTask -TaskName $TaskName).State
        if ($state -ne "Running") {
            break
        }
        Start-Sleep -Milliseconds 250
    } while ([DateTimeOffset]::UtcNow -lt $deadline)
    if ((Get-ScheduledTask -TaskName $TaskName).State -eq "Running") {
        throw "The previous MCP worker task did not stop within the timeout."
    }
}
if (Test-LoopbackPort -PortNumber $Port) {
    throw (
        "Loopback port $Port is already occupied after stopping the managed task. " +
        "Refusing to mistake an unrelated listener for the Godot Lab MCP worker."
    )
}

$powerShell = (Get-Command pwsh -ErrorAction SilentlyContinue).Source
if (-not $powerShell) {
    $powerShell = (Get-Command powershell.exe -ErrorAction Stop).Source
}
$argumentLine = @(
    "-NoLogo",
    "-NoProfile",
    "-NonInteractive",
    "-ExecutionPolicy", "Bypass",
    "-File", (ConvertTo-QuotedArgument -Value $startScript),
    "-ConfigurationPath", (ConvertTo-QuotedArgument -Value $configurationPath)
) -join " "
$action = New-ScheduledTaskAction -Execute $powerShell -Argument $argumentLine
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$userId = if ($env:USERDOMAIN) {
    "$env:USERDOMAIN\$env:USERNAME"
}
else {
    $env:USERNAME
}
$principal = New-ScheduledTaskPrincipal `
    -UserId $userId `
    -LogonType Interactive `
    -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Days 3650)
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description "Loopback-only EVAVO Godot QA MCP worker for the logged-in user." `
    -Force | Out-Null

$receipt = [ordered]@{
    schemaVersion = "2.0"
    status = "registered"
    taskName = $TaskName
    user = $userId
    labRoot = $resolvedLab
    labSha = $labSha
    allowedTargetRoots = @($resolvedRoots)
    engineRoot = $resolvedEngine
    evidenceRoot = $resolvedEvidence
    configurationPath = $configurationPath
    configurationSha256 = $configurationSha256
    endpoint = "http://127.0.0.1:$Port/mcp"
    autoProvisionEngines = -not [bool]$EngineOffline
    registeredAt = [DateTimeOffset]::UtcNow.ToString("o")
}
$receiptPath = Join-Path $resolvedEvidence "godot-lab-mcp-worker.json"
Write-AtomicJson -Path $receiptPath -Value $receipt
if ($StartNow) {
    Start-ScheduledTask -TaskName $TaskName
}
Write-Host "[godot-lab] Registered '$TaskName'. Receipt: $receiptPath"
