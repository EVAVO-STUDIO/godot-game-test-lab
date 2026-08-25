[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Target,
    [Parameter(Mandatory)][string]$Project,
    [Parameter(Mandatory)][string]$Package,
    [Parameter(Mandatory)][string]$Journey,
    [string]$Preset = 'Android',
    [string]$AndroidBridgeRepo,
    [string]$Godot,
    [string]$Python,
    [string]$EvidenceDir,
    [int]$HostPort = 43821,
    [int]$DevicePort = 43821,
    [int]$LogLines = 2000,
    [switch]$AllowDowngrade,
    [switch]$DryRun,
    [string]$Confirm
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$labRoot = Split-Path -Parent $PSScriptRoot

if (-not (Test-Path -LiteralPath $Journey -PathType Leaf)) {
    throw "Android semantic journey file not found: $Journey"
}
if ($HostPort -lt 1024 -or $HostPort -gt 65535 -or $DevicePort -lt 1024 -or $DevicePort -gt 65535) {
    throw 'HostPort and DevicePort must both be between 1024 and 65535.'
}
if (-not $DryRun -and $Confirm -ne 'TEST_GODOT_ANDROID_JOURNEY_ON_OWNED_DEVICE') {
    throw 'Use -Confirm TEST_GODOT_ANDROID_JOURNEY_ON_OWNED_DEVICE to deploy and exercise an owned Android test device.'
}

if (-not $AndroidBridgeRepo) {
    $repoParent = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
    $AndroidBridgeRepo = Join-Path $repoParent 'evavo-android-device-bridge'
}
$bridgeCli = Join-Path $AndroidBridgeRepo 'src\cli.mjs'
$bringupCli = Join-Path $AndroidBridgeRepo 'src\bringup-cli.mjs'
$deviceScript = Join-Path $PSScriptRoot 'Invoke-GodotLabAndroidDevice.ps1'
if (-not (Test-Path -LiteralPath $bridgeCli -PathType Leaf)) {
    throw "Android bridge CLI not found: $bridgeCli"
}
if (-not (Test-Path -LiteralPath $bringupCli -PathType Leaf)) {
    throw "Android bridge bring-up CLI not found: $bringupCli"
}
if (-not (Test-Path -LiteralPath $deviceScript -PathType Leaf)) {
    throw "Godot Android device wrapper not found: $deviceScript"
}

if (-not $Python) {
    $venvPython = Join-Path $labRoot '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $venvPython -PathType Leaf) {
        $Python = $venvPython
    } else {
        $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
        if ($pythonCommand) { $Python = $pythonCommand.Source }
    }
}
if (-not $Python) {
    throw 'Python is unavailable. Install the Godot Lab environment or supply -Python.'
}

$bringupText = (& node $bringupCli --json | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($bringupText)) {
    throw 'Android bridge bring-up failed before physical Godot journey admission.'
}
try { $bringup = $bringupText | ConvertFrom-Json -ErrorAction Stop } catch { throw 'Android bridge bring-up returned invalid JSON.' }
$targetDevice = @($bringup.devices | Where-Object { $_.targetRef -eq $Target -and $_.state -eq 'device' }) | Select-Object -First 1
if (-not $targetDevice) { throw 'The selected Android target is not currently authorised and online.' }
if ($targetDevice.deviceClass -ne 'physical') { throw 'Physical Godot Android semantic journeys reject emulator or unknown targets.' }

$resolvedProject = (Resolve-Path -LiteralPath $Project).Path
$admissionText = (& $Python -m godot_game_test_lab.android_export_admission --project $resolvedProject --preset $Preset | Out-String).Trim()
if ($LASTEXITCODE -ne 0) {
    throw 'Godot Android semantic export admission failed. The selected Android preset and semantic driver must satisfy the debug journey contract.'
}
try { $admission = $admissionText | ConvertFrom-Json -ErrorAction Stop } catch { throw 'Godot Android semantic export admission returned invalid JSON.' }
if ($admission.ok -ne $true -or $admission.semanticDriverEnabled -ne $true -or [int]$admission.allowedActionCount -lt 1) {
    throw 'Godot Android semantic driver admission was not verified.'
}

$projectName = Split-Path -Leaf ([System.IO.Path]::GetFullPath($Project).TrimEnd('\','/'))
$runId = Get-Date -Format 'yyyyMMdd-HHmmss'
if (-not $EvidenceDir) {
    $EvidenceDir = Join-Path 'C:\GodotLabEvidence' "$projectName\android-journey-$runId"
}
$bridgeEvidenceBase = "evidence/private/godot-lab/$projectName/android-journey-$runId"
$preEvidence = "$bridgeEvidenceBase/pre"
$postEvidence = "$bridgeEvidenceBase/post"

if ($DryRun) {
    [ordered]@{
        schema = 'evavo_godot_lab_android_journey_plan_v1'
        ok = $true
        mutationPerformed = $false
        targetRef = $Target
        deviceClass = $targetDevice.deviceClass
        physicalDeviceRequired = $true
        project = [System.IO.Path]::GetFullPath($Project)
        package = $Package
        preset = $Preset
        journey = [System.IO.Path]::GetFullPath($Journey)
        hostPort = $HostPort
        devicePort = $DevicePort
        debugExportRequired = $true
        internetPermissionVerified = $admission.internetPermission -eq $true
        semanticDriverEnabled = $admission.semanticDriverEnabled -eq $true
        semanticDriverAutoload = $admission.semanticDriverAutoload
        allowedActionCount = $admission.allowedActionCount
        bridgeEvidencePre = $preEvidence
        bridgeEvidencePost = $postEvidence
        labEvidenceDirectory = [System.IO.Path]::GetFullPath($EvidenceDir)
        cleanupAttemptedOnFailure = $true
    } | ConvertTo-Json -Depth 6
    exit 0
}

New-Item -ItemType Directory -Force -Path $EvidenceDir | Out-Null
$journeyOutput = Join-Path $EvidenceDir 'android-semantic-journey.json'
$summaryOutput = Join-Path $EvidenceDir 'android-journey-summary.json'
$mappingCreated = $false
$mappingRemoved = $false
$postEvidenceCaptured = $false
$failure = $null
$cleanupFailure = $null
$journeyReceipt = $null

try {
    $deployParams = @{
        Target = $Target
        Project = $Project
        Package = $Package
        Preset = $Preset
        AndroidBridgeRepo = $AndroidBridgeRepo
        EvidenceDir = $EvidenceDir
        BridgeEvidenceDir = $preEvidence
        LogLines = $LogLines
        Confirm = 'TEST_GODOT_ANDROID_ON_OWNED_DEVICE'
    }
    if ($Godot) { $deployParams.Godot = $Godot }
    if ($AllowDowngrade) { $deployParams.AllowDowngrade = $true }
    & $deviceScript @deployParams | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Godot Android deployment failed with exit code $LASTEXITCODE." }

    & node $bridgeCli forward --target $Target --local-port ([string]$HostPort) --remote-port ([string]$DevicePort) --confirm CREATE_ANDROID_PORT_MAPPING --json | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "ADB forward creation failed with exit code $LASTEXITCODE." }
    $mappingCreated = $true

    & $Python -m godot_game_test_lab.android_semantic_driver_cli --port ([string]$HostPort) --journey (Resolve-Path -LiteralPath $Journey).Path --output $journeyOutput | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Android semantic journey failed with exit code $LASTEXITCODE." }
    try { $journeyReceipt = Get-Content -LiteralPath $journeyOutput -Raw -Encoding UTF8 | ConvertFrom-Json -ErrorAction Stop } catch { throw 'Android semantic journey output was missing or invalid.' }
    if ($journeyReceipt.ok -ne $true -or $journeyReceipt.truth.semanticInput -ne $true -or $journeyReceipt.truth.rawCoordinatesUsed -ne $false -or $journeyReceipt.truth.androidShellExposed -ne $false) {
        throw 'Android semantic journey returned an invalid truth receipt.'
    }

    & node $bridgeCli evidence --target $Target --package $Package --output-dir $postEvidence --lines ([string]$LogLines) --json | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Post-journey Android evidence capture failed with exit code $LASTEXITCODE." }
    $postEvidenceCaptured = $true
}
catch {
    $failure = $_
}
finally {
    if ($mappingCreated) {
        & node $bridgeCli forward-remove --target $Target --local-port ([string]$HostPort) --json | Out-Null
        if ($LASTEXITCODE -eq 0) {
            $mappingRemoved = $true
        } else {
            $cleanupFailure = "ADB forward cleanup failed with exit code $LASTEXITCODE."
            if (-not $failure) {
                $failure = [System.Exception]::new($cleanupFailure)
            }
        }
    }
}

$journeySucceeded = -not $failure
$assertionCount = if ($journeyReceipt) { [int]$journeyReceipt.assertionCount } else { 0 }
$finalState = if ($journeyReceipt) { $journeyReceipt.finalState } else { $null }
$summary = [ordered]@{
    schema = 'evavo_godot_lab_android_journey_summary_v1'
    ok = $journeySucceeded
    targetRef = $Target
    deviceClass = $targetDevice.deviceClass
    physicalDeviceRequired = $true
    package = $Package
    project = [System.IO.Path]::GetFullPath($Project)
    preset = $Preset
    journey = [System.IO.Path]::GetFullPath($Journey)
    journeyResult = if (Test-Path -LiteralPath $journeyOutput) { [System.IO.Path]::GetFullPath($journeyOutput) } else { $null }
    assertionCount = $assertionCount
    projectStateAssertionsPerformed = $assertionCount -gt 0
    finalSemanticState = $finalState
    bridgeEvidencePre = $preEvidence
    bridgeEvidencePost = if ($postEvidenceCaptured) { $postEvidence } else { $null }
    postEvidenceCaptured = $postEvidenceCaptured
    internetPermissionVerified = $admission.internetPermission -eq $true
    semanticDriverEnabled = $admission.semanticDriverEnabled -eq $true
    semanticDriverAutoload = $admission.semanticDriverAutoload
    allowedActionCount = $admission.allowedActionCount
    hostPort = $HostPort
    devicePort = $DevicePort
    portMappingCreated = $mappingCreated
    portMappingRemoved = $mappingRemoved
    cleanupFailure = $cleanupFailure
    physicalDeviceExecutionClaimed = $journeySucceeded
    semanticGameplayClaimed = $journeySucceeded
    semanticOutcomeAssertionsClaimed = $journeySucceeded -and $assertionCount -gt 0
    releaseBuildClaimed = $false
    rawCoordinatesUsed = $false
    arbitraryAdbShellExposed = $false
    arbitraryNodeInspectionExposed = $false
    failure = if ($failure) { $failure.Exception.Message } else { $null }
    completedAt = (Get-Date).ToUniversalTime().ToString('o')
}
$encodedSummary = $summary | ConvertTo-Json -Depth 12
$encodedSummary | Set-Content -LiteralPath $summaryOutput -Encoding UTF8
Write-Output $encodedSummary

if ($failure) {
    throw $failure
}
exit 0
