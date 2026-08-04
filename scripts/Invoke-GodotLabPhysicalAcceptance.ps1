[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$GdscriptRepositoryPath,

    [Parameter(Mandatory = $true)]
    [string]$CSharpRepositoryPath,

    [Parameter(Mandatory = $true)]
    [string]$NativeProfilePath,

    [Parameter(Mandatory = $true)]
    [string]$BotProfilePath,

    [string]$GdscriptProjectSubpath = ".",
    [string]$CSharpProjectSubpath = ".",
    [string]$LabRoot = "",
    [string[]]$AllowedTargetRoots = @("C:\GitRepos"),
    [string]$EvidenceRoot = "C:\GodotLabEvidence",
    [string]$EngineRoot = "$env:LOCALAPPDATA\EVAVO\GodotGameTestLab\engines",
    [string]$TaskName = "EVAVO Godot Game Test Lab MCP",
    [ValidateRange(1, 65535)]
    [int]$Port = 8765,
    [ValidateRange(1, 120)]
    [int]$WorkerStartupTimeoutSeconds = 30,
    [ValidateRange(1, 600)]
    [int]$EstateLockTimeoutSeconds = 30,
    [string]$ExpectedLabSha = "",
    [string]$EngineVersion = "4.6.3",
    [switch]$InitializeHost,
    [switch]$PrepareLinuxSandboxImages,
    [bool]$InstallPrerequisites = $true,
    [bool]$RequireFullMediaToolchain = $true,
    [bool]$RegisterWorker = $true,
    [bool]$StartWorker = $true,
    [switch]$EngineOffline
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw "Physical estate acceptance must run on Windows."
}
if ($PrepareLinuxSandboxImages -and -not $InitializeHost) {
    throw "PrepareLinuxSandboxImages requires InitializeHost."
}
if (-not $LabRoot) {
    $LabRoot = Split-Path -Parent $PSScriptRoot
}

$common = Join-Path $PSScriptRoot "GodotLabEstateAcceptance.Common.ps1"
if (-not (Test-Path -LiteralPath $common -PathType Leaf)) {
    throw "The governed estate common module is missing: $common"
}
. $common

function Resolve-ExactRepository {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][string[]]$AllowedRoots
    )

    $repository = (Resolve-Path -LiteralPath $Path).Path
    Assert-NoReparsePoint -Path $repository
    $topLevel = Get-GitText -Root $repository -Arguments @(
        "rev-parse",
        "--show-toplevel"
    ) -Label "Resolve $Label Git root"
    $topLevel = (Resolve-Path -LiteralPath $topLevel).Path
    if (-not $repository.Equals(
        $topLevel,
        [StringComparison]::OrdinalIgnoreCase
    )) {
        throw "$Label must identify the Git top-level directory."
    }

    $allowed = $false
    foreach ($root in $AllowedRoots) {
        if (Test-IsWithinPath -Candidate $repository -Parent $root) {
            $allowed = $true
            break
        }
    }
    if (-not $allowed) {
        throw "$Label is outside every AllowedTargetRoots value."
    }

    $sha = Get-GitText -Root $repository -Arguments @(
        "rev-parse",
        "HEAD"
    ) -Label "Resolve $Label SHA"
    if ($sha -notmatch '^[0-9a-f]{40}$') {
        throw "$Label does not expose an exact lowercase commit SHA."
    }
    $status = Get-GitText -Root $repository -Arguments @(
        "status",
        "--porcelain=v1",
        "--untracked-files=all"
    ) -Label "Read $Label status"
    if ($status) {
        throw "$Label must be completely clean before physical acceptance."
    }

    return [pscustomobject]@{
        Path = $repository
        Sha = $sha
    }
}

function Resolve-ManifestProfilePath {
    param(
        [Parameter(Mandatory = $true)][string]$RepositoryPath,
        [Parameter(Mandatory = $true)][string]$SuppliedPath,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $null = Resolve-TargetOwnedFile -RepositoryPath $RepositoryPath `
        -SuppliedPath $SuppliedPath `
        -Label $Label
    return $SuppliedPath.Replace('\', '/')
}

$lab = (Resolve-Path -LiteralPath $LabRoot).Path
Assert-NoReparsePoint -Path $lab
$estate = Join-Path $lab "scripts\Invoke-GodotLabEstateAcceptance.ps1"
$initializer = Join-Path $lab "scripts\Initialize-GodotLabAgentHost.ps1"
foreach ($scriptPath in @($estate, $initializer)) {
    if (-not (Test-Path -LiteralPath $scriptPath -PathType Leaf)) {
        throw "Required physical-acceptance script is missing: $scriptPath"
    }
    Assert-NoReparsePoint -Path $scriptPath
}

$labSha = Get-GitText -Root $lab -Arguments @(
    "rev-parse",
    "HEAD"
) -Label "Resolve Lab SHA"
if (-not $ExpectedLabSha) {
    $ExpectedLabSha = $labSha
}
if ($ExpectedLabSha -notmatch '^[0-9a-f]{40}$' -or
    $ExpectedLabSha -ne $labSha) {
    throw "The Lab checkout does not match ExpectedLabSha."
}
$labStatus = Get-GitText -Root $lab -Arguments @(
    "status",
    "--porcelain=v1",
    "--untracked-files=all"
) -Label "Read complete Lab status"
if ($labStatus) {
    throw "The Lab checkout must be completely clean before physical acceptance."
}

$resolvedRoots = [Collections.Generic.List[string]]::new()
$seenRoots = [Collections.Generic.HashSet[string]]::new(
    [StringComparer]::OrdinalIgnoreCase
)
foreach ($targetRoot in $AllowedTargetRoots) {
    $resolved = (Resolve-Path -LiteralPath $targetRoot).Path
    Assert-NoReparsePoint -Path $resolved
    if ($seenRoots.Add($resolved)) {
        $resolvedRoots.Add($resolved)
    }
}
if ($resolvedRoots.Count -eq 0) {
    throw "At least one allowed target root is required."
}

$gdscript = Resolve-ExactRepository `
    -Path $GdscriptRepositoryPath `
    -Label "GDScript repository" `
    -AllowedRoots @($resolvedRoots)
$csharp = Resolve-ExactRepository `
    -Path $CSharpRepositoryPath `
    -Label "C# repository" `
    -AllowedRoots @($resolvedRoots)
if ($gdscript.Path.Equals(
    $csharp.Path,
    [StringComparison]::OrdinalIgnoreCase
)) {
    throw "GDScriptRepositoryPath and CSharpRepositoryPath must be different repositories."
}
if ((Test-PathsOverlap -Left $gdscript.Path -Right $lab) -or
    (Test-PathsOverlap -Left $csharp.Path -Right $lab)) {
    throw "Physical acceptance targets must remain disjoint from the Lab checkout."
}

$nativeProfile = Resolve-ManifestProfilePath `
    -RepositoryPath $csharp.Path `
    -SuppliedPath $NativeProfilePath `
    -Label "C# native profile"
$botProfile = Resolve-ManifestProfilePath `
    -RepositoryPath $csharp.Path `
    -SuppliedPath $BotProfilePath `
    -Label "C# bot profile"

$candidateEvidence = [IO.Path]::GetFullPath($EvidenceRoot)
$candidateEngine = [IO.Path]::GetFullPath($EngineRoot)
Assert-NoReparsePointForCandidate -Path $candidateEvidence
Assert-NoReparsePointForCandidate -Path $candidateEngine
if (Test-PathsOverlap -Left $candidateEvidence -Right $lab) {
    throw "EvidenceRoot must remain disjoint from the Lab checkout."
}
foreach ($root in $resolvedRoots) {
    if (Test-PathsOverlap -Left $candidateEvidence -Right $root) {
        throw "EvidenceRoot must remain disjoint from every allowed target root."
    }
}
foreach ($protected in @($lab, $candidateEvidence) + @($resolvedRoots)) {
    if (Test-PathsOverlap -Left $candidateEngine -Right $protected) {
        throw "EngineRoot must remain disjoint from Lab, target, and evidence roots."
    }
}

New-Item -ItemType Directory -Force -Path $candidateEvidence | Out-Null
$evidence = (Resolve-Path -LiteralPath $candidateEvidence).Path
Assert-NoReparsePoint -Path $evidence
$manifestRoot = Join-Path $evidence "estate-manifests"
New-Item -ItemType Directory -Force -Path $manifestRoot | Out-Null
$manifestRoot = (Resolve-Path -LiteralPath $manifestRoot).Path
Assert-NoReparsePoint -Path $manifestRoot

$stamp = [DateTimeOffset]::UtcNow.ToString("yyyyMMdd-HHmmssfff")
$manifestName = "estate-{0}-{1}-{2}.json" -f @(
    $stamp,
    $gdscript.Sha.Substring(0, 12),
    $csharp.Sha.Substring(0, 12)
)
$manifestPath = Join-Path $manifestRoot $manifestName
$manifest = [ordered]@{
    schemaVersion = "1.0"
    targets = @(
        [ordered]@{
            id = "gdscript-game"
            repositoryPath = $gdscript.Path
            expectedSha = $gdscript.Sha
            projectSubpath = $GdscriptProjectSubpath
            expectedProjectKind = "gdscript"
            acceptanceMode = "validate"
            nativeProfilePath = ""
            botProfilePath = ""
        },
        [ordered]@{
            id = "csharp-game"
            repositoryPath = $csharp.Path
            expectedSha = $csharp.Sha
            projectSubpath = $CSharpProjectSubpath
            expectedProjectKind = "csharp"
            acceptanceMode = "all"
            nativeProfilePath = $nativeProfile
            botProfilePath = $botProfile
        }
    )
}
Write-AtomicJson -Path $manifestPath -Value $manifest
Write-Host "[godot-lab] Physical acceptance manifest: $manifestPath"

$hostPreparedByInitializer = $false
if ($InitializeHost) {
    $initializeParameters = @{
        LabRoot = $lab
        TargetRoot = $resolvedRoots[0]
        AdditionalTargetRoots = @($resolvedRoots | Select-Object -Skip 1)
        EvidenceRoot = $evidence
        EngineRoot = $candidateEngine
        EngineVersion = $EngineVersion
        TaskName = $TaskName
        Port = $Port
        PrepareEstate = $true
        InstallPrerequisites = $InstallPrerequisites
        RequireFullMediaToolchain = $RequireFullMediaToolchain
    }
    if ($PrepareLinuxSandboxImages) {
        $initializeParameters.PrepareLinuxSandboxImages = $true
    }
    if ($EngineOffline) {
        $initializeParameters.EngineOffline = $true
    }
    Write-Host "[godot-lab] Initializing and accepting the governed Windows host."
    & $initializer @initializeParameters
    $hostPreparedByInitializer = $true
}

$estateParameters = @{
    ManifestPath = $manifestPath
    LabRoot = $lab
    AllowedTargetRoots = @($resolvedRoots)
    EvidenceRoot = $evidence
    EngineRoot = $candidateEngine
    TaskName = $TaskName
    Port = $Port
    WorkerStartupTimeoutSeconds = $WorkerStartupTimeoutSeconds
    EstateLockTimeoutSeconds = $EstateLockTimeoutSeconds
    ExpectedLabSha = $labSha
}
if ($hostPreparedByInitializer) {
    Write-Host (
        "[godot-lab] Reusing the initialized and protocol-accepted scheduled worker; " +
        "the estate will not register or start it a second time."
    )
}
else {
    if ($RegisterWorker) {
        $estateParameters.RegisterWorker = $true
    }
    if ($StartWorker) {
        $estateParameters.StartWorker = $true
    }
}
if ($EngineOffline) {
    $estateParameters.EngineOffline = $true
}

Write-Host "[godot-lab] Running exact GDScript/C# physical estate acceptance."
& $estate @estateParameters
Write-Host "[godot-lab] Physical estate acceptance completed."
