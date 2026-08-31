param(
    [Parameter(Mandatory = $true)]
    [string]$RuntimeRepo,

    [string]$GodotPath = $env:GODOT_BIN,

    [string]$ArtifactRoot = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$TestLabRoot = Split-Path -Parent $PSScriptRoot
$RuntimeRoot = (Resolve-Path -LiteralPath $RuntimeRepo).Path
if (-not $ArtifactRoot) {
    $ArtifactRoot = Join-Path $TestLabRoot "artifacts\evavo-game-runtime-content-cache-crash-recovery"
}
$ArtifactRoot = [System.IO.Path]::GetFullPath($ArtifactRoot)
New-Item -ItemType Directory -Path $ArtifactRoot -Force | Out-Null

if (-not $GodotPath -or -not (Test-Path -LiteralPath $GodotPath)) {
    throw "GodotPath/GODOT_BIN must point to a Godot 4.6.2 executable."
}

function Invoke-Scenario {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Id,

        [Parameter(Mandatory = $true)]
        [scriptblock]$Command,

        [string]$PassMarker = ""
    )

    $LogPath = Join-Path $ArtifactRoot "$Id.log"
    $Lines = & $Command 2>&1 | ForEach-Object { [string]$_ }
    $ExitCode = $LASTEXITCODE
    $Lines | Set-Content -LiteralPath $LogPath -Encoding utf8
    $Lines | ForEach-Object { Write-Host $_ }
    $MarkerObserved = $true
    if ($PassMarker) {
        $MarkerObserved = [bool]($Lines | Where-Object { $_ -eq $PassMarker })
    }
    return [ordered]@{
        id = $Id
        passed = ($ExitCode -eq 0 -and $MarkerObserved)
        exit_code = $ExitCode
        log_path = $LogPath
        pass_marker_observed = $MarkerObserved
    }
}

$RuntimeStatus = @(git -C $RuntimeRoot status --porcelain)
if ($LASTEXITCODE -ne 0) {
    throw "Unable to read runtime Git status."
}
$TestLabStatus = @(git -C $TestLabRoot status --porcelain)
if ($LASTEXITCODE -ne 0) {
    throw "Unable to read Test Lab Git status."
}
$RuntimeSha = (git -C $RuntimeRoot rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0) {
    throw "Unable to resolve runtime Git SHA."
}
$TestLabSha = (git -C $TestLabRoot rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0) {
    throw "Unable to resolve Test Lab Git SHA."
}
$GodotVersion = (& $GodotPath --version 2>&1 | Select-Object -First 1).ToString().Trim()

$Scenarios = @()
$Scenarios += Invoke-Scenario `
    -Id "dependency_free_validator" `
    -Command {
        python (Join-Path $RuntimeRoot "tests\validate_content_cache_crash_recovery.py")
    }
$Scenarios += Invoke-Scenario `
    -Id "headless_import_parse" `
    -Command {
        & $GodotPath --headless --editor --path $RuntimeRoot --quit
    }
$Scenarios += Invoke-Scenario `
    -Id "fault_plan_behavior" `
    -PassMarker "EVAVO_CONTENT_CACHE_CRASH_RECOVERY_TEST=PASS" `
    -Command {
        & $GodotPath `
            --headless `
            --path $RuntimeRoot `
            --script (Join-Path $RuntimeRoot "tests\godot\test_content_cache_crash_recovery.gd")
    }

$Passed = -not [bool]($Scenarios | Where-Object { -not $_.passed })
$Receipt = [ordered]@{
    version = 1
    suite_id = "evavo_game_runtime_content_cache_crash_recovery"
    runtime_sha = $RuntimeSha
    test_lab_sha = $TestLabSha
    godot_version = $GodotVersion
    runtime_clean = ($RuntimeStatus.Count -eq 0)
    test_lab_clean = ($TestLabStatus.Count -eq 0)
    scenarios = $Scenarios
    passed = $Passed
    claims = [ordered]@{
        simulated_interrupt_is_process_crash = $false
        restart_receipt_grants_content_availability = $false
        reconciliation_grants_scene_activation = $false
        reconciliation_grants_simulation_authority = $false
    }
}
$ReceiptPath = Join-Path $ArtifactRoot "receipt.json"
$Receipt | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $ReceiptPath -Encoding utf8
Write-Host "Receipt: $ReceiptPath"

if (-not $Passed) {
    throw "EVAVO Game Runtime content cache crash recovery suite failed."
}

Write-Host "EVAVO Game Runtime content cache crash recovery suite passed."
