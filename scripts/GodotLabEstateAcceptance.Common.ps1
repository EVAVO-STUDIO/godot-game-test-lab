$script:EstateStrictJsonValidator = [IO.Path]::GetFullPath(
    (Join-Path $PSScriptRoot "..\src\godot_game_test_lab\strict_json.py")
)

function Test-IsWithinPath {
    param([string]$Candidate, [string]$Parent)
    $candidateFull = [IO.Path]::GetFullPath($Candidate).TrimEnd('\', '/')
    $parentFull = [IO.Path]::GetFullPath($Parent).TrimEnd('\', '/')
    return (
        $candidateFull.Equals(
            $parentFull,
            [StringComparison]::OrdinalIgnoreCase
        ) -or
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
    if (Test-Path -LiteralPath $Path) {
        throw "Evidence receipt already exists: $Path"
    }
    $parent = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
        throw "Evidence receipt parent does not exist: $parent"
    }
    Assert-NoReparsePoint -Path $parent
    $temporary = "$Path.tmp-$PID-$([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds())"
    try {
        [IO.File]::WriteAllText(
            $temporary,
            ($Value | ConvertTo-Json -Depth 20) + [Environment]::NewLine,
            [Text.UTF8Encoding]::new($false)
        )
        Move-Item -LiteralPath $temporary -Destination $Path
    }
    finally {
        if (Test-Path -LiteralPath $temporary) {
            Remove-Item -LiteralPath $temporary -Force
        }
    }
}

function Get-FileSha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (
        Get-FileHash -LiteralPath $Path -Algorithm SHA256
    ).Hash.ToLowerInvariant()
}

function Read-StrictJsonFile {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$PythonExecutable,
        [Parameter(Mandatory = $true)][string]$Label,
        [ValidateRange(1, 67108864)]
        [int]$MaximumBytes = 16777216
    )
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Label does not exist: $Path"
    }
    Assert-NoReparsePoint -Path $Path
    if (-not (Test-Path -LiteralPath $script:EstateStrictJsonValidator `
        -PathType Leaf)) {
        throw "The strict JSON validator is missing."
    }
    Assert-NoReparsePoint -Path $script:EstateStrictJsonValidator
    $lines = @(
        & $PythonExecutable $script:EstateStrictJsonValidator `
            --input $Path `
            --maximum-bytes $MaximumBytes 2>&1
    )
    $exitCode = $LASTEXITCODE
    $output = ($lines -join "`n").Trim()
    if ($exitCode -ne 0) {
        throw "$Label failed strict JSON admission: $output"
    }
    try {
        $envelope = $output | ConvertFrom-Json
    }
    catch {
        throw "$Label validator output is not JSON."
    }
    if ([string]$envelope.schemaVersion -ne "1.0" -or
        [string]$envelope.status -ne "passed" -or
        [string]$envelope.sha256 -notmatch '^[0-9a-f]{64}$' -or
        $null -eq $envelope.value) {
        throw "$Label validator output is incomplete."
    }
    return [pscustomobject]@{
        Value = $envelope.value
        Sha256 = [string]$envelope.sha256
    }
}

function Assert-ExactProperties {
    param(
        [Parameter(Mandatory = $true)][object]$Value,
        [Parameter(Mandatory = $true)][string[]]$Expected,
        [Parameter(Mandatory = $true)][string]$Label
    )
    if ($null -eq $Value -or $null -eq $Value.PSObject) {
        throw "$Label must be a JSON object."
    }
    $actual = @($Value.PSObject.Properties.Name | Sort-Object)
    $wanted = @($Expected | Sort-Object)
    $difference = @(Compare-Object -ReferenceObject $wanted `
        -DifferenceObject $actual)
    if ($difference.Count -ne 0) {
        throw "$Label must contain exactly: $($wanted -join ', ')."
    }
}

function Get-NormalizedPathIdentity {
    param([Parameter(Mandatory = $true)][string]$Path)
    return [IO.Path]::GetFullPath($Path).TrimEnd('\', '/').ToLowerInvariant()
}

function Test-PathSetExact {
    param(
        [object[]]$Observed,
        [string[]]$Expected
    )
    try {
        $observedIds = @(
            $Observed |
                ForEach-Object { Get-NormalizedPathIdentity -Path ([string]$_) } |
                Sort-Object -Unique
        )
        $expectedIds = @(
            $Expected |
                ForEach-Object { Get-NormalizedPathIdentity -Path $_ } |
                Sort-Object -Unique
        )
        if ($observedIds.Count -ne $expectedIds.Count) {
            return $false
        }
        for ($index = 0; $index -lt $expectedIds.Count; $index++) {
            if ($observedIds[$index] -ne $expectedIds[$index]) {
                return $false
            }
        }
        return $true
    }
    catch {
        return $false
    }
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
    if ([IO.Path]::IsPathRooted($SuppliedPath)) {
        throw "$Label must be repository-relative."
    }
    $relative = $SuppliedPath.Replace('\', '/')
    $relativePattern = `
        '^[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*$'
    if ($relative -notmatch $relativePattern -or
        $relative -match '(^|/)\.\.(/|$)') {
        throw "$Label must be a traversal-free repository-relative path."
    }
    $candidate = [IO.Path]::GetFullPath((Join-Path $RepositoryPath $relative))
    if (-not (Test-IsWithinPath -Candidate $candidate -Parent $RepositoryPath)) {
        throw "$Label must remain within the target repository."
    }
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
        throw "$Label does not exist: $candidate"
    }
    Assert-NoReparsePoint -Path $candidate
    $resolved = (Resolve-Path -LiteralPath $candidate).Path
    $null = Get-GitText -Root $RepositoryPath -Arguments @(
        "ls-files",
        "--error-unmatch",
        "--",
        $relative
    ) -Label "Verify tracked $Label"
    return $resolved
}

function Get-HostReceiptPaths {
    param([string]$Root)
    $hostRoot = Join-Path $Root "host-acceptance"
    if (-not (Test-Path -LiteralPath $hostRoot -PathType Container)) {
        return @()
    }
    Assert-NoReparsePoint -Path $hostRoot
    $paths = @(
        Get-ChildItem -LiteralPath $hostRoot `
            -Filter "host-acceptance.json" `
            -File -Recurse -Force |
            Select-Object -First 10001 |
            ForEach-Object { $_.FullName }
    )
    if ($paths.Count -gt 10000) {
        throw "Host acceptance evidence contains more than 10000 receipts."
    }
    return $paths
}

function Get-RequiredHostStageIds {
    param([string]$AcceptanceMode)
    $ids = @(
        "toolchain",
        "managed-engines",
        "doctor",
        "mcp-self-test",
        "hardware",
        "worker-protocol-acceptance",
        "target-validation"
    )
    if ($AcceptanceMode -in @("native", "all")) {
        $ids += "target-native-journey"
    }
    if ($AcceptanceMode -in @("bot", "all")) {
        $ids += "target-bot-journey"
    }
    return $ids
}
