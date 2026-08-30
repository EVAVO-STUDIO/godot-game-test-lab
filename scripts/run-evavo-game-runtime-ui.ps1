[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$GodotPath,

    [string]$RuntimeRepo = "",

    [string]$EvidenceRoot = "",

    [int]$TimeoutSeconds = 0,

    [string[]]$Scenario = @(),

    [switch]$SkipVideo,

    [switch]$RequireVideo,

    [switch]$RequireClean
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$LabRoot = Split-Path -Parent $PSScriptRoot
$MatrixPath = Join-Path $LabRoot "config\evavo-game-runtime-ui-matrix.v1.json"
$StaticValidator = Join-Path $LabRoot "scripts\validate-evavo-game-runtime-ui.py"
$ReceiptValidator = Join-Path $LabRoot "scripts\validate-evavo-game-runtime-ui-receipt.py"

function Resolve-FullPath {
    param([Parameter(Mandatory = $true)][string]$Path)
    return [System.IO.Path]::GetFullPath($Path)
}

function Test-PathInside {
    param(
        [Parameter(Mandatory = $true)][string]$Candidate,
        [Parameter(Mandatory = $true)][string]$Parent
    )
    $candidateFull = (Resolve-FullPath $Candidate).TrimEnd("\", "/")
    $parentFull = (Resolve-FullPath $Parent).TrimEnd("\", "/")
    if ($candidateFull.Equals($parentFull, [System.StringComparison]::OrdinalIgnoreCase)) {
        return $true
    }
    $prefix = $parentFull + [System.IO.Path]::DirectorySeparatorChar
    return $candidateFull.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)
}

function Get-GitIdentity {
    param([Parameter(Mandatory = $true)][string]$Repository)
    if (-not (Test-Path (Join-Path $Repository ".git"))) {
        throw "Not a Git repository: $Repository"
    }
    $sha = (& git -C $Repository rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or $sha -notmatch "^[0-9a-f]{40}$") {
        throw "Unable to resolve Git HEAD for $Repository"
    }
    $status = (& git -C $Repository status --porcelain=v1)
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to inspect Git status for $Repository"
    }
    return [pscustomobject]@{
        Sha = $sha
        Dirty = [bool]($status)
    }
}

function ConvertTo-NativeCommandLine {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)
    $encoded = foreach ($argument in $Arguments) {
        $value = [string]$argument
        if ($value -notmatch '[\s"]') {
            $value
            continue
        }
        '"' + $value.Replace('"', '\"') + '"'
    }
    return ($encoded -join " ")
}

function Invoke-BoundedProcess {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$StdoutPath,
        [Parameter(Mandatory = $true)][string]$StderrPath,
        [Parameter(Mandatory = $true)][int]$Timeout
    )

    New-Item -ItemType File -Force -Path $StdoutPath | Out-Null
    New-Item -ItemType File -Force -Path $StderrPath | Out-Null

    $commandLine = ConvertTo-NativeCommandLine $Arguments
    $watch = [System.Diagnostics.Stopwatch]::StartNew()
    $process = Start-Process `
        -FilePath $Executable `
        -ArgumentList $commandLine `
        -RedirectStandardOutput $StdoutPath `
        -RedirectStandardError $StderrPath `
        -PassThru

    $completed = $process.WaitForExit($Timeout * 1000)
    if (-not $completed) {
        try {
            Stop-Process -Id $process.Id -Force -ErrorAction Stop
        } catch {
            Write-Warning "Unable to stop timed-out process $($process.Id): $($_.Exception.Message)"
        }
        try {
            $process.WaitForExit()
        } catch {
        }
    }

    $watch.Stop()
    $exitCode = -1
    if ($completed) {
        $exitCode = $process.ExitCode
    }

    return [pscustomobject]@{
        ExitCode = $exitCode
        TimedOut = -not $completed
        DurationMs = [int]$watch.ElapsedMilliseconds
    }
}

function Get-MarkerPayloads {
    param(
        [Parameter(Mandatory = $true)][string]$LogPath,
        [Parameter(Mandatory = $true)][string]$Marker
    )
    $payloads = @()
    if (-not (Test-Path $LogPath)) {
        return $payloads
    }

    foreach ($line in Get-Content -LiteralPath $LogPath) {
        $index = $line.IndexOf($Marker, [System.StringComparison]::Ordinal)
        if ($index -lt 0) {
            continue
        }
        $jsonText = $line.Substring($index + $Marker.Length).Trim()
        if (-not $jsonText) {
            continue
        }
        try {
            $payloads += ,($jsonText | ConvertFrom-Json)
        } catch {
            throw "Invalid JSON after marker $Marker in $LogPath`: $jsonText"
        }
    }
    return $payloads
}

function Set-ProcessEnvironment {
    param([Parameter(Mandatory = $true)][hashtable]$Values)
    $previous = @{}
    foreach ($name in $Values.Keys) {
        $previous[$name] = [System.Environment]::GetEnvironmentVariable(
            $name,
            [System.EnvironmentVariableTarget]::Process
        )
        [System.Environment]::SetEnvironmentVariable(
            $name,
            [string]$Values[$name],
            [System.EnvironmentVariableTarget]::Process
        )
    }
    return $previous
}

function Restore-ProcessEnvironment {
    param([Parameter(Mandatory = $true)][hashtable]$Previous)
    foreach ($name in $Previous.Keys) {
        [System.Environment]::SetEnvironmentVariable(
            $name,
            $Previous[$name],
            [System.EnvironmentVariableTarget]::Process
        )
    }
}

function Add-Failure {
    param(
        [Parameter(Mandatory = $true)]
        [System.Collections.Generic.List[string]]$Failures,
        [Parameter(Mandatory = $true)]
        [string]$Message
    )
    if (-not $Failures.Contains($Message)) {
        $Failures.Add($Message) | Out-Null
    }
}

if (-not (Test-Path -LiteralPath $GodotPath -PathType Leaf)) {
    throw "Godot executable not found: $GodotPath"
}
$GodotPath = (Resolve-Path -LiteralPath $GodotPath).Path

if (-not (Test-Path -LiteralPath $MatrixPath -PathType Leaf)) {
    throw "UI matrix not found: $MatrixPath"
}

& python $StaticValidator
if ($LASTEXITCODE -ne 0) {
    throw "EVAVO Game Runtime UI Test Lab handshake validation failed."
}

$matrix = Get-Content -Raw -LiteralPath $MatrixPath | ConvertFrom-Json

if (-not $RuntimeRepo) {
    $RuntimeRepo = Join-Path (Split-Path -Parent $LabRoot) "evavo-game-runtime"
}
$RuntimeRepo = Resolve-FullPath $RuntimeRepo
if (-not (Test-Path (Join-Path $RuntimeRepo "project.godot") -PathType Leaf)) {
    throw "The runtime repository root must contain project.godot: $RuntimeRepo"
}

if (-not $EvidenceRoot) {
    $EvidenceRoot = [string]$matrix.default_evidence_root_windows
}
$EvidenceRoot = Resolve-FullPath $EvidenceRoot
if ((Test-PathInside $EvidenceRoot $LabRoot) -or (Test-PathInside $EvidenceRoot $RuntimeRepo)) {
    throw "EvidenceRoot must be outside both source repositories: $EvidenceRoot"
}

if ($TimeoutSeconds -le 0) {
    $TimeoutSeconds = [int]$matrix.default_timeout_seconds
}
if ($TimeoutSeconds -le 0) {
    throw "TimeoutSeconds must be greater than zero."
}

$labIdentity = Get-GitIdentity $LabRoot
$runtimeIdentity = Get-GitIdentity $RuntimeRepo
if ($RequireClean -and ($labIdentity.Dirty -or $runtimeIdentity.Dirty)) {
    throw "RequireClean was requested, but the Test Lab or Runtime checkout is dirty."
}

$runId = Get-Date -Format "yyyyMMdd-HHmmssfff"
$runRoot = Join-Path $EvidenceRoot $runId
New-Item -ItemType Directory -Force -Path $runRoot | Out-Null

$importStdout = Join-Path $runRoot "import.stdout.log"
$importStderr = Join-Path $runRoot "import.stderr.log"
$importResult = Invoke-BoundedProcess `
    -Executable $GodotPath `
    -Arguments @("--headless", "--editor", "--path", $RuntimeRepo, "--quit") `
    -StdoutPath $importStdout `
    -StderrPath $importStderr `
    -Timeout $TimeoutSeconds

if ($importResult.TimedOut -or $importResult.ExitCode -ne 0) {
    $summary = [ordered]@{
        version = 1
        run_id = $runId
        status = "failed"
        runtime_sha = $runtimeIdentity.Sha
        test_lab_sha = $labIdentity.Sha
        failures = @(
            "Godot import failed or timed out. See import.stdout.log and import.stderr.log."
        )
        scenarios = @()
    }
    $summary | ConvertTo-Json -Depth 100 | Set-Content `
        -LiteralPath (Join-Path $runRoot "summary.json") `
        -Encoding UTF8
    throw "Godot import failed or timed out. Evidence: $runRoot"
}

$scenarioResults = @()
$selected = @($matrix.scenarios)
if ($Scenario.Count -gt 0) {
    $wanted = @{}
    foreach ($id in $Scenario) {
        $wanted[$id] = $true
    }
    $selected = @($selected | Where-Object { $wanted.ContainsKey([string]$_.id) })
    if ($selected.Count -ne $wanted.Count) {
        $known = @($matrix.scenarios | ForEach-Object { [string]$_.id })
        throw "One or more requested scenarios are unknown. Known: $($known -join ', ')"
    }
}

foreach ($entry in $selected) {
    $scenarioId = [string]$entry.id
    $scenarioDir = Join-Path $runRoot $scenarioId
    New-Item -ItemType Directory -Force -Path $scenarioDir | Out-Null

    $stdoutPath = Join-Path $scenarioDir "stdout.log"
    $stderrPath = Join-Path $scenarioDir "stderr.log"
    $receiptPath = Join-Path $scenarioDir "receipt.json"
    $videoPath = Join-Path $scenarioDir "journey.mp4"
    $failures = New-Object "System.Collections.Generic.List[string]"
    $warnings = New-Object "System.Collections.Generic.List[string]"

    $width = [int]$entry.width
    $height = [int]$entry.height
    $safeInsets = @($entry.safe_insets | ForEach-Object { [double]$_ })
    $safeText = ($safeInsets | ForEach-Object {
        $_.ToString([System.Globalization.CultureInfo]::InvariantCulture)
    }) -join ","

    $environment = @{
        EVAVO_QA_ENABLED = "1"
        EVAVO_QA_SCREENSHOTS = "1"
        EVAVO_QA_OUTPUT_DIR = $scenarioDir
        EVAVO_QA_RUN_ID = $runId
        EVAVO_QA_SCENARIO = $scenarioId
        EVAVO_QA_LAYOUT = [string]$entry.layout_preset
        EVAVO_QA_MIN_TARGET = ([double]$entry.minimum_target_px).ToString(
            [System.Globalization.CultureInfo]::InvariantCulture
        )
        EVAVO_QA_SAFE_INSETS = $safeText
        EVAVO_QA_AUTOQUIT = "1"
    }

    $previousEnvironment = Set-ProcessEnvironment $environment
    try {
        $journeyResult = Invoke-BoundedProcess `
            -Executable $GodotPath `
            -Arguments @("--path", $RuntimeRepo, "--resolution", "$($width)x$($height)") `
            -StdoutPath $stdoutPath `
            -StderrPath $stderrPath `
            -Timeout $TimeoutSeconds
    } finally {
        Restore-ProcessEnvironment $previousEnvironment
    }

    if ($journeyResult.TimedOut) {
        Add-Failure $failures "Godot journey timed out."
    }
    if ($journeyResult.ExitCode -ne 0) {
        Add-Failure $failures "Godot journey exited with code $($journeyResult.ExitCode)."
    }

    try {
        $checkpoints = @(Get-MarkerPayloads $stdoutPath "EVAVO_UI_CHECKPOINT=")
        $navigationPayloads = @(Get-MarkerPayloads $stdoutPath "EVAVO_UI_NAVIGATION=")
        $finalPayloads = @(Get-MarkerPayloads $stdoutPath "EVAVO_UI_EVIDENCE=")
    } catch {
        Add-Failure $failures $_.Exception.Message
        $checkpoints = @()
        $navigationPayloads = @()
        $finalPayloads = @()
    }

    $navigation = @{}
    if ($navigationPayloads.Count -gt 0) {
        $navigation = $navigationPayloads[-1]
    } else {
        Add-Failure $failures "EVAVO_UI_NAVIGATION marker was not emitted."
    }

    $finalEvidence = @{}
    if ($finalPayloads.Count -gt 0) {
        $finalEvidence = $finalPayloads[-1]
    } else {
        Add-Failure $failures "EVAVO_UI_EVIDENCE marker was not emitted."
    }

    $minimumCheckpointCount = [int]$matrix.minimum_checkpoint_count
    if ($checkpoints.Count -lt $minimumCheckpointCount) {
        Add-Failure $failures (
            "Expected at least $minimumCheckpointCount checkpoints; received $($checkpoints.Count)."
        )
    }
    if ($navigationPayloads.Count -gt 0 -and -not [bool]$navigation.passed) {
        Add-Failure $failures "Deterministic navigation journey reported failure."
    }
    if ($finalPayloads.Count -gt 0 -and -not [bool]$finalEvidence.passed) {
        Add-Failure $failures "Final runtime evidence reported failure."
    }

    $screenshots = @()
    foreach ($checkpoint in $checkpoints) {
        $geometryErrors = [int]$checkpoint.geometry.summary.error_count
        if ($geometryErrors -gt 0) {
            Add-Failure $failures (
                "Checkpoint $($checkpoint.checkpoint_id) reported $geometryErrors geometry errors."
            )
        }
        if ([bool]$checkpoint.metadata.require_focus -and -not [bool]$checkpoint.focus.present) {
            Add-Failure $failures "Checkpoint $($checkpoint.checkpoint_id) lost required focus."
        }
        $screenshotPath = [string]$checkpoint.evidence.screenshot_path
        if (-not $screenshotPath -or -not (Test-Path -LiteralPath $screenshotPath -PathType Leaf)) {
            Add-Failure $failures "Checkpoint $($checkpoint.checkpoint_id) screenshot is missing."
        } else {
            $screenshots += $screenshotPath
        }
    }

    $videoCreated = $false
    if (-not $SkipVideo -and $screenshots.Count -gt 0) {
        $ffmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue
        if ($null -eq $ffmpeg) {
            $message = "FFmpeg was not found; checkpoint PNGs were retained without an MP4."
            if ($RequireVideo) {
                Add-Failure $failures $message
            } else {
                $warnings.Add($message) | Out-Null
            }
        } else {
            $videoStdout = Join-Path $scenarioDir "ffmpeg.stdout.log"
            $videoStderr = Join-Path $scenarioDir "ffmpeg.stderr.log"
            $videoResult = Invoke-BoundedProcess `
                -Executable $ffmpeg.Source `
                -Arguments @(
                    "-y",
                    "-framerate", [string]$matrix.video_fps,
                    "-i", (Join-Path $scenarioDir "frame_%04d.png"),
                    "-c:v", "libx264",
                    "-pix_fmt", "yuv420p",
                    $videoPath
                ) `
                -StdoutPath $videoStdout `
                -StderrPath $videoStderr `
                -Timeout $TimeoutSeconds
            $videoDidNotTimeOut = -not [bool]$videoResult.TimedOut
            $videoExitedSuccessfully = [int]$videoResult.ExitCode -eq 0
            $videoExists = Test-Path -LiteralPath $videoPath -PathType Leaf
            $videoCreated = (
                $videoDidNotTimeOut -and
                $videoExitedSuccessfully -and
                $videoExists
            )
            if (-not $videoCreated) {
                $message = "FFmpeg could not assemble the checkpoint review video."
                if ($RequireVideo) {
                    Add-Failure $failures $message
                } else {
                    $warnings.Add($message) | Out-Null
                }
            }
        }
    }

    $status = "passed"
    if ($failures.Count -gt 0) {
        $status = "failed"
    }

    $receipt = [ordered]@{
        version = 1
        run_id = $runId
        scenario_id = $scenarioId
        status = $status
        runtime_sha = $runtimeIdentity.Sha
        test_lab_sha = $labIdentity.Sha
        runtime_dirty = $runtimeIdentity.Dirty
        test_lab_dirty = $labIdentity.Dirty
        viewport = [ordered]@{
            width = $width
            height = $height
            layout_preset = [string]$entry.layout_preset
        }
        safe_insets = $safeInsets
        minimum_target_px = [double]$entry.minimum_target_px
        minimum_checkpoint_count = $minimumCheckpointCount
        godot = [ordered]@{
            path = $GodotPath
            import_exit_code = $importResult.ExitCode
            exit_code = $journeyResult.ExitCode
            timed_out = $journeyResult.TimedOut
            duration_ms = $journeyResult.DurationMs
        }
        checkpoints = $checkpoints
        navigation = $navigation
        final_evidence = $finalEvidence
        logs = [ordered]@{
            stdout_path = $stdoutPath
            stderr_path = $stderrPath
            import_stdout_path = $importStdout
            import_stderr_path = $importStderr
        }
        artifacts = [ordered]@{
            scenario_directory = $scenarioDir
            screenshots = $screenshots
            video_path = $(if ($videoCreated) { $videoPath } else { $null })
            video_created = $videoCreated
        }
        warnings = @($warnings)
        failures = @($failures)
    }

    $receipt | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $receiptPath -Encoding UTF8

    if ($status -eq "passed") {
        & python $ReceiptValidator $receiptPath
        if ($LASTEXITCODE -ne 0) {
            Add-Failure $failures "Independent receipt validation failed."
            $receipt.status = "failed"
            $receipt.failures = @($failures)
            $receipt | ConvertTo-Json -Depth 100 | Set-Content `
                -LiteralPath $receiptPath `
                -Encoding UTF8
        }
    }

    $scenarioResults += [pscustomobject]@{
        scenario_id = $scenarioId
        status = [string]$receipt.status
        receipt = $receiptPath
        checkpoint_count = $checkpoints.Count
        screenshot_count = $screenshots.Count
        video_created = $videoCreated
        failures = @($failures)
    }
}

$failedScenarios = @($scenarioResults | Where-Object { $_.status -ne "passed" })
$summary = [ordered]@{
    version = 1
    run_id = $runId
    status = $(if ($failedScenarios.Count -eq 0) { "passed" } else { "failed" })
    runtime_repo = $RuntimeRepo
    runtime_sha = $runtimeIdentity.Sha
    runtime_dirty = $runtimeIdentity.Dirty
    test_lab_repo = $LabRoot
    test_lab_sha = $labIdentity.Sha
    test_lab_dirty = $labIdentity.Dirty
    godot_path = $GodotPath
    evidence_root = $runRoot
    scenario_count = $scenarioResults.Count
    failed_scenario_count = $failedScenarios.Count
    scenarios = $scenarioResults
}

$summaryPath = Join-Path $runRoot "summary.json"
$summary | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $summaryPath -Encoding UTF8

if ($failedScenarios.Count -gt 0) {
    throw "EVAVO Game Runtime UI matrix failed. Summary: $summaryPath"
}

Write-Host "EVAVO Game Runtime UI matrix passed."
Write-Host "Summary: $summaryPath"