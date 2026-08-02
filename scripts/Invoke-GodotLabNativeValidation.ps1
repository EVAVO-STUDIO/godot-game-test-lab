[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$TargetRepositoryPath,

    [Parameter(Mandatory = $true)]
    [string]$ExpectedLabSha,

    [Parameter(Mandatory = $true)]
    [string]$ExpectedTargetSha,

    [Parameter(Mandatory = $true)]
    [string]$ArtifactPath,

    [Parameter(Mandatory = $true)]
    [string]$AllowedArtifactRoot,

    [string]$ProjectSubpath = ".",
    [string[]]$AllowedTargetRoots = @("C:\GitRepos"),
    [string]$PythonExecutable = "",
    [string]$GodotExecutable = "",
    [string]$DotnetExecutable = "",
    [string]$MinimumGodotVersion = "4.6.2",

    [ValidateRange(30, 7200)]
    [int]$TimeoutSeconds = 300,

    [ValidateRange(0, 3600)]
    [int]$BootFrames = 5
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Test-PathWithin {
    param(
        [Parameter(Mandatory = $true)][string]$Candidate,
        [Parameter(Mandatory = $true)][string]$Root
    )

    $candidateFull = [IO.Path]::GetFullPath($Candidate).TrimEnd('\', '/')
    $rootFull = [IO.Path]::GetFullPath($Root).TrimEnd('\', '/')
    if ($candidateFull.Equals($rootFull, [StringComparison]::OrdinalIgnoreCase)) {
        return $true
    }
    return $candidateFull.StartsWith(
        $rootFull + [IO.Path]::DirectorySeparatorChar,
        [StringComparison]::OrdinalIgnoreCase
    )
}

function Test-PathsOverlap {
    param(
        [Parameter(Mandatory = $true)][string]$Left,
        [Parameter(Mandatory = $true)][string]$Right
    )

    return (
        (Test-PathWithin -Candidate $Left -Root $Right) -or
        (Test-PathWithin -Candidate $Right -Root $Left)
    )
}

function Assert-NoReparsePoint {
    param([Parameter(Mandatory = $true)][string]$Path)

    $item = Get-Item -LiteralPath $Path -Force
    while ($null -ne $item) {
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Path traverses a reparse point and is not authoritative: $Path"
        }
        $item = $item.Parent
    }
}

function Get-GitText {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $lines = @(& git -C $Root @Arguments 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed: $($lines -join [Environment]::NewLine)"
    }
    return ($lines -join "`n").TrimEnd()
}

function Write-AtomicJson {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][object]$Value
    )

    $parent = Split-Path -Parent $Path
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    $temporary = "$Path.tmp-$PID-$([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds())"
    $json = ($Value | ConvertTo-Json -Depth 12) + [Environment]::NewLine
    [IO.File]::WriteAllText(
        $temporary,
        $json,
        [Text.UTF8Encoding]::new($false)
    )
    Move-Item -LiteralPath $temporary -Destination $Path -Force
}

function Invoke-CheckedCommand {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$ArgumentList,
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][string]$LogPath,
        [Parameter(Mandatory = $true)][System.Collections.IList]$Stages
    )

    $started = [DateTimeOffset]::UtcNow
    $stage = [ordered]@{
        id = $Label
        status = "running"
        startedAt = $started.ToString("o")
        log = $LogPath
    }
    try {
        Write-Host "[godot-lab] $Label"
        & $FilePath @ArgumentList 2>&1 | Tee-Object -FilePath $LogPath
        $stage.exitCode = $LASTEXITCODE
        if ($LASTEXITCODE -ne 0) {
            throw "$Label failed with exit code ${LASTEXITCODE}."
        }
        $stage.status = "passed"
    }
    catch {
        $stage.status = "failed"
        $stage.error = $_.Exception.Message
        throw
    }
    finally {
        $stage.finishedAt = [DateTimeOffset]::UtcNow.ToString("o")
        $stage.durationSeconds = [Math]::Round(
            ([DateTimeOffset]::UtcNow - $started).TotalSeconds,
            3
        )
        [void]$Stages.Add($stage)
    }
}

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw "Native Godot validation must run on Windows."
}
if ($ExpectedLabSha -notmatch '^[0-9a-f]{40}$') {
    throw "ExpectedLabSha must be an exact lowercase 40-character commit SHA."
}
if ($ExpectedTargetSha -notmatch '^[0-9a-f]{40}$') {
    throw "ExpectedTargetSha must be an exact lowercase 40-character commit SHA."
}
if ($MinimumGodotVersion -notmatch '^4\.[0-9]+\.[0-9]+$') {
    throw "MinimumGodotVersion must be an explicit Godot 4.x.y version."
}
$relativePattern = '^(?:\.|[A-Za-z0-9._-]+(?:[\\/][A-Za-z0-9._-]+)*)$'
if ($ProjectSubpath -notmatch $relativePattern -or
    $ProjectSubpath -match '(^|[\\/])\.\.([\\/]|$)') {
    throw "ProjectSubpath must be a traversal-free relative path."
}
if ($AllowedTargetRoots.Count -eq 0) {
    throw "At least one AllowedTargetRoots value is required."
}

$labRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Assert-NoReparsePoint -Path $labRoot
if (-not $PythonExecutable) {
    $PythonExecutable = Join-Path $labRoot ".venv\Scripts\python.exe"
}
$python = (Resolve-Path -LiteralPath $PythonExecutable).Path
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "PythonExecutable must identify a usable Python 3.11 executable."
}
Assert-NoReparsePoint -Path $python

$labGitRoot = Get-GitText -Root $labRoot -Arguments @(
    "rev-parse", "--show-toplevel"
) -Label "Resolve Lab Git root"
$labGitRoot = (Resolve-Path -LiteralPath $labGitRoot).Path
if (-not $labGitRoot.Equals($labRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "The script must run from the canonical Godot Game Test Lab Git root."
}
$currentLabSha = Get-GitText -Root $labRoot -Arguments @(
    "rev-parse", "HEAD"
) -Label "Resolve Lab SHA"
if ($currentLabSha -ne $ExpectedLabSha) {
    throw "The checked-out Lab SHA does not match ExpectedLabSha."
}
$labTrackedStatus = Get-GitText -Root $labRoot -Arguments @(
    "status", "--porcelain=v1", "--untracked-files=no"
) -Label "Read Lab tracked status"
if ($labTrackedStatus) {
    throw "The Lab checkout has tracked changes and cannot represent ExpectedLabSha."
}

$targetRoot = (Resolve-Path -LiteralPath $TargetRepositoryPath).Path
Assert-NoReparsePoint -Path $targetRoot
$targetGitRoot = Get-GitText -Root $targetRoot -Arguments @(
    "rev-parse", "--show-toplevel"
) -Label "Resolve target Git root"
$targetGitRoot = (Resolve-Path -LiteralPath $targetGitRoot).Path
Assert-NoReparsePoint -Path $targetGitRoot
if (-not $targetGitRoot.Equals($targetRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "TargetRepositoryPath must identify the target Git root; use ProjectSubpath for monorepos."
}
if ($targetGitRoot.Equals($labRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "The Test Lab cannot validate itself as a target game repository."
}

$resolvedAllowedRoots = @()
foreach ($root in $AllowedTargetRoots) {
    $resolved = (Resolve-Path -LiteralPath $root).Path
    Assert-NoReparsePoint -Path $resolved
    $resolvedAllowedRoots += $resolved
}
$targetAllowed = $false
foreach ($root in $resolvedAllowedRoots) {
    if (Test-PathWithin -Candidate $targetGitRoot -Root $root) {
        $targetAllowed = $true
        break
    }
}
if (-not $targetAllowed) {
    throw "TargetRepositoryPath is outside AllowedTargetRoots."
}

$projectPath = if ($ProjectSubpath -eq ".") {
    $targetGitRoot
}
else {
    (Resolve-Path -LiteralPath (Join-Path $targetGitRoot $ProjectSubpath)).Path
}
Assert-NoReparsePoint -Path $projectPath
if (-not (Test-PathWithin -Candidate $projectPath -Root $targetGitRoot)) {
    throw "ProjectSubpath escapes the target Git repository."
}
if (-not (Test-Path -LiteralPath (Join-Path $projectPath "project.godot") -PathType Leaf)) {
    throw "The selected ProjectSubpath does not contain project.godot."
}

$currentTargetSha = Get-GitText -Root $targetGitRoot -Arguments @(
    "rev-parse", "HEAD"
) -Label "Resolve target SHA"
if ($currentTargetSha -ne $ExpectedTargetSha) {
    throw "The target repository HEAD does not match ExpectedTargetSha."
}
$targetStatusBefore = Get-GitText -Root $targetGitRoot -Arguments @(
    "status", "--porcelain=v1", "--untracked-files=all"
) -Label "Read initial target status"
if ($targetStatusBefore) {
    throw "The target repository must be completely clean for exact-SHA validation."
}

New-Item -ItemType Directory -Force -Path $AllowedArtifactRoot | Out-Null
$artifactRoot = (Resolve-Path -LiteralPath $AllowedArtifactRoot).Path
Assert-NoReparsePoint -Path $artifactRoot
$artifactFull = [IO.Path]::GetFullPath($ArtifactPath)
if (-not (Test-PathWithin -Candidate $artifactFull -Root $artifactRoot)) {
    throw "ArtifactPath must remain beneath AllowedArtifactRoot."
}
foreach ($protected in @($labRoot, $targetGitRoot)) {
    if (Test-PathsOverlap -Left $artifactRoot -Right $protected) {
        throw "AllowedArtifactRoot must remain disjoint from Lab and target repositories."
    }
}
if (Test-Path -LiteralPath $artifactFull) {
    throw "ArtifactPath already exists; use a unique run directory."
}
New-Item -ItemType Directory -Path $artifactFull | Out-Null
$artifacts = (Resolve-Path -LiteralPath $artifactFull).Path
Assert-NoReparsePoint -Path $artifacts
$logs = Join-Path $artifacts "logs"
New-Item -ItemType Directory -Path $logs | Out-Null

$receiptPath = Join-Path $artifacts "native-validation-receipt.json"
$stages = [System.Collections.ArrayList]::new()
$receipt = [ordered]@{
    schemaVersion = "2.0"
    status = "running"
    startedAt = [DateTimeOffset]::UtcNow.ToString("o")
    labRepository = "EVAVO-STUDIO/godot-game-test-lab"
    labRoot = $labRoot
    labSha = $currentLabSha
    targetRepositoryPath = $targetGitRoot
    targetSha = $currentTargetSha
    projectSubpath = $ProjectSubpath
    projectPath = $projectPath
    allowedTargetRoots = $resolvedAllowedRoots
    artifactRoot = $artifactRoot
    artifacts = $artifacts
    python = $python
    minimumGodotVersion = $MinimumGodotVersion
    timeoutSeconds = $TimeoutSeconds
    bootFrames = $BootFrames
    targetUnchanged = $false
    stages = $stages
}
$validationError = $null

Push-Location $labRoot
try {
    Invoke-CheckedCommand -FilePath $python -ArgumentList @(
        "scripts/check_repository_toolchain.py", "--native-family", "--installed"
    ) -Label "toolchain" -LogPath (Join-Path $logs "toolchain.log") -Stages $stages

    Invoke-CheckedCommand -FilePath $python -ArgumentList @(
        "-m", "compileall", "-q", "src", "scripts", "tests"
    ) -Label "compile" -LogPath (Join-Path $logs "compile.log") -Stages $stages

    Invoke-CheckedCommand -FilePath $python -ArgumentList @(
        "-m", "ruff", "check", "src", "scripts", "tests"
    ) -Label "ruff" -LogPath (Join-Path $logs "ruff.log") -Stages $stages

    Invoke-CheckedCommand -FilePath $python -ArgumentList @(
        "-m", "pytest"
    ) -Label "pytest" -LogPath (Join-Path $logs "pytest.log") -Stages $stages

    $doctorArguments = @(
        "-m", "godot_game_test_lab.cli", "doctor",
        "--output", (Join-Path $artifacts "doctor.json")
    )
    if ($GodotExecutable) {
        $doctorArguments += @("--godot", $GodotExecutable)
    }
    if ($DotnetExecutable) {
        $doctorArguments += @("--dotnet", $DotnetExecutable)
    }
    Invoke-CheckedCommand -FilePath $python -ArgumentList $doctorArguments `
        -Label "doctor" -LogPath (Join-Path $logs "doctor.log") -Stages $stages

    $validationArguments = @(
        "-m", "godot_game_test_lab.cli", "validate", $projectPath,
        "--minimum-godot-version", $MinimumGodotVersion,
        "--timeout", $TimeoutSeconds.ToString(),
        "--boot-frames", $BootFrames.ToString(),
        "--artifacts", (Join-Path $artifacts "validation")
    )
    if ($GodotExecutable) {
        $validationArguments += @("--godot", $GodotExecutable)
    }
    if ($DotnetExecutable) {
        $validationArguments += @("--dotnet", $DotnetExecutable)
    }
    Invoke-CheckedCommand -FilePath $python -ArgumentList $validationArguments `
        -Label "validate" -LogPath (Join-Path $logs "validation.log") -Stages $stages

    $receipt.status = "passed"
}
catch {
    $validationError = $_.Exception
    $receipt.status = "failed"
    $receipt.error = $validationError.Message
}
finally {
    Pop-Location
    try {
        $finalTargetSha = Get-GitText -Root $targetGitRoot -Arguments @(
            "rev-parse", "HEAD"
        ) -Label "Resolve final target SHA"
        $targetStatusAfter = Get-GitText -Root $targetGitRoot -Arguments @(
            "status", "--porcelain=v1", "--untracked-files=all"
        ) -Label "Read final target status"
        $receipt.targetUnchanged = (
            $finalTargetSha -eq $currentTargetSha -and
            $targetStatusAfter -eq $targetStatusBefore
        )
        $receipt.targetStatusBefore = $targetStatusBefore
        $receipt.targetStatusAfter = $targetStatusAfter
        if (-not $receipt.targetUnchanged) {
            $receipt.status = "failed"
            $receipt.error = "Native validation changed or obscured the target repository."
            $validationError = [InvalidOperationException]::new($receipt.error)
        }
    }
    catch {
        $receipt.status = "failed"
        $receipt.targetUnchanged = $false
        $receipt.error = $_.Exception.Message
        $validationError = $_.Exception
    }
    $receipt.finishedAt = [DateTimeOffset]::UtcNow.ToString("o")
    Write-AtomicJson -Path $receiptPath -Value $receipt
}

if ($validationError) {
    throw $validationError
}

Write-Host "[godot-lab] Native validation passed. Receipt: $receiptPath"
