[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$TargetRepositoryPath,

    [Parameter(Mandatory = $true)]
    [string]$ExpectedLabSha,

    [Parameter(Mandatory = $true)]
    [string]$ArtifactPath,

    [string]$PythonExecutable = "python",
    [string]$MinimumGodotVersion = "4.6.2",
    [ValidateRange(1, 3600)]
    [int]$TimeoutSeconds = 300,
    [ValidateRange(0, 600)]
    [int]$BootFrames = 5
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Invoke-CheckedCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [Parameter(Mandatory = $true)]
        [string[]]$ArgumentList,
        [Parameter(Mandatory = $true)]
        [string]$Label,
        [string]$LogPath
    )

    Write-Host "[godot-lab] $Label"
    if ($LogPath) {
        & $FilePath @ArgumentList 2>&1 | Tee-Object -FilePath $LogPath
    }
    else {
        & $FilePath @ArgumentList
    }
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE."
    }
}

function Test-ChildPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Candidate,
        [Parameter(Mandatory = $true)]
        [string]$Parent
    )

    $parentPrefix = $Parent.TrimEnd([System.IO.Path]::DirectorySeparatorChar) +
        [System.IO.Path]::DirectorySeparatorChar
    return $Candidate.StartsWith(
        $parentPrefix,
        [System.StringComparison]::OrdinalIgnoreCase
    )
}

if ($ExpectedLabSha -notmatch '^[0-9a-f]{40}$') {
    throw "ExpectedLabSha must be an exact 40-character lowercase commit SHA."
}
if ($MinimumGodotVersion -notmatch '^4\.[0-9]+\.[0-9]+$') {
    throw "MinimumGodotVersion must be an explicit Godot 4.x.y version."
}

$labRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$allowedRepositoryRoot = (Resolve-Path "C:\GitRepos").Path
$target = (Resolve-Path $TargetRepositoryPath).Path

if (-not (Test-ChildPath -Candidate $target -Parent $allowedRepositoryRoot)) {
    throw "TargetRepositoryPath must resolve beneath C:\GitRepos."
}
if ($target.Equals($labRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "The test lab cannot validate itself as a game project."
}
if (-not (Test-Path (Join-Path $target "project.godot") -PathType Leaf)) {
    throw "TargetRepositoryPath does not contain project.godot."
}

$currentLabSha = (& git -C $labRoot rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $currentLabSha -ne $ExpectedLabSha) {
    throw "The checked-out lab SHA does not match ExpectedLabSha."
}

$gitRoot = (& git -C $target rev-parse --show-toplevel).Trim()
if ($LASTEXITCODE -ne 0 -or -not $gitRoot) {
    throw "TargetRepositoryPath must belong to a Git repository."
}
$gitRoot = (Resolve-Path $gitRoot).Path
if (-not (Test-ChildPath -Candidate $gitRoot -Parent $allowedRepositoryRoot) -and
    -not $gitRoot.Equals($allowedRepositoryRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "The target Git root must remain beneath C:\GitRepos."
}

New-Item -ItemType Directory -Path $ArtifactPath -Force | Out-Null
$artifacts = (Resolve-Path $ArtifactPath).Path
if (-not (Test-ChildPath -Candidate $artifacts -Parent $labRoot) -and
    -not (Test-ChildPath -Candidate $artifacts -Parent $target)) {
    throw "ArtifactPath must remain beneath the lab checkout or target project."
}

$trackedBefore = @(& git -C $gitRoot status --porcelain=v1 --untracked-files=no) -join "`n"
if ($LASTEXITCODE -ne 0) {
    throw "Unable to capture the target repository's tracked status."
}

$receiptPath = Join-Path $artifacts "native-validation-receipt.json"
$receipt = [ordered]@{
    schemaVersion = "1.0"
    labRepository = "EVAVO-STUDIO/godot-game-test-lab"
    labSha = $currentLabSha
    targetRepositoryPath = $target
    targetGitRoot = $gitRoot
    minimumGodotVersion = $MinimumGodotVersion
    timeoutSeconds = $TimeoutSeconds
    bootFrames = $BootFrames
    trackedMutationDetected = $false
    status = "running"
}

try {
    Invoke-CheckedCommand -FilePath $PythonExecutable -ArgumentList @(
        "-m", "compileall", "src", "tests"
    ) -Label "Compile Python sources"

    Invoke-CheckedCommand -FilePath $PythonExecutable -ArgumentList @(
        "-m", "ruff", "check", "src", "tests"
    ) -Label "Run Ruff"

    Invoke-CheckedCommand -FilePath $PythonExecutable -ArgumentList @(
        "-m", "pytest"
    ) -Label "Run pytest"

    Invoke-CheckedCommand -FilePath $PythonExecutable -ArgumentList @(
        "-m", "godot_game_test_lab.cli", "doctor",
        "--output", (Join-Path $artifacts "doctor.json")
    ) -Label "Probe Godot and .NET tools" -LogPath (Join-Path $artifacts "doctor.log")

    Invoke-CheckedCommand -FilePath $PythonExecutable -ArgumentList @(
        "-m", "godot_game_test_lab.cli", "validate", $target,
        "--minimum-godot-version", $MinimumGodotVersion,
        "--timeout", $TimeoutSeconds.ToString(),
        "--boot-frames", $BootFrames.ToString(),
        "--artifacts", $artifacts
    ) -Label "Validate Godot project" -LogPath (Join-Path $artifacts "validation.log")

    $receipt.status = "passed"
}
catch {
    $receipt.status = "failed"
    $receipt.error = $_.Exception.Message
    throw
}
finally {
    $trackedAfter = @(& git -C $gitRoot status --porcelain=v1 --untracked-files=no) -join "`n"
    if ($LASTEXITCODE -ne 0) {
        $receipt.status = "failed"
        $receipt.error = "Unable to capture final tracked repository status."
    }
    $receipt.trackedMutationDetected = $trackedAfter -ne $trackedBefore
    $receipt.trackedStatusBefore = $trackedBefore
    $receipt.trackedStatusAfter = $trackedAfter
    $receipt | ConvertTo-Json -Depth 6 | Set-Content -Path $receiptPath -Encoding UTF8

    if ($receipt.trackedMutationDetected) {
        throw "Native validation changed tracked files in the target repository."
    }
}

Write-Host "[godot-lab] Native validation passed without tracked source changes."
