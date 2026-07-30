[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$TargetRepositoryPath,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-f]{40}$')]
    [string]$ExpectedLabSha,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-f]{40}$')]
    [string]$ExpectedTargetSha,

    [Parameter(Mandatory = $true)]
    [string]$ArtifactPath,

    [string]$ProjectSubpath = '.',

    [ValidateSet('auto', 'standard', 'mono')]
    [string]$EngineFlavor = 'auto',

    [ValidateRange(0, 1800)]
    [int]$VisualFrames = 180,

    [string]$ExportPreset = ''
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$targetRoot = [IO.Path]::GetFullPath($TargetRepositoryPath)
$artifactRoot = [IO.Path]::GetFullPath($ArtifactPath)
$workRoot = Join-Path ([IO.Path]::GetTempPath()) "evavo-godot-linux-$([Guid]::NewGuid().ToString('N'))"
$imageTag = "evavo-godot-linux:$($PID)-$([DateTimeOffset]::UtcNow.ToUnixTimeSeconds())"

if ($targetRoot -notmatch '^[A-Za-z]:\GitRepos\[^\r\n]+$') {
    throw 'TargetRepositoryPath must be beneath C:\GitRepos.'
}
if ($ProjectSubpath -match '(^[A-Za-z]:)|(^/)|(^|[\\/])\.\.([\\/]|$)|[\r\n]') {
    throw 'ProjectSubpath must be a canonical relative path without traversal.'
}
if (-not (Test-Path -LiteralPath (Join-Path $targetRoot $ProjectSubpath) -PathType Container)) {
    throw 'ProjectSubpath does not exist beneath the target repository.'
}
if (-not (Test-Path -LiteralPath (Join-Path (Join-Path $targetRoot $ProjectSubpath) 'project.godot') -PathType Leaf)) {
    throw 'project.godot is missing at ProjectSubpath.'
}
if ($null -eq (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'Docker Desktop or another compatible Docker engine is required.'
}
if ($null -eq (Get-Command git -ErrorAction SilentlyContinue)) {
    throw 'Git is required to bind the sandbox to exact repository revisions.'
}

$labSha = (& git -C $repoRoot rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $labSha -ne $ExpectedLabSha) {
    throw "Test-lab HEAD $labSha does not match ExpectedLabSha $ExpectedLabSha."
}
$targetSha = (& git -C $targetRoot rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $targetSha -ne $ExpectedTargetSha) {
    throw "Target HEAD $targetSha does not match ExpectedTargetSha $ExpectedTargetSha."
}
$beforeStatus = @(& git -C $targetRoot status --porcelain=v1 --untracked-files=all)
if ($LASTEXITCODE -ne 0 -or $beforeStatus.Count -gt 0) {
    throw 'Target repository must be clean before Linux sandbox validation.'
}

$projectRoot = Join-Path $targetRoot $ProjectSubpath
$detectedFlavor = if (Get-ChildItem -LiteralPath $projectRoot -Recurse -File -Filter '*.csproj' -ErrorAction SilentlyContinue | Select-Object -First 1) { 'mono' } else { 'standard' }
$selectedFlavor = if ($EngineFlavor -eq 'auto') { $detectedFlavor } else { $EngineFlavor }
if ($detectedFlavor -eq 'mono' -and $selectedFlavor -ne 'mono') {
    throw 'C# target requires EngineFlavor mono.'
}

New-Item -ItemType Directory -Force -Path $artifactRoot, $workRoot | Out-Null

try {
    & docker build `
        --pull `
        --build-arg GODOT_VERSION=4.6.2 `
        --build-arg "GODOT_FLAVOR=$selectedFlavor" `
        --tag $imageTag `
        --file (Join-Path $repoRoot 'containers\linux-sandbox\Dockerfile') `
        $repoRoot
    if ($LASTEXITCODE -ne 0) {
        throw 'Linux Godot sandbox image build failed.'
    }

    $runArguments = @(
        'run', '--rm',
        '--network', 'none',
        '--read-only',
        '--cap-drop', 'ALL',
        '--security-opt', 'no-new-privileges',
        '--pids-limit', '2048',
        '--cpus', '4',
        '--memory', '8g',
        '--shm-size', '1g',
        '--tmpfs', '/tmp:rw,nosuid,nodev,noexec,size=1g,mode=1777',
        '--tmpfs', '/home/godotlab:rw,nosuid,nodev,size=2g,mode=0700,uid=10001,gid=10001',
        '--mount', "type=bind,source=$targetRoot,target=/workspace/source,readonly",
        '--mount', "type=bind,source=$workRoot,target=/workspace/work",
        '--mount', "type=bind,source=$artifactRoot,target=/artifacts",
        '--env', 'EVAVO_TARGET_REPOSITORY=local-checkout',
        '--env', "EVAVO_TARGET_SHA=$ExpectedTargetSha",
        '--env', "EVAVO_LAB_SHA=$ExpectedLabSha",
        '--env', "EVAVO_PROJECT_SUBPATH=$ProjectSubpath",
        '--env', "EVAVO_VISUAL_FRAMES=$VisualFrames"
    )
    if (-not [string]::IsNullOrWhiteSpace($ExportPreset)) {
        $runArguments += @('--env', "EVAVO_EXPORT_PRESET=$ExportPreset")
    }
    $runArguments += $imageTag

    & docker @runArguments
    $sandboxExitCode = $LASTEXITCODE

    $afterSha = (& git -C $targetRoot rev-parse HEAD).Trim()
    $afterStatus = @(& git -C $targetRoot status --porcelain=v1 --untracked-files=all)
    if ($afterSha -ne $ExpectedTargetSha -or $afterStatus.Count -gt 0) {
        throw 'Linux sandbox changed the target checkout.'
    }
    if ($sandboxExitCode -ne 0) {
        throw "Linux Godot sandbox reported failure with exit code $sandboxExitCode."
    }
}
finally {
    & docker image rm $imageTag *> $null
    Remove-Item -LiteralPath $workRoot -Recurse -Force -ErrorAction SilentlyContinue
}
