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
if (-not $GodotPath -or -not (Test-Path -LiteralPath $GodotPath)) {
    throw "GodotPath/GODOT_BIN must point to a Godot 4.6.2 executable."
}

$PythonCommand = Get-Command python -ErrorAction SilentlyContinue
$PythonArguments = @()
if (-not $PythonCommand) {
    $PythonCommand = Get-Command py -ErrorAction SilentlyContinue
    $PythonArguments = @("-3")
}
if (-not $PythonCommand) {
    throw "Python 3 is required."
}
$PythonExecutable = $PythonCommand.Source

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

if (-not $ArtifactRoot) {
    $ArtifactRoot = Join-Path `
        $TestLabRoot `
        "artifacts\evavo-game-runtime-disk-cache-process-recovery"
}
$ArtifactRoot = [System.IO.Path]::GetFullPath($ArtifactRoot)
New-Item -ItemType Directory -Path $ArtifactRoot -Force | Out-Null

$GodotVersion = (& $GodotPath --version 2>&1 | Select-Object -First 1).ToString().Trim()
if ($GodotVersion -notmatch '^4\.6\.2') {
    throw "Expected Godot 4.6.2, observed: $GodotVersion"
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
        $MarkerObserved = [bool]($Lines | Where-Object {
            $_ -eq $PassMarker
        })
    }
    return [ordered]@{
        id = $Id
        passed = ($ExitCode -eq 0 -and $MarkerObserved)
        exit_code = $ExitCode
        log_path = $LogPath
        pass_marker_observed = $MarkerObserved
    }
}

$Scenarios = @()
$Scenarios += Invoke-Scenario `
    -Id "dependency_free_validators" `
    -PassMarker "EVAVO_DISK_CACHE_DEPENDENCY_VALIDATION=PASS" `
    -Command {
        & $PythonExecutable @PythonArguments `
            (Join-Path $TestLabRoot "scripts\validate-evavo-game-runtime-disk-cache-process-recovery.py") `
            --runtime-repo $RuntimeRoot
        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }
        & $PythonExecutable @PythonArguments `
            (Join-Path $RuntimeRoot "tests\validate_disk_content_package_cache_host.py")
        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }
        & $PythonExecutable @PythonArguments `
            (Join-Path $RuntimeRoot "tests\validate_disk_cache_process_recovery.py")
        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }
        Write-Output "EVAVO_DISK_CACHE_DEPENDENCY_VALIDATION=PASS"
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
            --script (Join-Path $RuntimeRoot "tests\godot\test_disk_content_package_cache_host.gd")
    }

$MatrixArtifactRoot = Join-Path $ArtifactRoot "process-matrix"
$Scenarios += Invoke-Scenario `
    -Id "actual_process_kill_matrix" `
    -PassMarker "EVAVO_DISK_CACHE_PROCESS_MATRIX=PASS" `
    -Command {
        & $PythonExecutable @PythonArguments `
            (Join-Path $RuntimeRoot "tests\run_disk_cache_process_recovery.py") `
            --godot $GodotPath `
            --repo $RuntimeRoot `
            --artifact-root $MatrixArtifactRoot
    }

$Passed = (
    -not [bool]($Scenarios | Where-Object { -not $_.passed })
    -and $RuntimeStatus.Count -eq 0
    -and $TestLabStatus.Count -eq 0
)
$Receipt = [ordered]@{
    version = 1
    suite_id = "evavo_game_runtime_disk_cache_process_recovery"
    runtime_sha = $RuntimeSha
    test_lab_sha = $TestLabSha
    godot_version = $GodotVersion
    runtime_clean = ($RuntimeStatus.Count -eq 0)
    test_lab_clean = ($TestLabStatus.Count -eq 0)
    scenarios = $Scenarios
    passed = $Passed
    claims = [ordered]@{
        checkpoint_marker_is_process_termination = $false
        process_restart_grants_content_availability = $false
        process_restart_grants_scene_activation = $false
        process_restart_grants_simulation_authority = $false
        headless_process_test_is_exported_device_test = $false
    }
}
$ReceiptPath = Join-Path $ArtifactRoot "receipt.json"
$Receipt | ConvertTo-Json -Depth 16 | Set-Content `
    -LiteralPath $ReceiptPath `
    -Encoding utf8
Write-Host "Receipt: $ReceiptPath"

if (-not $Passed) {
    throw "EVAVO Game Runtime disk cache process recovery suite failed."
}

Write-Host "EVAVO Game Runtime disk cache process recovery suite passed."
