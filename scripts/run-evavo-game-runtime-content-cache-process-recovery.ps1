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
    $ArtifactRoot = Join-Path $TestLabRoot "artifacts\evavo-game-runtime-content-cache-process-recovery"
}
$ArtifactRoot = [System.IO.Path]::GetFullPath($ArtifactRoot)
New-Item -ItemType Directory -Path $ArtifactRoot -Force | Out-Null

if (-not $GodotPath -or -not (Test-Path -LiteralPath $GodotPath)) {
    throw "GodotPath/GODOT_BIN must point to a Godot 4.6.2 executable."
}

function Invoke-Scenario {
    param(
        [Parameter(Mandatory = $true)][string]$Id,
        [Parameter(Mandatory = $true)][scriptblock]$Command,
        [string]$PassMarker = "",
        [string]$RuntimeReceiptPath = ""
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
        runtime_receipt_path = $RuntimeReceiptPath
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
if ($LASTEXITCODE -ne 0 -or $RuntimeSha -notmatch '^[0-9a-f]{40}$') {
    throw "Unable to resolve runtime Git SHA."
}
$TestLabSha = (git -C $TestLabRoot rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $TestLabSha -notmatch '^[0-9a-f]{40}$') {
    throw "Unable to resolve Test Lab Git SHA."
}
$GodotVersion = (& $GodotPath --version 2>&1 | Select-Object -First 1).ToString().Trim()
if ($GodotVersion -notmatch '^4\.6\.2') {
    throw "Expected Godot 4.6.2, observed: $GodotVersion"
}

$Scenarios = @()
$Scenarios += Invoke-Scenario `
    -Id "dependency_free_validator" `
    -Command {
        python (Join-Path $RuntimeRoot "tests\validate_content_cache_process_recovery.py")
    }
$Scenarios += Invoke-Scenario `
    -Id "headless_import_parse" `
    -Command {
        & $GodotPath --headless --editor --path $RuntimeRoot --quit
    }
$Scenarios += Invoke-Scenario `
    -Id "disk_host_behavior" `
    -PassMarker "EVAVO_DISK_CONTENT_PACKAGE_CACHE_TEST=PASS" `
    -Command {
        & $GodotPath `
            --headless `
            --path $RuntimeRoot `
            --script (Join-Path $RuntimeRoot "tests\godot\test_disk_content_package_cache.gd")
    }

$RuntimeMatrixRoot = Join-Path $ArtifactRoot "runtime-process-matrix"
$RuntimeReceiptPath = Join-Path $RuntimeMatrixRoot "receipt.json"
$Scenarios += Invoke-Scenario `
    -Id "actual_process_kill_matrix" `
    -PassMarker "EVAVO content cache process-recovery suite passed." `
    -RuntimeReceiptPath $RuntimeReceiptPath `
    -Command {
        & (Join-Path $RuntimeRoot "scripts\run-content-cache-process-recovery-smoke.ps1") `
            -GodotPath $GodotPath `
            -ArtifactRoot $RuntimeMatrixRoot `
            -SkipStaticValidation `
            -SkipImport
    }

if (-not (Test-Path -LiteralPath $RuntimeReceiptPath)) {
    throw "Runtime process-recovery receipt was not produced."
}
$RuntimeReceipt = Get-Content -LiteralPath $RuntimeReceiptPath -Raw | ConvertFrom-Json
if (-not [bool]$RuntimeReceipt.passed) {
    throw "Runtime process-recovery matrix receipt did not pass."
}
if ([string]$RuntimeReceipt.runtime_sha -ne $RuntimeSha) {
    throw "Runtime process-recovery receipt SHA did not match the tested checkout."
}
if ([bool]$RuntimeReceipt.claims.process_kill_is_simulated) {
    throw "Runtime process-recovery receipt incorrectly described process kill as simulated."
}
if ([bool]$RuntimeReceipt.claims.headless_editor_process_is_exported_build) {
    throw "Runtime process-recovery receipt incorrectly claimed exported-build evidence."
}

$Passed = (
    -not [bool]($Scenarios | Where-Object { -not $_.passed })
    -and $RuntimeStatus.Count -eq 0
    -and $TestLabStatus.Count -eq 0
)
$Receipt = [ordered]@{
    version = 1
    suite_id = "evavo_game_runtime_content_cache_process_recovery"
    runtime_sha = $RuntimeSha
    test_lab_sha = $TestLabSha
    godot_version = $GodotVersion
    runtime_clean = ($RuntimeStatus.Count -eq 0)
    test_lab_clean = ($TestLabStatus.Count -eq 0)
    scenarios = $Scenarios
    passed = $Passed
    claims = [ordered]@{
        process_kill_is_simulated = $false
        headless_editor_process_is_exported_build = $false
        reconciliation_grants_content_availability = $false
        reconciliation_grants_scene_activation = $false
        reconciliation_grants_simulation_authority = $false
    }
}
$ReceiptPath = Join-Path $ArtifactRoot "receipt.json"
$Receipt | ConvertTo-Json -Depth 16 | Set-Content -LiteralPath $ReceiptPath -Encoding utf8
Write-Host "Receipt: $ReceiptPath"

if (-not $Passed) {
    throw "EVAVO Game Runtime content cache process recovery suite failed."
}
Write-Host "EVAVO Game Runtime content cache process recovery suite passed."
