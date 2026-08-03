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
Assert-NoReparsePoint -Path $hostAcceptance
$python = Join-Path $lab ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Run scripts\Initialize-GodotLabAgentHost.ps1 before estate acceptance."
}
Assert-NoReparsePoint -Path $python

$manifestFile = (Resolve-Path -LiteralPath $ManifestPath).Path
Assert-NoReparsePoint -Path $manifestFile
$manifestRecord = Read-StrictJsonFile -Path $manifestFile `
    -PythonExecutable $python `
    -Label "Estate acceptance manifest" `
    -MaximumBytes 1048576
$manifest = $manifestRecord.Value
Assert-ExactProperties -Value $manifest `
    -Expected @("schemaVersion", "targets") `
    -Label "Estate acceptance manifest"
Assert-JsonString -Value $manifest.schemaVersion `
    -Label "Estate acceptance manifest schemaVersion"
Assert-JsonObjectArray -Value $manifest.targets `
    -Label "Estate acceptance manifest targets"
if ($manifest.schemaVersion -ne "1.0") {
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
if ($ExpectedLabSha -notmatch '^[0-9a-f]{40}$' -or
    $labSha -ne $ExpectedLabSha) {
    throw "The Lab checkout does not match ExpectedLabSha."
}
$labStatusBefore = Get-GitText -Root $lab -Arguments @(
    "status",
    "--porcelain=v1",
    "--untracked-files=all"
) -Label "Read Lab status before estate acceptance"
if ($labStatusBefore) {
    throw "The Lab checkout must be completely clean before estate acceptance."
}
if (Test-IsWithinPath -Candidate $manifestFile -Parent $lab) {
    throw "ManifestPath must remain outside the Lab checkout."
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
    Assert-ExactProperties -Value $entry `
        -Expected $requiredProperties `
        -Label "Estate acceptance target"
    foreach ($property in $requiredProperties) {
        Assert-JsonString -Value $entry.$property `
            -Label "Estate acceptance target $property"
    }

    $id = $entry.id
    if ($id -notmatch '^[a-z0-9][a-z0-9._-]{0,63}$') {
        throw "Target id must be a lowercase stable identifier: $id"
    }
    if (-not $seenIds.Add($id)) {
        throw "Target ids must be unique: $id"
    }

    $expectedSha = $entry.expectedSha.ToLowerInvariant()
    if ($expectedSha -notmatch '^[0-9a-f]{40}$') {
        throw "Target $id must declare an exact 40-character expectedSha."
    }
    $projectKind = $entry.expectedProjectKind.ToLowerInvariant()
    if ($projectKind -notin @("gdscript", "csharp")) {
        throw "Target $id expectedProjectKind must be gdscript or csharp."
    }
    $mode = $entry.acceptanceMode.ToLowerInvariant()
    if ($mode -notin @("validate", "native", "bot", "all")) {
        throw "Target $id acceptanceMode must be validate, native, bot, or all."
    }

    $repository = (Resolve-Path -LiteralPath $entry.repositoryPath).Path
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
    if (Test-IsWithinPath -Candidate $manifestFile -Parent $repository) {
        throw "ManifestPath must remain outside target $id."
    }
    $topLevel = Get-GitText -Root $repository -Arguments @(
        "rev-parse",
        "--show-toplevel"
    ) -Label "Resolve target $id repository root"
    if (-not $repository.Equals(
        (Resolve-Path -LiteralPath $topLevel).Path,
        [StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Target $id repositoryPath must be the Git top-level directory."
    }
    $actualSha = Get-GitText -Root $repository -Arguments @(
        "rev-parse",
        "HEAD"
    ) -Label "Resolve target $id SHA"
    if ($actualSha -ne $expectedSha) {
        throw "Target $id does not match its expectedSha."
    }
    $statusBefore = Get-GitText -Root $repository -Arguments @(
        "status",
        "--porcelain=v1",
        "--untracked-files=all"
    ) -Label "Read target $id status"
    if ($statusBefore) {
        throw "Target $id must be completely clean before estate acceptance."
    }

    $projectSubpath = $entry.projectSubpath.Replace('\', '/')
    $projectPattern = `
        '^(?:\.|[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*)$'
    if ($projectSubpath -notmatch $projectPattern -or
        $projectSubpath -match '(^|/)\.\.(/|$)') {
        throw (
            "Target $id projectSubpath must be a traversal-free " +
            "canonical relative path."
        )
    }
    $project = if ($projectSubpath -eq ".") {
        $repository
    }
    else {
        [IO.Path]::GetFullPath((Join-Path $repository $projectSubpath))
    }
    if (-not (Test-IsWithinPath -Candidate $project -Parent $repository)) {
        throw "Target $id projectSubpath escapes the repository."
    }
    if (-not (Test-Path -LiteralPath $project -PathType Container)) {
        throw "Target $id projectSubpath does not exist."
    }
    Assert-NoReparsePoint -Path $project
    if (-not (Test-Path -LiteralPath (Join-Path $project "project.godot") `
        -PathType Leaf)) {
        throw "Target $id projectSubpath does not contain project.godot."
    }

    $projectFiles = Get-ProjectFileInventory -RepositoryPath $repository `
        -ProjectSubpath $projectSubpath
    $hasCsproj = @(
        $projectFiles | Where-Object { $_ -match '\.csproj$' }
    ).Count -gt 0
    $hasCSharp = @(
        $projectFiles | Where-Object { $_ -match '\.cs$' }
    ).Count -gt 0
    $hasGdscript = @(
        $projectFiles | Where-Object { $_ -match '\.gd$' }
    ).Count -gt 0
    if ($projectKind -eq "csharp" -and
        (-not $hasCsproj -or -not $hasCSharp)) {
        throw "Target $id is declared csharp but lacks tracked .csproj or .cs files."
    }
    if ($projectKind -eq "gdscript" -and
        (-not $hasGdscript -or $hasCsproj -or $hasCSharp)) {
        throw (
            "Target $id is declared gdscript but is not a pure tracked " +
            "GDScript project."
        )
    }

    $nativeProfile = ""
    $botProfile = ""
    if ($mode -in @("native", "all")) {
        $nativeProfile = Resolve-TargetOwnedFile -RepositoryPath $repository `
            -SuppliedPath $entry.nativeProfilePath `
            -Label "Target $id nativeProfilePath"
    }
    elseif ($entry.nativeProfilePath) {
        throw "Target $id supplies nativeProfilePath without native acceptance."
    }
    if ($mode -in @("bot", "all")) {
        $botProfile = Resolve-TargetOwnedFile -RepositoryPath $repository `
            -SuppliedPath $entry.botProfilePath `
            -Label "Target $id botProfilePath"
    }
    elseif ($entry.botProfilePath) {
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
        nativeProfileSha256 = if ($nativeProfile) {
            Get-FileSha256 -Path $nativeProfile
        }
        else { $null }
        botProfilePath = $botProfile
        botProfileSha256 = if ($botProfile) {
            Get-FileSha256 -Path $botProfile
        }
        else { $null }
    })
}

$kinds = @(
    $targets |
        ForEach-Object { $_.expectedProjectKind } |
        Sort-Object -Unique
)
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

New-Item -ItemType Directory -Force `
    -Path $candidateEvidence, $candidateEngine | Out-Null
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
$sourceChecks = [Collections.ArrayList]::new()
$receipt = [ordered]@{
    schemaVersion = "1.3"
    status = "running"
    startedAt = [DateTimeOffset]::UtcNow.ToString("o")
    labRoot = $lab
    labSha = $labSha
    manifestPath = $manifestFile
    manifestSha256 = $manifestRecord.Sha256
    strictJsonProfile = "bounded-utf8-unique-names-stable-file-v2"
    receiptTypePolicy = "closed-authority-types-v1"
    preflightLeasePolicy = "global-before-preflight-v1"
    evidenceRoot = $evidence
    engineRoot = $engines
    runRoot = $runRoot
    allowedTargetRoots = @($resolvedRoots)
    engineOffline = [bool]$EngineOffline
    protocolProbePolicy = "every-target"
    estateMutex = "Global\EVAVO.GodotLab.EstateAcceptance"
    targets = $targetResults
    sourceChecks = $sourceChecks
}
