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

function Get-FileSha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
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
