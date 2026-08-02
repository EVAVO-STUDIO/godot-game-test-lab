[CmdletBinding()]
param(
    [string]$LabRoot = "C:\GitRepos\godot-game-test-lab",
    [string]$TargetRoot = "C:\GitRepos",
    [string]$EvidenceRoot = "C:\GodotLabEvidence",
    [string]$EngineRoot = "",
    [string]$TaskName = "EVAVO Godot Game Test Lab MCP",
    [int]$Port = 8765,
    [switch]$EngineOffline,
    [switch]$StartNow
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Test-IsWithinPath {
    param([string]$Candidate, [string]$Parent)
    $candidateFull = [System.IO.Path]::GetFullPath($Candidate).TrimEnd('\')
    $parentFull = [System.IO.Path]::GetFullPath($Parent).TrimEnd('\')
    return (
        $candidateFull -eq $parentFull -or
        $candidateFull.StartsWith(
            $parentFull + '\',
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

if ($Port -lt 1 -or $Port -gt 65535) {
    throw "Port must be between 1 and 65535."
}
$resolvedLab = (Resolve-Path -LiteralPath $LabRoot).Path
$resolvedTarget = (Resolve-Path -LiteralPath $TargetRoot).Path
$startScript = Join-Path $resolvedLab "scripts\Start-GodotLabMcp.ps1"
if (-not (Test-Path -LiteralPath $startScript -PathType Leaf)) {
    throw "The MCP start script is missing: $startScript"
}
$python = Join-Path $resolvedLab ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Run scripts\Install-GodotLab.ps1 before registering the worker."
}
if (-not $EngineRoot) {
    $localData = [Environment]::GetFolderPath("LocalApplicationData")
    $EngineRoot = Join-Path $localData "EVAVO\GodotGameTestLab\engines"
}
New-Item -ItemType Directory -Force -Path $EvidenceRoot, $EngineRoot | Out-Null
$resolvedEvidence = (Resolve-Path -LiteralPath $EvidenceRoot).Path
$resolvedEngine = (Resolve-Path -LiteralPath $EngineRoot).Path
foreach ($protected in @($resolvedLab, $resolvedEvidence, $resolvedTarget)) {
    if (Test-PathsOverlap -Left $resolvedEngine -Right $protected) {
        throw 'EngineRoot must remain disjoint from Lab, target and evidence roots.'
    }
}
if (Test-PathsOverlap -Left $resolvedEvidence -Right $resolvedLab) {
    throw 'EvidenceRoot must remain disjoint from the Lab checkout.'
}
if (Test-PathsOverlap -Left $resolvedEvidence -Right $resolvedTarget) {
    throw 'EvidenceRoot must remain disjoint from the target root.'
}

$powerShell = (Get-Command pwsh -ErrorAction SilentlyContinue).Source
if (-not $powerShell) {
    $powerShell = (Get-Command powershell.exe -ErrorAction Stop).Source
}
$arguments = @(
    "-NoLogo",
    "-NoProfile",
    "-NonInteractive",
    "-ExecutionPolicy", "Bypass",
    "-File", ('"' + $startScript + '"'),
    "-LabRoot", ('"' + $resolvedLab + '"'),
    "-AllowedTargetRoots", ('"' + $resolvedTarget + '"'),
    "-EvidenceRoot", ('"' + $resolvedEvidence + '"'),
    "-EngineRoot", ('"' + $resolvedEngine + '"'),
    "-Port", [string]$Port
)
if ($EngineOffline) {
    $arguments += "-EngineOffline"
}
$action = New-ScheduledTaskAction -Execute $powerShell -Argument ($arguments -join " ")
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
    schemaVersion = "1.0"
    status = "registered"
    taskName = $TaskName
    user = $userId
    labRoot = $resolvedLab
    targetRoot = $resolvedTarget
    engineRoot = $resolvedEngine
    evidenceRoot = $resolvedEvidence
    endpoint = "http://127.0.0.1:$Port/mcp"
    engineOffline = [bool]$EngineOffline
    registeredAt = [DateTimeOffset]::UtcNow.ToString("o")
}
$receiptPath = Join-Path $resolvedEvidence "godot-lab-mcp-worker.json"
[System.IO.File]::WriteAllText(
    $receiptPath,
    ($receipt | ConvertTo-Json -Depth 8) + [Environment]::NewLine,
    [System.Text.UTF8Encoding]::new($false)
)
if ($StartNow) {
    Start-ScheduledTask -TaskName $TaskName
}
Write-Host "[godot-lab] Registered '$TaskName'. Receipt: $receiptPath"
