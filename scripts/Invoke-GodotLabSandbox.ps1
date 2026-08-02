[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$TargetRepositoryPath,
    [string]$LabRoot = "",
    [string]$ProjectSubpath = ".",
    [string]$ProfilePath = "",
    [string]$EvidenceRoot = "C:\GodotLabEvidence",
    [string]$ArtifactPath = "",
    [string]$GodotVersion = "4.6.3",
    [string]$ImageRepository = "evavo/godot-lab-sandbox",
    [string]$ExpectedLabSha = "",
    [string]$ExpectedTargetSha = "",
    [ValidateRange(30, 3600)]
    [int]$TimeoutSeconds = 600,
    [ValidateRange(0, 3600)]
    [int]$BootFrames = 30,
    [ValidateRange(1, 16)]
    [int]$CpuCount = 4,
    [ValidatePattern('^[1-9][0-9]*(m|g)$')]
    [string]$Memory = "10g",
    [switch]$BuildImage,
    [switch]$NoCache
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Test-IsWithinPath {
    param([string]$Candidate, [string]$Parent)
    $candidateFull = [IO.Path]::GetFullPath($Candidate).TrimEnd('\')
    $parentFull = [IO.Path]::GetFullPath($Parent).TrimEnd('\')
    return (
        $candidateFull -eq $parentFull -or
        $candidateFull.StartsWith(
            $parentFull + '\',
            [StringComparison]::OrdinalIgnoreCase
        )
    )
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$Command,
        [Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments
    )
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Command failed with exit code ${LASTEXITCODE}: $($Arguments -join ' ')"
    }
}

function Get-GitValue {
    param([string]$Root, [string[]]$Arguments, [switch]$Optional)
    $value = (& git -C $Root @Arguments 2>$null)
    if ($LASTEXITCODE -ne 0) {
        if ($Optional) { return $null }
        throw "Git command failed in ${Root}: $($Arguments -join ' ')"
    }
    return ($value -join "`n").Trim()
}

function Invoke-LabPython {
    param([string[]]$Arguments)
    $venvPython = Join-Path $resolvedLab ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venvPython -PathType Leaf) {
        & $venvPython @Arguments
    }
    else {
        $py = Get-Command py -ErrorAction SilentlyContinue
        if (-not $py) {
            throw "Python 3.11 is required; run scripts\Install-GodotLab.ps1 first."
        }
        & $py.Source -3.11 @Arguments
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed: $($Arguments -join ' ')"
    }
}

if (-not $LabRoot) {
    $LabRoot = Split-Path -Parent $PSScriptRoot
}
$resolvedLab = (Resolve-Path -LiteralPath $LabRoot).Path
$resolvedTarget = (Resolve-Path -LiteralPath $TargetRepositoryPath).Path
if (-not (Test-Path -LiteralPath (Join-Path $resolvedLab "pyproject.toml") -PathType Leaf)) {
    throw "LabRoot does not identify Godot Game Test Lab: $resolvedLab"
}
if (-not (Test-Path -LiteralPath $resolvedTarget -PathType Container)) {
    throw "TargetRepositoryPath must be a directory."
}
if ($GodotVersion -notmatch '^4\.[0-9]+\.[0-9]+$') {
    throw "GodotVersion must be an explicit stable Godot 4.x.y version."
}
$docker = Get-Command docker -ErrorAction SilentlyContinue
if (-not $docker) {
    throw "Docker Desktop is required for the no-network Linux sandbox lane."
}
Invoke-Checked $docker.Source version --format '{{.Server.Version}}'

New-Item -ItemType Directory -Force -Path $EvidenceRoot | Out-Null
$resolvedEvidenceRoot = (Resolve-Path -LiteralPath $EvidenceRoot).Path
if (
    (Test-IsWithinPath $resolvedEvidenceRoot $resolvedLab) -or
    (Test-IsWithinPath $resolvedEvidenceRoot $resolvedTarget) -or
    (Test-IsWithinPath $resolvedLab $resolvedEvidenceRoot) -or
    (Test-IsWithinPath $resolvedTarget $resolvedEvidenceRoot)
) {
    throw "EvidenceRoot must remain separate from both source repositories."
}
if (-not $ArtifactPath) {
    $stamp = [DateTimeOffset]::UtcNow.ToString("yyyyMMddTHHmmssZ")
    $ArtifactPath = Join-Path $resolvedEvidenceRoot "sandbox\$([IO.Path]::GetFileName($resolvedTarget))\$stamp"
}
$artifactFull = [IO.Path]::GetFullPath($ArtifactPath)
if (-not (Test-IsWithinPath $artifactFull $resolvedEvidenceRoot)) {
    throw "ArtifactPath must remain beneath EvidenceRoot."
}
if (Test-Path -LiteralPath $artifactFull) {
    if (@(Get-ChildItem -LiteralPath $artifactFull -Force).Count -gt 0) {
        throw "ArtifactPath must be new or empty: $artifactFull"
    }
}
New-Item -ItemType Directory -Force -Path $artifactFull | Out-Null

$beforeSha = Get-GitValue -Root $resolvedTarget -Arguments @("rev-parse", "HEAD") -Optional
$beforeStatus = Get-GitValue -Root $resolvedTarget -Arguments @(
    "status", "--porcelain=v1", "--untracked-files=all"
) -Optional
$labSha = Get-GitValue -Root $resolvedLab -Arguments @("rev-parse", "HEAD") -Optional
if ($ExpectedTargetSha -and $beforeSha -ne $ExpectedTargetSha) {
    throw "Target HEAD $beforeSha does not match ExpectedTargetSha $ExpectedTargetSha."
}
if ($ExpectedLabSha -and $labSha -ne $ExpectedLabSha) {
    throw "Lab HEAD $labSha does not match ExpectedLabSha $ExpectedLabSha."
}

$normalisedProfile = Join-Path $artifactFull "profile.normalized.json"
if ($ProfilePath) {
    $candidate = if ([IO.Path]::IsPathRooted($ProfilePath)) {
        $ProfilePath
    } else {
        Join-Path $resolvedTarget $ProfilePath
    }
    $resolvedProfile = (Resolve-Path -LiteralPath $candidate).Path
    if (-not (Test-IsWithinPath $resolvedProfile $resolvedTarget)) {
        throw "ProfilePath must remain inside the target repository."
    }
    Invoke-LabPython @(
        (Join-Path $resolvedLab "scripts\read_linux_sandbox_profile.py"),
        "--profile", $resolvedProfile,
        "--output", $normalisedProfile
    )
}
else {
    $safeSubpath = $ProjectSubpath.Replace('\', '/').Trim()
    if (
        -not $safeSubpath -or
        $safeSubpath.StartsWith('/') -or
        $safeSubpath.Contains(':') -or
        @($safeSubpath.Split('/') | Where-Object { $_ -eq '..' }).Count -gt 0
    ) {
        throw "ProjectSubpath must be a bounded relative path."
    }
    $generated = [ordered]@{
        schemaVersion = "2.0"
        projectSubpath = $safeSubpath
        minimumGodotVersion = "4.6.2"
        engineFlavor = "auto"
        visual = [ordered]@{
            required = $true
            scene = ""
            frames = 180
            fps = 30
            width = 1280
            height = 720
            renderingMethod = "gl_compatibility"
            userArguments = @()
        }
        export = [ordered]@{ required = $false; preset = "" }
        journeys = @()
    }
    [IO.File]::WriteAllText(
        $normalisedProfile,
        ($generated | ConvertTo-Json -Depth 12) + [Environment]::NewLine,
        [Text.UTF8Encoding]::new($false)
    )
}
$profile = Get-Content -Raw -LiteralPath $normalisedProfile | ConvertFrom-Json
$profileSubpath = [string]$profile.projectSubpath
$projectRoot = if ($profileSubpath -eq ".") {
    $resolvedTarget
} else {
    (Resolve-Path -LiteralPath (Join-Path $resolvedTarget $profileSubpath)).Path
}
if (-not (Test-Path -LiteralPath (Join-Path $projectRoot "project.godot") -PathType Leaf)) {
    throw "The selected projectSubpath does not contain project.godot: $projectRoot"
}
$hasCsharp = $null -ne (
    Get-ChildItem -LiteralPath $projectRoot -Filter *.csproj -File -Recurse `
        -ErrorAction SilentlyContinue | Select-Object -First 1
)
$flavor = [string]$profile.engineFlavor
if ($flavor -eq "auto") {
    $flavor = if ($hasCsharp) { "mono" } else { "standard" }
}
if ($hasCsharp -and $flavor -ne "mono") {
    throw "C# targets require engineFlavor=mono or auto."
}
if ([version]$GodotVersion -lt [version]([string]$profile.minimumGodotVersion)) {
    throw "GodotVersion $GodotVersion is below the profile minimum $($profile.minimumGodotVersion)."
}

$imageTag = "$ImageRepository`:$GodotVersion-$flavor"
& $docker.Source image inspect $imageTag *> $null
$imageExists = $LASTEXITCODE -eq 0
if ($BuildImage -or -not $imageExists) {
    $buildArguments = @(
        "-LabRoot", $resolvedLab,
        "-GodotVersion", $GodotVersion,
        "-Flavor", $flavor,
        "-ImageRepository", $ImageRepository
    )
    if ($NoCache) { $buildArguments += "-NoCache" }
    & (Join-Path $resolvedLab "scripts\Build-GodotLabSandboxes.ps1") @buildArguments
}
Invoke-Checked $docker.Source image inspect $imageTag

$visual = $profile.visual
$visualArgumentsJson = ConvertTo-Json -InputObject @($visual.userArguments) -Compress
$exportPreset = [string]$profile.export.preset
$workRoot = Join-Path ([IO.Path]::GetTempPath()) "godot-lab-sandbox-$([Guid]::NewGuid().ToString('N'))"
New-Item -ItemType Directory -Force -Path $workRoot | Out-Null
$containerName = "evavo-godot-$([Guid]::NewGuid().ToString('N').Substring(0, 12))"
$dispatch = [ordered]@{
    schemaVersion = "1.0"
    status = "dispatched"
    targetRoot = $resolvedTarget
    targetSha = $beforeSha
    labRoot = $resolvedLab
    labSha = $labSha
    projectSubpath = $profileSubpath
    profile = $normalisedProfile
    image = $imageTag
    flavor = $flavor
    godotVersion = $GodotVersion
    network = "none"
    sourceReadOnly = $true
    rootFilesystemReadOnly = $true
    createdAt = [DateTimeOffset]::UtcNow.ToString("o")
}
[IO.File]::WriteAllText(
    (Join-Path $artifactFull "local-sandbox-dispatch.json"),
    ($dispatch | ConvertTo-Json -Depth 10) + [Environment]::NewLine,
    [Text.UTF8Encoding]::new($false)
)

try {
    $arguments = @(
        "run", "--rm",
        "--name", $containerName,
        "--stop-timeout", "10",
        "--network", "none",
        "--read-only",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--pids-limit", "1024",
        "--cpus", [string]$CpuCount,
        "--memory", $Memory,
        "--memory-swap", $Memory,
        "--ulimit", "nofile=4096:4096",
        "--shm-size", "1g",
        "--tmpfs", "/tmp:rw,nosuid,nodev,noexec,size=1g,mode=1777",
        "--tmpfs", "/home/godotlab:rw,nosuid,nodev,size=2g,mode=0700,uid=10001,gid=10001",
        "--mount", "type=bind,source=$resolvedTarget,target=/workspace/source,readonly",
        "--mount", "type=bind,source=$normalisedProfile,target=/workspace/profile.normalized.json,readonly",
        "--mount", "type=bind,source=$workRoot,target=/workspace/work",
        "--mount", "type=bind,source=$artifactFull,target=/artifacts",
        "--env", "EVAVO_TARGET_REPOSITORY=local/$([IO.Path]::GetFileName($resolvedTarget))",
        "--env", "EVAVO_TARGET_SHA=$beforeSha",
        "--env", "EVAVO_LAB_SHA=$labSha",
        "--env", "EVAVO_PROFILE_PATH=/workspace/profile.normalized.json",
        "--env", "EVAVO_PROJECT_SUBPATH=$profileSubpath",
        "--env", "EVAVO_MINIMUM_GODOT_VERSION=$($profile.minimumGodotVersion)",
        "--env", "EVAVO_TIMEOUT_SECONDS=$TimeoutSeconds",
        "--env", "EVAVO_BOOT_FRAMES=$BootFrames",
        "--env", "EVAVO_VISUAL_SCENE=$($visual.scene)",
        "--env", "EVAVO_VISUAL_FRAMES=$($visual.frames)",
        "--env", "EVAVO_VISUAL_FPS=$($visual.fps)",
        "--env", "EVAVO_VISUAL_WIDTH=$($visual.width)",
        "--env", "EVAVO_VISUAL_HEIGHT=$($visual.height)",
        "--env", "EVAVO_RENDERING_METHOD=$($visual.renderingMethod)",
        "--env", "EVAVO_VISUAL_ARGUMENTS_JSON=$visualArgumentsJson",
        "--env", "EVAVO_EXPORT_PRESET=$exportPreset",
        $imageTag
    )
    & $docker.Source @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Godot Linux sandbox exited with code $LASTEXITCODE. Review $artifactFull."
    }
}
finally {
    & $docker.Source rm -f $containerName *> $null
    Remove-Item -LiteralPath $workRoot -Recurse -Force -ErrorAction SilentlyContinue
    $afterSha = Get-GitValue -Root $resolvedTarget -Arguments @("rev-parse", "HEAD") -Optional
    $afterStatus = Get-GitValue -Root $resolvedTarget -Arguments @(
        "status", "--porcelain=v1", "--untracked-files=all"
    ) -Optional
    if ($beforeSha -and $afterSha -ne $beforeSha) {
        throw "The sandbox changed the target repository HEAD."
    }
    if ($null -ne $beforeStatus -and $afterStatus -ne $beforeStatus) {
        throw "The sandbox changed the target repository working tree."
    }
}
Write-Host "[godot-lab] Sandbox evidence: $artifactFull"
