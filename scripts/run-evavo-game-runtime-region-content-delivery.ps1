param(
    [string]$GodotPath = $env:GODOT_BIN,
    [string]$RuntimeRepo = "C:\GitRepos\evavo-game-runtime",
    [string]$EvidenceRoot,
    [switch]$RequireGodot
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$TestLabRoot = Split-Path -Parent $PSScriptRoot
$RuntimeRepo = [System.IO.Path]::GetFullPath($RuntimeRepo)
if (-not (Test-Path -LiteralPath $RuntimeRepo -PathType Container)) {
    throw "Runtime repository does not exist: $RuntimeRepo"
}
if (-not (Test-Path -LiteralPath (Join-Path $RuntimeRepo ".git") -PathType Container)) {
    throw "Runtime path is not a Git checkout: $RuntimeRepo"
}
if (-not (Test-Path -LiteralPath (Join-Path $TestLabRoot ".git") -PathType Container)) {
    throw "Test Lab path is not a Git checkout: $TestLabRoot"
}

$runId = "region-content-delivery-{0}" -f ([DateTime]::UtcNow.ToString("yyyyMMddTHHmmssfffZ"))
if (-not $EvidenceRoot) {
    $EvidenceRoot = Join-Path $TestLabRoot ("artifacts\region-content-delivery\{0}" -f $runId)
}
$EvidenceRoot = [System.IO.Path]::GetFullPath($EvidenceRoot)
New-Item -ItemType Directory -Force -Path $EvidenceRoot | Out-Null

function Get-GitValue {
    param(
        [Parameter(Mandatory = $true)][string]$RepoPath,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    Push-Location $RepoPath
    try {
        # Canonical evidence is collected with: git rev-parse HEAD
        $value = & git @Arguments 2>&1
        $exitCode = $LASTEXITCODE
        if ($exitCode -ne 0) {
            throw "Git command failed in $RepoPath: git $($Arguments -join ' ')"
        }
        return (($value | Select-Object -First 1) -as [string]).Trim()
    }
    finally {
        Pop-Location
    }
}

function Resolve-LocalGodot {
    param([string]$RequestedPath)

    if ($RequestedPath -and (Test-Path -LiteralPath $RequestedPath -PathType Leaf)) {
        return (Resolve-Path -LiteralPath $RequestedPath).Path
    }

    foreach ($name in @("godot", "godot4", "Godot")) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if ($command -and $command.Source) {
            return $command.Source
        }
    }

    $roots = @(
        "$env:LOCALAPPDATA\Programs",
        "$env:USERPROFILE\Downloads",
        "$env:USERPROFILE\Desktop",
        "C:\Program Files",
        "C:\Program Files (x86)"
    ) | Where-Object {
        $_ -and (Test-Path -LiteralPath $_ -PathType Container)
    }

    foreach ($root in $roots) {
        $candidate = Get-ChildItem -LiteralPath $root -File -Recurse -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match '^Godot.*\.exe$' } |
            Sort-Object LastWriteTimeUtc -Descending |
            Select-Object -First 1
        if ($candidate) {
            return $candidate.FullName
        }
    }

    return $null
}

function Invoke-LoggedCheck {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Executable,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [string]$RequiredMarker = ""
    )

    $safeName = ($Name -replace '[^A-Za-z0-9._-]', '_')
    $logPath = Join-Path $EvidenceRoot ("{0}.log" -f $safeName)
    $started = [DateTime]::UtcNow
    $outputLines = @()
    $exitCode = $null
    $reason = ""

    Push-Location $WorkingDirectory
    try {
        $outputLines = & $Executable @Arguments 2>&1 |
            ForEach-Object { [string]$_ }
        $exitCode = $LASTEXITCODE
    }
    catch {
        $outputLines += [string]$_
        $exitCode = 1
        $reason = $_.Exception.Message
    }
    finally {
        Pop-Location
    }

    $outputLines | Set-Content -LiteralPath $logPath -Encoding UTF8
    $markerPresent = $true
    if ($RequiredMarker) {
        $markerPresent = [bool]($outputLines | Where-Object { $_ -eq $RequiredMarker })
        if (-not $markerPresent -and -not $reason) {
            $reason = "Required marker was not emitted: $RequiredMarker"
        }
    }

    $status = "pass"
    if ($exitCode -ne 0 -or -not $markerPresent) {
        $status = "fail"
        if (-not $reason) {
            $reason = "Process exited with code $exitCode"
        }
    }

    return [ordered]@{
        status = $status
        exit_code = $exitCode
        log_path = $logPath
        marker = $RequiredMarker
        reason = $reason
        started_at_utc = $started.ToString("o")
        finished_at_utc = [DateTime]::UtcNow.ToString("o")
    }
}

function New-SkippedCheck {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Reason
    )

    return [ordered]@{
        status = "skipped"
        exit_code = $null
        log_path = (Join-Path $EvidenceRoot ("{0}.log" -f $Name))
        marker = ""
        reason = $Reason
        started_at_utc = [DateTime]::UtcNow.ToString("o")
        finished_at_utc = [DateTime]::UtcNow.ToString("o")
    }
}

$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCommand) {
    $pythonCommand = Get-Command python3 -ErrorAction SilentlyContinue
}
if (-not $pythonCommand -or -not $pythonCommand.Source) {
    throw "Python 3 was not found on PATH."
}
$python = $pythonCommand.Source

$runtimeSha = Get-GitValue -RepoPath $RuntimeRepo -Arguments @("rev-parse", "HEAD")
$testLabSha = Get-GitValue -RepoPath $TestLabRoot -Arguments @("rev-parse", "HEAD")
$runtimeBranch = Get-GitValue -RepoPath $RuntimeRepo -Arguments @("branch", "--show-current")
$testLabBranch = Get-GitValue -RepoPath $TestLabRoot -Arguments @("branch", "--show-current")

foreach ($sha in @($runtimeSha, $testLabSha)) {
    if ($sha -notmatch '^[0-9a-f]{40}$') {
        throw "Invalid Git SHA evidence: $sha"
    }
}

$sourceValidation = [ordered]@{
    content_delivery = Invoke-LoggedCheck `
        -Name "source-content-delivery" `
        -Executable $python `
        -Arguments @("tests/validate_region_content_delivery.py") `
        -WorkingDirectory $RuntimeRepo `
        -RequiredMarker "EVAVO region content delivery validation passed"
    region_package_binding = Invoke-LoggedCheck `
        -Name "source-region-package-binding" `
        -Executable $python `
        -Arguments @("tests/validate_region_package_binding.py") `
        -WorkingDirectory $RuntimeRepo `
        -RequiredMarker "EVAVO region package binding validation passed"
}

$godot = Resolve-LocalGodot -RequestedPath $GodotPath
$godotVersion = $null
$executableValidation = [ordered]@{}

if ($godot) {
    $versionLines = & $godot --version 2>&1 | ForEach-Object { [string]$_ }
    if ($LASTEXITCODE -ne 0) {
        throw "Godot version check failed: $godot"
    }
    $godotVersion = ($versionLines | Select-Object -First 1)

    $executableValidation.godot_import = Invoke-LoggedCheck `
        -Name "godot-import" `
        -Executable $godot `
        -Arguments @("--headless", "--editor", "--path", $RuntimeRepo, "--quit") `
        -WorkingDirectory $RuntimeRepo

    $executableValidation.delivery_session_smoke = Invoke-LoggedCheck `
        -Name "godot-delivery-session-smoke" `
        -Executable $godot `
        -Arguments @(
            "--headless",
            "--path", $RuntimeRepo,
            "--script", (Join-Path $RuntimeRepo "tests\godot\test_content_delivery_session.gd")
        ) `
        -WorkingDirectory $RuntimeRepo `
        -RequiredMarker "EVAVO_CONTENT_DELIVERY_SESSION_TEST=PASS"

    $executableValidation.region_driver_smoke = Invoke-LoggedCheck `
        -Name "godot-region-driver-smoke" `
        -Executable $godot `
        -Arguments @(
            "--headless",
            "--path", $RuntimeRepo,
            "--script", (Join-Path $RuntimeRepo "tests\godot\test_region_content_driver.gd")
        ) `
        -WorkingDirectory $RuntimeRepo `
        -RequiredMarker "EVAVO_REGION_CONTENT_DRIVER_TEST=PASS"
}
else {
    $missingReason = "Godot executable was not found; executable checks were not run."
    $executableValidation.godot_import = New-SkippedCheck `
        -Name "godot-import" `
        -Reason $missingReason
    $executableValidation.delivery_session_smoke = New-SkippedCheck `
        -Name "godot-delivery-session-smoke" `
        -Reason $missingReason
    $executableValidation.region_driver_smoke = New-SkippedCheck `
        -Name "godot-region-driver-smoke" `
        -Reason $missingReason
}

$allSourcePassed = @($sourceValidation.Values | ForEach-Object { $_.status }) -notcontains "fail"
$allExecutablePassed = @($executableValidation.Values | ForEach-Object { $_.status }) -notcontains "fail" -and
    @($executableValidation.Values | ForEach-Object { $_.status }) -notcontains "skipped"
$anyFailed = @(
    $sourceValidation.Values + $executableValidation.Values |
        ForEach-Object { $_.status }
) -contains "fail"

$status = "partial"
if ($anyFailed) {
    $status = "fail"
}
elseif ($allSourcePassed -and $allExecutablePassed) {
    $status = "pass"
}

$notes = @(
    "The in-memory delivery host is deterministic test infrastructure, not a storefront or network downloader.",
    "Declared package byte sizes are planning metadata and are not measured transfer or disk usage.",
    "Threaded resource cancellation is represented as draining until the host reports completion.",
    "Content or install completion never grants simulation authority."
)
if (-not $godot) {
    $notes += "Executable Godot validation was skipped because no local Godot executable was found."
}

$receipt = [ordered]@{
    version = 1
    suite_id = "evavo_game_runtime_region_content_delivery"
    run_id = $runId
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    status = $status
    runtime_repository = "EVAVO-STUDIO/evavo-game-runtime"
    runtime_sha = $runtimeSha
    test_lab_repository = "EVAVO-STUDIO/godot-game-test-lab"
    test_lab_sha = $testLabSha
    runtime_branch = $runtimeBranch
    test_lab_branch = $testLabBranch
    godot_version = $godotVersion
    source_validation = $sourceValidation
    executable_validation = $executableValidation
    claims = [ordered]@{
        real_storefront_install_verified = $false
        real_network_transfer_verified = $false
        measured_byte_progress_verified = $false
        threaded_load_hard_cancel_verified = $false
        resource_completion_grants_authority = $false
        declared_bytes_are_measured_bytes = $false
    }
    evidence_root = $EvidenceRoot
    notes = $notes
}

$receiptPath = Join-Path $EvidenceRoot "receipt.json"
$receipt | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $receiptPath -Encoding UTF8

$verifyScript = Join-Path $PSScriptRoot "verify-evavo-game-runtime-region-content-delivery-receipt.py"
$verification = Invoke-LoggedCheck `
    -Name "receipt-verification" `
    -Executable $python `
    -Arguments @($verifyScript, $receiptPath) `
    -WorkingDirectory $TestLabRoot `
    -RequiredMarker "EVAVO region content delivery receipt verification passed"
if ($verification.status -ne "pass") {
    $status = "fail"
}

Write-Host "EVAVO_REGION_CONTENT_DELIVERY_RECEIPT=$receiptPath"
Write-Host "EVAVO_REGION_CONTENT_DELIVERY_STATUS=$status"

if ($RequireGodot -and -not $godot) {
    throw "Godot was required but no executable was found. Receipt: $receiptPath"
}
if ($status -eq "fail") {
    throw "Region content delivery validation failed. Receipt: $receiptPath"
}
