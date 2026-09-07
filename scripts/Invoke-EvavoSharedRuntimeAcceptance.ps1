[CmdletBinding()]
param(
    [string]$GameRuntimePath = "",
    [string]$EngineSystemsPath = "",
    [string]$WebRuntimePath = "",
    [string]$GodotPath = $env:GODOT_BIN,
    [string]$OutputRoot = "",
    [switch]$AllowDirty,
    [switch]$SourceOnly,
    [switch]$SkipWebRuntime
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ($SkipWebRuntime -and -not $SourceOnly) {
    throw "-SkipWebRuntime is only permitted with -SourceOnly; a full acceptance pass must exercise the web runtime."
}
if ($AllowDirty -and -not $SourceOnly) {
    throw "-AllowDirty is only permitted with -SourceOnly; dirty checkouts cannot produce full acceptance evidence."
}

$LabRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$WorkspaceRoot = Split-Path -Parent $LabRoot
if (-not $GameRuntimePath) { $GameRuntimePath = Join-Path $WorkspaceRoot "evavo-game-runtime" }
if (-not $EngineSystemsPath) { $EngineSystemsPath = Join-Path $WorkspaceRoot "godot-engine-systems" }
if (-not $WebRuntimePath) { $WebRuntimePath = Join-Path $WorkspaceRoot "godot-web-runtime" }
if (-not $OutputRoot) { $OutputRoot = Join-Path $LabRoot "artifacts\shared-runtime-acceptance" }

$ExpectedNetworkingContracts = @(
    "res://tests/godot/validate_multiplayer_peer_factory.gd",
    "res://tests/godot/validate_network_clock_profile.gd",
    "res://tests/godot/validate_entity_replication_envelope.gd",
    "res://tests/godot/validate_entity_replication_receive_guard.gd",
    "res://tests/godot/validate_replication_authority_contract.gd",
    "res://tests/godot/validate_replication_visibility_policy.gd",
    "res://tests/godot/validate_partition_handoff_protocol.gd",
    "res://tests/godot/validate_network_state_buffers.gd",
    "res://tests/godot/validate_network_reconciliation_pipeline.gd"
)
$ExpectedNetworkingAggregateMarker = "EVAVO_NETWORKING_CONTRACTS=PASS count=$($ExpectedNetworkingContracts.Count)"

function Resolve-RepositoryEvidence {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Name,
        [switch]$Optional
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        if ($Optional) { return $null }
        throw "$Name repository root not found: $Path"
    }
    $Resolved = (Resolve-Path -LiteralPath $Path).Path
    $Sha = (& git -C $Resolved rev-parse HEAD 2>&1 | Select-Object -First 1).Trim()
    if ($LASTEXITCODE -ne 0 -or $Sha -notmatch '^[0-9a-f]{40}$') {
        throw "Could not resolve exact commit SHA for $Name at $Resolved"
    }
    $Branch = (& git -C $Resolved branch --show-current 2>&1 | Select-Object -First 1).Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($Branch)) {
        throw "Could not resolve current branch for $Name at $Resolved"
    }
    $DirtyLines = @(& git -C $Resolved status --porcelain=v1 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "Could not inspect working tree state for $Name at $Resolved"
    }
    return [ordered]@{
        path = $Resolved
        sha = $Sha
        branch = $Branch
        dirty = ($DirtyLines.Count -gt 0)
    }
}

function Resolve-GodotExecutable {
    param([string]$Requested)
    if ($Requested -and (Test-Path -LiteralPath $Requested -PathType Leaf)) {
        return (Resolve-Path -LiteralPath $Requested).Path
    }
    foreach ($Name in @("godot", "godot4", "Godot")) {
        $Command = Get-Command $Name -ErrorAction SilentlyContinue
        if ($Command -and $Command.Source) { return $Command.Source }
    }
    return $null
}

function Invoke-RecordedCommand {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Repository,
        [Parameter(Mandatory = $true)][string]$LogPath,
        [Parameter(Mandatory = $true)][scriptblock]$Command,
        [switch]$Skip
    )

    if ($Skip) {
        "Skipped by explicit acceptance configuration." | Set-Content -LiteralPath $LogPath -Encoding utf8
        return [ordered]@{
            name = $Name
            repository = $Repository
            status = "skipped"
            exit_code = 0
            duration_ms = 0
            log_path = $LogPath
        }
    }

    $Watch = [System.Diagnostics.Stopwatch]::StartNew()
    $Global:LASTEXITCODE = 0
    $Output = @()
    $ExitCode = 0
    try {
        $Output = @(& $Command 2>&1 | ForEach-Object { [string]$_ })
        $ExitCode = if ($LASTEXITCODE) { [int]$LASTEXITCODE } else { 0 }
    }
    catch {
        $Output += $_.Exception.ToString()
        $ExitCode = 1
    }
    finally {
        $Watch.Stop()
        $Output | Set-Content -LiteralPath $LogPath -Encoding utf8
    }
    return [ordered]@{
        name = $Name
        repository = $Repository
        status = if ($ExitCode -eq 0) { "passed" } else { "failed" }
        exit_code = $ExitCode
        duration_ms = [int][Math]::Min([int64]::MaxValue, $Watch.ElapsedMilliseconds)
        log_path = $LogPath
    }
}

function Get-NetworkingEvidence {
    param(
        [Parameter(Mandatory = $true)][string]$LogPath,
        [Parameter(Mandatory = $true)][string[]]$ExpectedContracts,
        [Parameter(Mandatory = $true)][string]$AggregateMarker
    )

    $Lines = if (Test-Path -LiteralPath $LogPath -PathType Leaf) {
        @(Get-Content -LiteralPath $LogPath | ForEach-Object { [string]$_ })
    }
    else {
        @()
    }
    $Prefix = "[networking] PASS "
    $ObservedContracts = @(
        $Lines |
            Where-Object { $_.Trim().StartsWith($Prefix, [StringComparison]::Ordinal) } |
            ForEach-Object { $_.Trim().Substring($Prefix.Length) }
    )
    $Counts = @{}
    foreach ($Contract in $ObservedContracts) {
        if ($Counts.ContainsKey($Contract)) { $Counts[$Contract] = [int]$Counts[$Contract] + 1 }
        else { $Counts[$Contract] = 1 }
    }
    $Missing = @($ExpectedContracts | Where-Object { -not $Counts.ContainsKey($_) })
    $Unexpected = @($Counts.Keys | Where-Object { $_ -notin $ExpectedContracts } | Sort-Object)
    $Duplicates = @($Counts.Keys | Where-Object { [int]$Counts[$_] -ne 1 } | Sort-Object)
    $AggregateOccurrences = @($Lines | Where-Object { $_.Trim() -ceq $AggregateMarker }).Count
    $Valid = (
        $AggregateOccurrences -eq 1 -and
        $ObservedContracts.Count -eq $ExpectedContracts.Count -and
        $Missing.Count -eq 0 -and
        $Unexpected.Count -eq 0 -and
        $Duplicates.Count -eq 0
    )
    if ($Valid) {
        for ($Index = 0; $Index -lt $ExpectedContracts.Count; $Index++) {
            if ($ObservedContracts[$Index] -cne $ExpectedContracts[$Index]) {
                $Valid = $false
                break
            }
        }
    }
    return [ordered]@{
        expected_contract_count = $ExpectedContracts.Count
        observed_contract_count = $ObservedContracts.Count
        aggregate_marker = $AggregateMarker
        aggregate_marker_occurrences = $AggregateOccurrences
        expected_contracts = @($ExpectedContracts)
        observed_contracts = @($ObservedContracts)
        missing_contracts = @($Missing)
        unexpected_contracts = @($Unexpected)
        duplicate_contracts = @($Duplicates)
        valid = $Valid
    }
}

$GameRuntime = Resolve-RepositoryEvidence -Path $GameRuntimePath -Name "evavo-game-runtime"
$EngineSystems = Resolve-RepositoryEvidence -Path $EngineSystemsPath -Name "godot-engine-systems"
$WebRuntime = Resolve-RepositoryEvidence -Path $WebRuntimePath -Name "godot-web-runtime" -Optional:$SkipWebRuntime
$TestLab = Resolve-RepositoryEvidence -Path $LabRoot -Name "godot-game-test-lab"

$AllEvidence = @($TestLab, $GameRuntime, $EngineSystems)
if ($null -ne $WebRuntime) { $AllEvidence += $WebRuntime }
if (-not $AllowDirty -and @($AllEvidence | Where-Object { $_.dirty }).Count -gt 0) {
    $DirtyNames = @()
    if ($TestLab.dirty) { $DirtyNames += "godot-game-test-lab" }
    if ($GameRuntime.dirty) { $DirtyNames += "evavo-game-runtime" }
    if ($EngineSystems.dirty) { $DirtyNames += "godot-engine-systems" }
    if ($null -ne $WebRuntime -and $WebRuntime.dirty) { $DirtyNames += "godot-web-runtime" }
    throw "Shared runtime acceptance requires clean exact-SHA checkouts: $($DirtyNames -join ', ')"
}

$Godot = Resolve-GodotExecutable -Requested $GodotPath
if (-not $SourceOnly -and -not $Godot) {
    throw "Godot is required for executable shared runtime acceptance. Use -SourceOnly only for a non-release source check."
}
$GodotEvidence = $null
if ($Godot) {
    $GodotVersion = (& $Godot --version 2>&1 | Select-Object -First 1).ToString().Trim()
    if ($LASTEXITCODE -ne 0 -or $GodotVersion -match '(?i)(dev|alpha|beta|rc)' -or $GodotVersion -notmatch '^4\.(?<Minor>\d+)\.(?<Patch>\d+)') {
        throw "Expected a stable Godot 4.x executable, observed: $GodotVersion"
    }
    $Minor = [int]$Matches.Minor
    $Patch = [int]$Matches.Patch
    if ($Minor -lt 6 -or ($Minor -eq 6 -and $Patch -lt 2)) {
        throw "Expected stable Godot 4.6.2 or newer within Godot 4, observed: $GodotVersion"
    }
    $GodotEvidence = [ordered]@{ path = $Godot; version = $GodotVersion }
}

$RunId = Get-Date -Format "yyyyMMdd-HHmmss"
$RunRoot = Join-Path $OutputRoot $RunId
New-Item -ItemType Directory -Force -Path $RunRoot | Out-Null
$Commands = @()
$Issues = [System.Collections.Generic.List[string]]::new()

$EngineRunner = Join-Path $EngineSystems.path "scripts\run-networking-contracts.ps1"
$EngineLog = Join-Path $RunRoot "godot-engine-systems-networking.log"
if (-not (Test-Path -LiteralPath $EngineRunner -PathType Leaf)) {
    throw "godot-engine-systems networking runner is missing: $EngineRunner"
}
$EngineCommand = Invoke-RecordedCommand -Name "engine-networking-contracts" -Repository "godot-engine-systems" -LogPath $EngineLog -Skip:$SourceOnly -Command {
    & $EngineRunner -GodotPath $Godot
}
$Commands += $EngineCommand
$NetworkingEvidence = Get-NetworkingEvidence -LogPath $EngineLog -ExpectedContracts $ExpectedNetworkingContracts -AggregateMarker $ExpectedNetworkingAggregateMarker
if (-not $SourceOnly -and $EngineCommand.status -eq "passed" -and -not $NetworkingEvidence.valid) {
    $Issues.Add("engine_networking_evidence_invalid")
}

$GameRunner = Join-Path $GameRuntime.path "scripts\validate.ps1"
$GameLog = Join-Path $RunRoot "evavo-game-runtime-validation.log"
if (-not (Test-Path -LiteralPath $GameRunner -PathType Leaf)) {
    throw "evavo-game-runtime validation runner is missing: $GameRunner"
}
$Commands += Invoke-RecordedCommand -Name "game-runtime-contracts" -Repository "evavo-game-runtime" -LogPath $GameLog -Command {
    if ($SourceOnly) {
        & $GameRunner -SkipRuntimeSmoke
    }
    else {
        & $GameRunner -GodotPath $Godot -SkipRuntimeSmoke
    }
}

$WebExecuted = $false
if (-not $SkipWebRuntime) {
    if ($null -eq $WebRuntime) { throw "godot-web-runtime is required unless -SkipWebRuntime is supplied." }
    $PackageJson = Join-Path $WebRuntime.path "package.json"
    if (-not (Test-Path -LiteralPath $PackageJson -PathType Leaf)) {
        throw "godot-web-runtime package.json is missing: $PackageJson"
    }
    $Pnpm = Get-Command pnpm -ErrorAction SilentlyContinue
    if (-not $Pnpm -or -not $Pnpm.Source) {
        throw "pnpm is required for godot-web-runtime acceptance."
    }
    $WebLog = Join-Path $RunRoot "godot-web-runtime-check.log"
    $Commands += Invoke-RecordedCommand -Name "web-runtime-check" -Repository "godot-web-runtime" -LogPath $WebLog -Command {
        Push-Location $WebRuntime.path
        try { & $Pnpm.Source check }
        finally { Pop-Location }
    }
    $WebExecuted = $true
}
else {
    $WebLog = Join-Path $RunRoot "godot-web-runtime-check.log"
    $Commands += Invoke-RecordedCommand -Name "web-runtime-check" -Repository "godot-web-runtime" -LogPath $WebLog -Skip -Command { }
}

foreach ($CommandResult in $Commands) {
    if ($CommandResult.status -eq "failed") {
        $Issues.Add("$($CommandResult.name)_failed")
    }
}

$NetworkingExecuted = (
    -not $SourceOnly -and
    $EngineCommand.status -eq "passed" -and
    [bool]$NetworkingEvidence.valid
)
$Status = if ($Issues.Count -gt 0) { "failed" } elseif ($SourceOnly) { "source_only" } else { "passed" }
$Receipt = [ordered]@{
    version = 1
    generated_utc = [DateTime]::UtcNow.ToString("o")
    status = $Status
    test_lab = $TestLab
    repositories = [ordered]@{
        game_runtime = $GameRuntime
        engine_systems = $EngineSystems
        web_runtime = $WebRuntime
    }
    godot = $GodotEvidence
    commands = $Commands
    networking_evidence = $NetworkingEvidence
    issues = @($Issues)
    claims = [ordered]@{
        source_only_is_executable_pass = $false
        dirty_checkout_is_release_evidence = $false
        networking_contracts_executed = $NetworkingExecuted
        game_runtime_contracts_executed = (($Commands | Where-Object { $_.name -eq "game-runtime-contracts" -and $_.status -eq "passed" }).Count -eq 1)
        web_runtime_contracts_executed = ($WebExecuted -and ($Commands | Where-Object { $_.name -eq "web-runtime-check" -and $_.status -eq "passed" }).Count -eq 1)
    }
}
$ReceiptPath = Join-Path $RunRoot "receipt.json"
$Receipt | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $ReceiptPath -Encoding utf8

$Python = Get-Command python -ErrorAction SilentlyContinue
if (-not $Python) { $Python = Get-Command python3 -ErrorAction SilentlyContinue }
if (-not $Python -or -not $Python.Source) {
    throw "Python 3 is required to validate the shared runtime acceptance receipt. Receipt: $ReceiptPath"
}
$ReceiptValidator = Join-Path $LabRoot "scripts\validate-evavo-shared-runtime-acceptance.py"
if (-not (Test-Path -LiteralPath $ReceiptValidator -PathType Leaf)) {
    throw "Shared runtime receipt validator is missing: $ReceiptValidator"
}
$ValidationLines = @(& $Python.Source $ReceiptValidator $ReceiptPath 2>&1 | ForEach-Object { [string]$_ })
$ValidationLines | ForEach-Object { Write-Host $_ }
if ($LASTEXITCODE -ne 0 -or -not ($ValidationLines | Where-Object { $_ -eq "EVAVO_SHARED_RUNTIME_ACCEPTANCE_RECEIPT=VALID" })) {
    throw "Shared runtime acceptance receipt validation failed. Receipt: $ReceiptPath"
}

Write-Host "EVAVO_SHARED_RUNTIME_ACCEPTANCE_STATUS=$Status"
Write-Host "EVAVO_SHARED_RUNTIME_ACCEPTANCE_RECEIPT=$ReceiptPath"
if ($Status -eq "failed") {
    throw "EVAVO shared runtime acceptance failed. Receipt: $ReceiptPath"
}
