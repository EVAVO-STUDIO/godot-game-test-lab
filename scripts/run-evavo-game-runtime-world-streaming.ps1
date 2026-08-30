param(
    [string]$GodotPath = $env:GODOT_BIN,
    [string]$RuntimeRepo = "C:\GitRepos\evavo-game-runtime",
    [string]$OutputRoot = "C:\GodotLabEvidence\evavo-game-runtime\world-streaming",
    [switch]$AllowDirty
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$LabRoot = Split-Path -Parent $PSScriptRoot
$ProfilePath = Join-Path $LabRoot "config\evavo-game-runtime-world-streaming.v1.json"
$ContractPath = Join-Path $LabRoot "contracts\evavo-game-runtime-world-streaming-receipt-v1.json"

if ([string]::IsNullOrWhiteSpace($GodotPath) -or -not (Test-Path -LiteralPath $GodotPath -PathType Leaf)) {
    throw "GodotPath is required and must point to a Godot executable."
}
if (-not (Test-Path -LiteralPath (Join-Path $RuntimeRepo "project.godot") -PathType Leaf)) {
    throw "EVAVO Game Runtime project root not found: $RuntimeRepo"
}
if (-not (Test-Path -LiteralPath $ProfilePath -PathType Leaf)) {
    throw "World streaming Test Lab profile not found: $ProfilePath"
}
if (-not (Test-Path -LiteralPath $ContractPath -PathType Leaf)) {
    throw "World streaming receipt contract not found: $ContractPath"
}

$Profile = Get-Content -LiteralPath $ProfilePath -Raw | ConvertFrom-Json
$RuntimeSha = (& git -C $RuntimeRepo rev-parse HEAD 2>&1 | Select-Object -First 1).Trim()
if ($LASTEXITCODE -ne 0 -or $RuntimeSha -notmatch '^[0-9a-f]{40}$') {
    throw "Could not resolve the EVAVO Game Runtime commit SHA."
}
$Dirty = @(& git -C $RuntimeRepo status --porcelain=v1 2>&1)
if (-not $AllowDirty -and $Dirty.Count -gt 0) {
    throw "EVAVO Game Runtime must be clean for an exact-SHA Test Lab receipt."
}

$RunId = Get-Date -Format "yyyyMMdd-HHmmss"
$OutputDir = Join-Path $OutputRoot $RunId
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

$SourceLog = Join-Path $OutputDir "source-validation.log"
$ImportLog = Join-Path $OutputDir "godot-import.log"
$SmokeLog = Join-Path $OutputDir "world-streaming-smoke.log"
$ReceiptPath = Join-Path $OutputDir "receipt.json"

$Issues = [System.Collections.Generic.List[string]]::new()
$GodotVersion = (& $GodotPath --version 2>&1 | Select-Object -First 1).Trim()

$SourceLines = @(& python (Join-Path $RuntimeRepo "tests\validate_world_streaming.py") 2>&1 | ForEach-Object { [string]$_ })
$SourceExit = $LASTEXITCODE
$SourceLines | Set-Content -LiteralPath $SourceLog -Encoding utf8
if ($SourceExit -ne 0) {
    $Issues.Add("source_validation_failed")
}

$ImportLines = @(& $GodotPath --headless --editor --path $RuntimeRepo --quit 2>&1 | ForEach-Object { [string]$_ })
$ImportExit = $LASTEXITCODE
$ImportLines | Set-Content -LiteralPath $ImportLog -Encoding utf8
if ($ImportExit -ne 0) {
    $Issues.Add("godot_import_failed")
}

$Evidence = @{}
$SmokeExit = -1
if ($SourceExit -eq 0 -and $ImportExit -eq 0) {
    $ScriptPath = "res://" + ([string]$Profile.runtime_script).Replace('\', '/')
    $SmokeLines = @(& $GodotPath --headless --path $RuntimeRepo --script $ScriptPath 2>&1 | ForEach-Object { [string]$_ })
    $SmokeExit = $LASTEXITCODE
    $SmokeLines | Set-Content -LiteralPath $SmokeLog -Encoding utf8
    if ($SmokeExit -ne 0) {
        $Issues.Add("world_streaming_smoke_failed")
    }

    $MarkerPrefix = [string]$Profile.required_marker
    $Marker = $SmokeLines | Where-Object { $_ -like "$MarkerPrefix*" } | Select-Object -Last 1
    if (-not $Marker) {
        $Issues.Add("world_streaming_evidence_missing")
    }
    else {
        try {
            $EvidenceJson = $Marker.Substring($MarkerPrefix.Length)
            $Evidence = $EvidenceJson | ConvertFrom-Json -AsHashtable
        }
        catch {
            $Issues.Add("world_streaming_evidence_invalid_json")
        }
    }
}
else {
    "Smoke skipped because source validation or import failed." |
        Set-Content -LiteralPath $SmokeLog -Encoding utf8
}

if ($Evidence.Count -gt 0) {
    if ([string]$Evidence.packages.state -ne "ready") {
        $Issues.Add("content_delivery_not_ready")
    }
    $Memory = [double]$Evidence.streaming.memory_admitted_mb
    $Budget = [double]$Evidence.streaming.memory_budget_mb
    if ($Memory -gt $Budget) {
        $Issues.Add("streaming_memory_budget_exceeded")
    }
    if ([int]$Evidence.streaming.active_count -lt 1) {
        $Issues.Add("persistent_region_not_active")
    }
    $Committed = @($Evidence.handoffs.handoffs | Where-Object { [string]$_.state -eq "committed" })
    if ($Committed.Count -lt 1) {
        $Issues.Add("authority_handoff_not_committed")
    }
}

$Receipt = [ordered]@{
    version = 1
    generated_utc = [DateTime]::UtcNow.ToString("o")
    runtime_repo = (Resolve-Path -LiteralPath $RuntimeRepo).Path
    runtime_sha = $RuntimeSha
    runtime_dirty = ($Dirty.Count -gt 0)
    godot = $GodotVersion
    source_exit_code = $SourceExit
    import_exit_code = $ImportExit
    exit_code = $SmokeExit
    evidence = $Evidence
    stdout_path = $SmokeLog
    source_log_path = $SourceLog
    import_log_path = $ImportLog
    profile = $Profile
    issues = @($Issues)
}
$Receipt | ConvertTo-Json -Depth 40 | Set-Content -LiteralPath $ReceiptPath -Encoding utf8

if ($Issues.Count -gt 0) {
    throw "EVAVO world streaming Test Lab run failed: $($Issues -join ', '). Receipt: $ReceiptPath"
}

Write-Host "EVAVO world streaming Test Lab run passed."
Write-Host "Receipt: $ReceiptPath"
