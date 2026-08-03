[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ManifestPath,
    [string]$LabRoot = "",
    [string[]]$AllowedTargetRoots = @("C:\GitRepos"),
    [string]$EvidenceRoot = "C:\GodotLabEvidence",
    [string]$EngineRoot = "$env:LOCALAPPDATA\EVAVO\GodotGameTestLab\engines",
    [string]$TaskName = "EVAVO Godot Game Test Lab MCP",
    [ValidateRange(1, 65535)]
    [int]$Port = 8765,
    [ValidateRange(1, 120)]
    [int]$WorkerStartupTimeoutSeconds = 30,
    [string]$ExpectedLabSha = "",
    [switch]$EngineOffline,
    [switch]$RegisterWorker,
    [switch]$StartWorker
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Test-IsWithinPath {
    param([string]$Candidate, [string]$Parent)
    $candidateFull = [IO.Path]::GetFullPath($Candidate).TrimEnd('\', '/')
    $parentFull = [IO.Path]::GetFullPath($Parent).TrimEnd('\', '/')
    return (
        $candidateFull.Equals($parentFull, [StringComparison]::OrdinalIgnoreCase) -or
        $candidateFull.StartsWith(
            $parentFull + [IO.Path]::DirectorySeparatorChar,
            [StringComparison]::OrdinalIgnoreCase
        )
    )
}

function Test-PathsOverlap {
    param([string]$Left, [string]$Right)
    return (
        (Test-IsWithinPath -Candidate $Left -Parent $Right) -or
        (Test-IsWithinPath -Candidate $Right -Parent $Left)
    )
}

function Assert-NoReparsePoint {
    param([Parameter(Mandatory = $true)][string]$Path)
    $item = Get-Item -LiteralPath $Path -Force
    while ($null -ne $item) {
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Path traverses a reparse point: $Path"
        }
        $item = $item.Parent
    }
}

function Assert-NoReparsePointForCandidate {
    param([Parameter(Mandatory = $true)][string]$Path)
    $cursor = [IO.Path]::GetFullPath($Path)
    while (-not (Test-Path -LiteralPath $cursor)) {
        $parent = [IO.Directory]::GetParent($cursor)
        if ($null -eq $parent) {
            return
        }
        $cursor = $parent.FullName
    }
    Assert-NoReparsePoint -Path $cursor
}

function Get-GitText {
    param([string]$Root, [string[]]$Arguments, [string]$Label)
    $lines = @(& git -C $Root @Arguments 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed: $($lines -join [Environment]::NewLine)"
    }
    return ($lines -join "`n").TrimEnd()
}

function Get-GitLines {
    param([string]$Root, [string[]]$Arguments, [string]$Label)
    $lines = @(& git -C $Root @Arguments 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed: $($lines -join [Environment]::NewLine)"
    }
    return @($lines | ForEach-Object { [string]$_ })
}

function Write-AtomicJson {
    param([string]$Path, [object]$Value)
    $temporary = "$Path.tmp-$PID-$([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds())"
    [IO.File]::WriteAllText(
        $temporary,
        ($Value | ConvertTo-Json -Depth 16) + [Environment]::NewLine,
        [Text.UTF8Encoding]::new($false)
    )
    Move-Item -LiteralPath $temporary -Destination $Path -Force
}

function Resolve-TargetOwnedFile {
    param(
        [string]$RepositoryPath,
        [string]$SuppliedPath,
        [string]$Label
    )
    if (-not $SuppliedPath) {
        throw "$Label is required."
    }
    $candidate = if ([IO.Path]::IsPathRooted($SuppliedPath)) {
        [IO.Path]::GetFullPath($SuppliedPath)
    }
    else {
        [IO.Path]::GetFullPath((Join-Path $RepositoryPath $SuppliedPath))
    }
    if (-not (Test-IsWithinPath -Candidate $candidate -Parent $RepositoryPath)) {
        throw "$Label must remain within the target repository."
    }
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
        throw "$Label does not exist: $candidate"
    }
    Assert-NoReparsePoint -Path $candidate
    return (Resolve-Path -LiteralPath $candidate).Path
}

function Get-HostReceiptPaths {
    param([string]$Root)
    $hostRoot = Join-Path $Root "host-acceptance"
    if (-not (Test-Path -LiteralPath $hostRoot -PathType Container)) {
        return @()
    }
    return @(
        Get-ChildItem -LiteralPath $hostRoot -Filter "host-acceptance.json" `
            -File -Recurse -Force |
            ForEach-Object { $_.FullName }
    )
}

function Get-ProjectFileInventory {
    param([string]$RepositoryPath, [string]$ProjectSubpath)
    $allFiles = Get-GitLines -Root $RepositoryPath -Arguments @("ls-files") `
        -Label "Read tracked project files"
    $normalized = $ProjectSubpath.Replace('\', '/').Trim('/')
    if (-not $normalized -or $normalized -eq ".") {
        return $allFiles
    }
    $prefix = "$normalized/"
    return @($allFiles | Where-Object {
        $_ -eq $normalized -or $_.StartsWith($prefix, [StringComparison]::Ordinal)
    })
}

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw "Estate acceptance must run on Windows."
}
if (-not $LabRoot) {
    $LabRoot = Split-Path -Parent $PSScriptRoot
}
$lab = (Resolve-Path -LiteralPath $LabRoot).Path
Assert-NoReparsePoint -Path $lab
$hostAcceptance = Join-Path $lab "scripts\Test-GodotLabAgentHost.ps1"
if (-not (Test-Path -LiteralPath $hostAcceptance -PathType Leaf)) {
    throw "The governed host acceptance script is missing: $hostAcceptance"
}
$python = Join-Path $lab ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Run scripts\Initialize-GodotLabAgentHost.ps1 before estate acceptance."
}
Assert-NoReparsePoint -Path $python

$manifestFile = (Resolve-Path -LiteralPath $ManifestPath).Path
Assert-NoReparsePoint -Path $manifestFile
try {
    $manifest = Get-Content -Raw -LiteralPath $manifestFile | ConvertFrom-Json
}
catch {
    throw "Estate acceptance manifest is not valid JSON: $($_.Exception.Message)"
}
if ([string]$manifest.schemaVersion -ne "1.0") {
    throw "Estate acceptance manifest schemaVersion must be 1.0."
}
$entries = @($manifest.targets)
if ($entries.Count -lt 2 -or $entries.Count -gt 16) {
    throw "Estate acceptance requires between 2 and 16 targets."
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

$labSha = Get-GitText -Root $lab -Arguments @("rev-parse", "HEAD") `
    -Label "Resolve Lab SHA"
if (-not $ExpectedLabSha) {
    $ExpectedLabSha = $labSha
}
if ($ExpectedLabSha -notmatch '^[0-9a-f]{40}$' -or $labSha -ne $ExpectedLabSha) {
    throw "The Lab checkout does not match ExpectedLabSha."
}
$labStatusBefore = Get-GitText -Root $lab -Arguments @(
    "status", "--porcelain=v1", "--untracked-files=all"
) -Label "Read Lab status before estate acceptance"
if ($labStatusBefore) {
    throw "The Lab checkout must be completely clean before estate acceptance."
}

$requiredProperties = @(
    "id",
    "repositoryPath",
    "expectedSha",
    "projectSubpath",
    "expectedProjectKind",
    "acceptanceMode",
    "nativeProfilePath",
    "botProfilePath"
)
$seenIds = [Collections.Generic.HashSet[string]]::new(
    [StringComparer]::OrdinalIgnoreCase
)
$targets = [Collections.ArrayList]::new()
foreach ($entry in $entries) {
    foreach ($property in $requiredProperties) {
        if ($entry.PSObject.Properties.Name -notcontains $property) {
            throw "Every target must define $property."
        }
    }

    $id = [string]$entry.id
    if ($id -notmatch '^[a-z0-9][a-z0-9._-]{0,63}$') {
        throw "Target id must be a lowercase stable identifier: $id"
    }
    if (-not $seenIds.Add($id)) {
        throw "Target ids must be unique: $id"
    }

    $expectedSha = ([string]$entry.expectedSha).ToLowerInvariant()
    if ($expectedSha -notmatch '^[0-9a-f]{40}$') {
        throw "Target $id must declare an exact 40-character expectedSha."
    }
    $projectKind = ([string]$entry.expectedProjectKind).ToLowerInvariant()
    if ($projectKind -notin @("gdscript", "csharp")) {
        throw "Target $id expectedProjectKind must be gdscript or csharp."
    }
    $mode = ([string]$entry.acceptanceMode).ToLowerInvariant()
    if ($mode -notin @("validate", "native", "bot", "all")) {
        throw "Target $id acceptanceMode must be validate, native, bot, or all."
    }

    $repository = (Resolve-Path -LiteralPath ([string]$entry.repositoryPath)).Path
    Assert-NoReparsePoint -Path $repository
    $insideAllowedRoot = $false
    foreach ($root in $resolvedRoots) {
        if (Test-IsWithinPath -Candidate $repository -Parent $root) {
            $insideAllowedRoot = $true
            break
        }
    }
    if (-not $insideAllowedRoot) {
        throw "Target $id is outside every allowed target root."
    }
    if (Test-PathsOverlap -Left $repository -Right $lab) {
        throw "Target $id must remain disjoint from the Lab checkout."
    }
    $topLevel = Get-GitText -Root $repository -Arguments @(
        "rev-parse", "--show-toplevel"
    ) -Label "Resolve target $id repository root"
    if (-not $repository.Equals(
        (Resolve-Path -LiteralPath $topLevel).Path,
        [StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Target $id repositoryPath must be the Git top-level directory."
    }
    $actualSha = Get-GitText -Root $repository -Arguments @(
        "rev-parse", "HEAD"
    ) -Label "Resolve target $id SHA"
    if ($actualSha -ne $expectedSha) {
        throw "Target $id does not match its expectedSha."
    }
    $statusBefore = Get-GitText -Root $repository -Arguments @(
        "status", "--porcelain=v1", "--untracked-files=all"
    ) -Label "Read target $id status"
    if ($statusBefore) {
        throw "Target $id must be completely clean before estate acceptance."
    }

    $projectSubpath = [string]$entry.projectSubpath
    if (-not $projectSubpath) {
        throw "Target $id projectSubpath cannot be empty."
    }
    if ([IO.Path]::IsPathRooted($projectSubpath)) {
        throw "Target $id projectSubpath must be repository-relative."
    }
    $project = [IO.Path]::GetFullPath((Join-Path $repository $projectSubpath))
    if (-not (Test-IsWithinPath -Candidate $project -Parent $repository)) {
        throw "Target $id projectSubpath escapes the repository."
    }
    if (-not (Test-Path -LiteralPath $project -PathType Container)) {
        throw "Target $id projectSubpath does not exist."
    }
    Assert-NoReparsePoint -Path $project
    if (-not (Test-Path -LiteralPath (Join-Path $project "project.godot") -PathType Leaf)) {
        throw "Target $id projectSubpath does not contain project.godot."
    }

    $projectFiles = Get-ProjectFileInventory -RepositoryPath $repository `
        -ProjectSubpath $projectSubpath
    $hasCsproj = @($projectFiles | Where-Object { $_ -match '\.csproj$' }).Count -gt 0
    $hasCSharp = @($projectFiles | Where-Object { $_ -match '\.cs$' }).Count -gt 0
    $hasGdscript = @($projectFiles | Where-Object { $_ -match '\.gd$' }).Count -gt 0
    if ($projectKind -eq "csharp" -and (-not $hasCsproj -or -not $hasCSharp)) {
        throw "Target $id is declared csharp but lacks tracked .csproj or .cs files."
    }
    if ($projectKind -eq "gdscript" -and (-not $hasGdscript -or $hasCsproj)) {
        throw "Target $id is declared gdscript but is not a pure tracked GDScript project."
    }

    $nativeProfile = ""
    $botProfile = ""
    if ($mode -in @("native", "all")) {
        $nativeProfile = Resolve-TargetOwnedFile -RepositoryPath $repository `
            -SuppliedPath ([string]$entry.nativeProfilePath) `
            -Label "Target $id nativeProfilePath"
    }
    elseif ([string]$entry.nativeProfilePath) {
        throw "Target $id supplies nativeProfilePath without native acceptance."
    }
    if ($mode -in @("bot", "all")) {
        $botProfile = Resolve-TargetOwnedFile -RepositoryPath $repository `
            -SuppliedPath ([string]$entry.botProfilePath) `
            -Label "Target $id botProfilePath"
    }
    elseif ([string]$entry.botProfilePath) {
        throw "Target $id supplies botProfilePath without bot acceptance."
    }

    [void]$targets.Add([ordered]@{
        id = $id
        repositoryPath = $repository
        expectedSha = $expectedSha
        projectSubpath = $projectSubpath
        expectedProjectKind = $projectKind
        acceptanceMode = $mode
        nativeProfilePath = $nativeProfile
        botProfilePath = $botProfile
    })
}

$kinds = @($targets | ForEach-Object { $_.expectedProjectKind } | Sort-Object -Unique)
if ($kinds -notcontains "gdscript" -or $kinds -notcontains "csharp") {
    throw "Estate acceptance requires at least one GDScript target and one C# target."
}
$modes = @($targets | ForEach-Object { $_.acceptanceMode })
if (-not ($modes | Where-Object { $_ -in @("native", "all") })) {
    throw "Estate acceptance requires at least one native visible journey."
}
if (-not ($modes | Where-Object { $_ -in @("bot", "all") })) {
    throw "Estate acceptance requires at least one deterministic bot journey."
}

New-Item -ItemType Directory -Force -Path $candidateEvidence, $candidateEngine |
    Out-Null
$evidence = (Resolve-Path -LiteralPath $candidateEvidence).Path
$engines = (Resolve-Path -LiteralPath $candidateEngine).Path
Assert-NoReparsePoint -Path $evidence
Assert-NoReparsePoint -Path $engines
if (Test-PathsOverlap -Left $evidence -Right $lab) {
    throw "EvidenceRoot must remain disjoint from the Lab checkout."
}
foreach ($root in $resolvedRoots) {
    if (Test-PathsOverlap -Left $evidence -Right $root) {
        throw "EvidenceRoot must remain disjoint from every allowed target root."
    }
}
foreach ($protected in @($lab, $evidence) + @($resolvedRoots)) {
    if (Test-PathsOverlap -Left $engines -Right $protected) {
        throw "EngineRoot must remain disjoint from Lab, target, and evidence roots."
    }
}

$stamp = [DateTimeOffset]::UtcNow.ToString("yyyyMMdd-HHmmssfff")
$runRoot = Join-Path $evidence "estate-acceptance\$stamp"
New-Item -ItemType Directory -Path $runRoot | Out-Null
$receiptPath = Join-Path $runRoot "estate-acceptance.json"
$targetResults = [Collections.ArrayList]::new()
$receipt = [ordered]@{
    schemaVersion = "1.0"
    status = "running"
    startedAt = [DateTimeOffset]::UtcNow.ToString("o")
    labRoot = $lab
    labSha = $labSha
    manifestPath = $manifestFile
    manifestSha256 = $(
        (Get-FileHash -LiteralPath $manifestFile -Algorithm SHA256).Hash.ToLowerInvariant()
    )
    evidenceRoot = $evidence
    engineRoot = $engines
    runRoot = $runRoot
    allowedTargetRoots = @($resolvedRoots)
    engineOffline = [bool]$EngineOffline
    protocolProbeTargetId = $targets[0].id
    targets = $targetResults
}
$failure = $null

try {
    for ($index = 0; $index -lt $targets.Count; $index++) {
        $target = $targets[$index]
        $targetResult = [ordered]@{
            id = $target.id
            repositoryPath = $target.repositoryPath
            expectedSha = $target.expectedSha
            expectedProjectKind = $target.expectedProjectKind
            acceptanceMode = $target.acceptanceMode
            status = "running"
            startedAt = [DateTimeOffset]::UtcNow.ToString("o")
        }
        [void]$targetResults.Add($targetResult)
        $beforeReceipts = [Collections.Generic.HashSet[string]]::new(
            [StringComparer]::OrdinalIgnoreCase
        )
        foreach ($path in (Get-HostReceiptPaths -Root $evidence)) {
            [void]$beforeReceipts.Add($path)
        }

        try {
            $parameters = @{
                LabRoot = $lab
                AllowedTargetRoots = @($resolvedRoots)
                EvidenceRoot = $evidence
                EngineRoot = $engines
                TaskName = $TaskName
                Port = $Port
                WorkerStartupTimeoutSeconds = $WorkerStartupTimeoutSeconds
                ExpectedLabSha = $labSha
                AcceptanceRepositoryPath = $target.repositoryPath
                ExpectedTargetSha = $target.expectedSha
                ProjectSubpath = $target.projectSubpath
                AcceptanceMode = $target.acceptanceMode
            }
            if ($target.nativeProfilePath) {
                $parameters.NativeProfilePath = $target.nativeProfilePath
            }
            if ($target.botProfilePath) {
                $parameters.BotProfilePath = $target.botProfilePath
            }
            if ($EngineOffline) {
                $parameters.EngineOffline = $true
            }
            if ($index -eq 0) {
                if ($RegisterWorker) { $parameters.RegisterWorker = $true }
                if ($StartWorker) { $parameters.StartWorker = $true }
            }
            else {
                $parameters.SkipWorkerProbe = $true
            }

            Write-Host "[godot-lab] Estate target $($target.id): $($target.acceptanceMode)"
            & $hostAcceptance @parameters

            $newReceipts = @(
                Get-HostReceiptPaths -Root $evidence |
                    Where-Object { -not $beforeReceipts.Contains($_) }
            )
            if ($newReceipts.Count -ne 1) {
                throw "Target $($target.id) did not create exactly one host receipt."
            }
            $hostReceiptPath = $newReceipts[0]
            if (-not (Test-IsWithinPath -Candidate $hostReceiptPath -Parent $evidence)) {
                throw "Target $($target.id) host receipt escaped EvidenceRoot."
            }
            $hostReceipt = Get-Content -Raw -LiteralPath $hostReceiptPath |
                ConvertFrom-Json
            if ([string]$hostReceipt.status -ne "passed" -or
                [string]$hostReceipt.labSha -ne $labSha) {
                throw "Target $($target.id) host receipt is not an accepted Lab run."
            }

            $shaAfter = Get-GitText -Root $target.repositoryPath -Arguments @(
                "rev-parse", "HEAD"
            ) -Label "Recheck target $($target.id) SHA"
            $statusAfter = Get-GitText -Root $target.repositoryPath -Arguments @(
                "status", "--porcelain=v1", "--untracked-files=all"
            ) -Label "Recheck target $($target.id) status"
            if ($shaAfter -ne $target.expectedSha -or $statusAfter) {
                throw "Target $($target.id) changed during estate acceptance."
            }

            $targetResult.status = "passed"
            $targetResult.hostReceipt = $hostReceiptPath
            $targetResult.hostRunRoot = [string]$hostReceipt.runRoot
            $targetResult.workerProtocolProbed = ($index -eq 0)
        }
        catch {
            $targetResult.status = "failed"
            $targetResult.error = $_.Exception.Message
            throw
        }
        finally {
            $targetResult.finishedAt = [DateTimeOffset]::UtcNow.ToString("o")
        }
    }

    $labShaAfter = Get-GitText -Root $lab -Arguments @(
        "rev-parse", "HEAD"
    ) -Label "Recheck Lab SHA"
    $labStatusAfter = Get-GitText -Root $lab -Arguments @(
        "status", "--porcelain=v1", "--untracked-files=all"
    ) -Label "Recheck Lab status"
    if ($labShaAfter -ne $labSha -or $labStatusAfter) {
        throw "The Lab checkout changed during estate acceptance."
    }
    $receipt.status = "passed"
}
catch {
    $failure = $_.Exception
    $receipt.status = "failed"
    $receipt.error = $failure.Message
}
finally {
    $receipt.finishedAt = [DateTimeOffset]::UtcNow.ToString("o")
    Write-AtomicJson -Path $receiptPath -Value $receipt
}

if ($failure) {
    throw $failure
}
Write-Host "[godot-lab] Estate acceptance passed. Receipt: $receiptPath"
