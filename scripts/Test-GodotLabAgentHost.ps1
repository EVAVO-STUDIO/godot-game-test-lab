[CmdletBinding()]
param(
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
    [string]$AcceptanceRepositoryPath = "",
    [string]$ExpectedTargetSha = "",
    [string]$ProjectSubpath = ".",
    [string]$NativeProfilePath = "",
    [string]$BotProfilePath = "",
    [ValidateSet("validate", "native", "bot", "all")]
    [string]$AcceptanceMode = "validate",
    [switch]$EngineOffline,
    [switch]$RegisterWorker,
    [switch]$StartWorker,
    [switch]$SkipWorkerProbe
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

function Write-AtomicJson {
    param([string]$Path, [object]$Value)
    $temporary = "$Path.tmp-$PID-$([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds())"
    [IO.File]::WriteAllText(
        $temporary,
        ($Value | ConvertTo-Json -Depth 14) + [Environment]::NewLine,
        [Text.UTF8Encoding]::new($false)
    )
    Move-Item -LiteralPath $temporary -Destination $Path -Force
}

function Invoke-Stage {
    param(
        [Parameter(Mandatory = $true)][string]$Id,
        [Parameter(Mandatory = $true)][scriptblock]$Action,
        [Parameter(Mandatory = $true)][System.Collections.IList]$Stages
    )
    $started = [DateTimeOffset]::UtcNow
    $stage = [ordered]@{
        id = $Id
        status = "running"
        startedAt = $started.ToString("o")
    }
    try {
        $stage.result = & $Action
        $stage.status = "passed"
        return $stage.result
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

function Get-CommandText {
    param([string]$Command, [string[]]$Arguments)
    $lines = @(& $Command @Arguments 2>&1)
    $exitCode = $LASTEXITCODE
    return [ordered]@{
        command = $Command
        arguments = $Arguments
        exitCode = $exitCode
        output = ($lines -join "`n").Trim()
    }
}

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw "Agent-host acceptance must run on Windows."
}
if (-not $LabRoot) {
    $LabRoot = Split-Path -Parent $PSScriptRoot
}
$lab = (Resolve-Path -LiteralPath $LabRoot).Path
Assert-NoReparsePoint -Path $lab
$python = Join-Path $lab ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Run scripts\Install-GodotLab.ps1 before host acceptance."
}
Assert-NoReparsePoint -Path $python

$candidateEvidence = [IO.Path]::GetFullPath($EvidenceRoot)
$candidateEngine = [IO.Path]::GetFullPath($EngineRoot)
Assert-NoReparsePointForCandidate -Path $candidateEvidence
Assert-NoReparsePointForCandidate -Path $candidateEngine

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

$labSha = Get-GitText -Root $lab -Arguments @("rev-parse", "HEAD") -Label "Resolve Lab SHA"
if (-not $ExpectedLabSha) {
    $ExpectedLabSha = $labSha
}
if ($ExpectedLabSha -notmatch '^[0-9a-f]{40}$' -or $labSha -ne $ExpectedLabSha) {
    throw "The Lab checkout does not match ExpectedLabSha."
}
$labTrackedStatus = Get-GitText -Root $lab -Arguments @(
    "status", "--porcelain=v1", "--untracked-files=all"
) -Label "Read Lab tracked status"
if ($labTrackedStatus) {
    throw "The Lab checkout has tracked changes."
}

$currentSession = [Diagnostics.Process]::GetCurrentProcess().SessionId
$explorerSessions = @(
    Get-Process -Name explorer -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty SessionId -Unique
)
if ($currentSession -eq 0 -or $explorerSessions -notcontains $currentSession) {
    throw "Agent-host acceptance requires Explorer in the current nonzero Windows session."
}

$stamp = [DateTimeOffset]::UtcNow.ToString("yyyyMMdd-HHmmssfff")
$runRoot = Join-Path $evidence "host-acceptance\$stamp"
New-Item -ItemType Directory -Path $runRoot | Out-Null
$receiptPath = Join-Path $runRoot "host-acceptance.json"
$stages = [Collections.ArrayList]::new()
$receipt = [ordered]@{
    schemaVersion = "1.0"
    status = "running"
    startedAt = [DateTimeOffset]::UtcNow.ToString("o")
    labRoot = $lab
    labSha = $labSha
    evidenceRoot = $evidence
    runRoot = $runRoot
    engineRoot = $engines
    allowedTargetRoots = @($resolvedRoots)
    engineOffline = [bool]$EngineOffline
    machine = $env:COMPUTERNAME
    user = [Environment]::UserName
    sessionId = $currentSession
    explorerSessions = $explorerSessions
    endpoint = "http://127.0.0.1:$Port/mcp"
    stages = $stages
}
$failure = $null

try {
    Invoke-Stage -Id "toolchain" -Stages $stages -Action {
        $toolchain = Get-CommandText -Command $python -Arguments @(
            "scripts/check_repository_toolchain.py", "--native-family", "--installed"
        )
        if ($toolchain.exitCode -ne 0) {
            throw "Installed Lab toolchain validation failed: $($toolchain.output)"
        }
        return $toolchain
    } | Out-Null

    Invoke-Stage -Id "managed-engines" -Stages $stages -Action {
        $reportPath = Join-Path $runRoot "managed-engines.json"
        & $python -m godot_game_test_lab.cli engine status `
            --root $engines --output $reportPath
        if ($LASTEXITCODE -ne 0) {
            throw "Both governed managed Godot editors are not ready."
        }
        $report = Get-Content -Raw -LiteralPath $reportPath | ConvertFrom-Json
        $ready = @($report.installations | Where-Object { $_.status -eq "ready" })
        $flavors = @($ready | ForEach-Object { [string]$_.flavor } | Sort-Object -Unique)
        if ($flavors -notcontains "standard" -or $flavors -notcontains "mono") {
            throw "Managed engine acceptance requires ready Standard and .NET editors."
        }
        return [ordered]@{
            report = $reportPath
            flavors = $flavors
            installations = $ready.Count
        }
    } | Out-Null

    Invoke-Stage -Id "doctor" -Stages $stages -Action {
        $doctorPath = Join-Path $runRoot "doctor.json"
        & $python -m godot_game_test_lab.cli doctor --output $doctorPath
        if ($LASTEXITCODE -ne 0) {
            throw "Godot Lab doctor failed."
        }
        return [ordered]@{ report = $doctorPath }
    } | Out-Null

    Invoke-Stage -Id "mcp-self-test" -Stages $stages -Action {
        $arguments = @(
            "-m", "godot_game_test_lab.mcp_server",
            "--lab-root", $lab,
            "--evidence-root", $evidence,
            "--engine-root", $engines,
            "--self-test"
        )
        foreach ($root in $resolvedRoots) {
            $arguments += @("--allowed-root", $root)
        }
        if ($EngineOffline) {
            $arguments += "--no-auto-provision"
        }
        $mcp = Get-CommandText -Command $python -Arguments $arguments
        if ($mcp.exitCode -ne 0) {
            throw "MCP self-test failed: $($mcp.output)"
        }
        return $mcp
    } | Out-Null

    Invoke-Stage -Id "hardware" -Stages $stages -Action {
        $hardware = [ordered]@{
            schemaVersion = "1.0"
            computer = @(
                Get-CimInstance Win32_ComputerSystem |
                    Select-Object Manufacturer, Model, TotalPhysicalMemory
            )
            operatingSystem = @(
                Get-CimInstance Win32_OperatingSystem |
                    Select-Object Caption, Version, BuildNumber, OSArchitecture
            )
            videoControllers = @(
                Get-CimInstance Win32_VideoController |
                    Select-Object Name, DriverVersion, AdapterRAM, VideoProcessor
            )
            soundDevices = @(
                Get-CimInstance Win32_SoundDevice |
                    Select-Object Name, Manufacturer, Status
            )
            nvidiaSmi = $(
                if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
                    Get-CommandText -Command "nvidia-smi" -Arguments @(
                        "--query-gpu=name,driver_version,memory.total,compute_cap",
                        "--format=csv,noheader"
                    )
                }
                else {
                    $null
                }
            )
        }
        $hardwarePath = Join-Path $runRoot "hardware.json"
        Write-AtomicJson -Path $hardwarePath -Value $hardware
        return [ordered]@{ report = $hardwarePath }
    } | Out-Null

    if ($RegisterWorker) {
        Invoke-Stage -Id "register-worker" -Stages $stages -Action {
            $register = Join-Path $lab "scripts\Register-GodotLabMcpWorker.ps1"
            $parameters = @{
                LabRoot = $lab
                AllowedTargetRoots = @($resolvedRoots)
                EvidenceRoot = $evidence
                EngineRoot = $engines
                TaskName = $TaskName
                Port = $Port
            }
            if ($EngineOffline) {
                $parameters.EngineOffline = $true
            }
            if ($StartWorker) {
                $parameters.StartNow = $true
            }
            & $register @parameters
            return [ordered]@{
                taskName = $TaskName
                started = [bool]$StartWorker
                allowedTargetRoots = @($resolvedRoots)
                engineOffline = [bool]$EngineOffline
            }
        } | Out-Null
    }
    elseif ($StartWorker) {
        Invoke-Stage -Id "start-worker" -Stages $stages -Action {
            Start-ScheduledTask -TaskName $TaskName
            return [ordered]@{ taskName = $TaskName }
        } | Out-Null
    }

    if (-not $SkipWorkerProbe) {
        Invoke-Stage -Id "worker-protocol-acceptance" -Stages $stages -Action {
            $testWorker = Join-Path $lab "scripts\Test-GodotLabMcpWorker.ps1"
            if (-not (Test-Path -LiteralPath $testWorker -PathType Leaf)) {
                throw "The MCP worker acceptance script is missing: $testWorker"
            }
            $workerReceipt = Join-Path $runRoot "mcp-worker-acceptance.json"
            $probeParameters = @{
                LabRoot = $lab
                AllowedTargetRoots = @($resolvedRoots)
                EvidenceRoot = $evidence
                EngineRoot = $engines
                TaskName = $TaskName
                Port = $Port
                TimeoutSeconds = $WorkerStartupTimeoutSeconds
                ExpectedLabSha = $labSha
                OutputPath = $workerReceipt
            }
            if ($EngineOffline) {
                $probeParameters.EngineOffline = $true
            }
            if ($RegisterWorker -or $StartWorker) {
                $probeParameters.RequireScheduledTask = $true
            }
            & $testWorker @probeParameters
            $probe = Get-Content -Raw -LiteralPath $workerReceipt |
                ConvertFrom-Json
            return [ordered]@{
                receipt = $workerReceipt
                bridge = [string]$probe.capabilities.bridge
                allowedTargetRoots = @($probe.capabilities.allowedTargetRoots)
                autoProvisionEngines = [bool]$probe.capabilities.autoProvisionEngines
            }
        } | Out-Null
    }

    if ($AcceptanceRepositoryPath) {
        $target = (Resolve-Path -LiteralPath $AcceptanceRepositoryPath).Path
        $targetSha = Get-GitText -Root $target -Arguments @(
            "rev-parse", "HEAD"
        ) -Label "Resolve acceptance target SHA"
        if (-not $ExpectedTargetSha) {
            $ExpectedTargetSha = $targetSha
        }
        if ($ExpectedTargetSha -notmatch '^[0-9a-f]{40}$' -or
            $targetSha -ne $ExpectedTargetSha) {
            throw "The acceptance target does not match ExpectedTargetSha."
        }

        Invoke-Stage -Id "target-validation" -Stages $stages -Action {
            $validationRoot = Join-Path $runRoot "target-validation"
            & (Join-Path $lab "scripts\Invoke-GodotLabNativeValidation.ps1") `
                -TargetRepositoryPath $target `
                -ProjectSubpath $ProjectSubpath `
                -AllowedTargetRoots $AllowedTargetRoots `
                -ExpectedLabSha $labSha `
                -ExpectedTargetSha $targetSha `
                -ArtifactPath $validationRoot `
                -AllowedArtifactRoot $runRoot `
                -PythonExecutable $python
            return [ordered]@{ artifacts = $validationRoot }
        } | Out-Null

        if ($AcceptanceMode -in @("native", "all")) {
            if (-not $NativeProfilePath) {
                throw "NativeProfilePath is required for native acceptance."
            }
            Invoke-Stage -Id "target-native-journey" -Stages $stages -Action {
                $nativeRoot = Join-Path $runRoot "target-native"
                & (Join-Path $lab "scripts\Invoke-GodotLabNativeAgentQA.ps1") `
                    -TargetRepositoryPath $target `
                    -ProjectSubpath $ProjectSubpath `
                    -ProfilePath $NativeProfilePath `
                    -ExpectedLabSha $labSha `
                    -ExpectedTargetSha $targetSha `
                    -ArtifactPath $nativeRoot `
                    -AllowedArtifactRoot $runRoot `
                    -PythonExecutable $python
                return [ordered]@{ artifacts = $nativeRoot }
            } | Out-Null
        }

        if ($AcceptanceMode -in @("bot", "all")) {
            if (-not $BotProfilePath) {
                throw "BotProfilePath is required for bot acceptance."
            }
            Invoke-Stage -Id "target-bot-journey" -Stages $stages -Action {
                $botRoot = Join-Path $runRoot "target-bot"
                & (Join-Path $lab "scripts\Invoke-GodotLabBotQA.ps1") `
                    -TargetRepositoryPath $target `
                    -ProjectSubpath $ProjectSubpath `
                    -ProfilePath $BotProfilePath `
                    -ExpectedLabSha $labSha `
                    -ExpectedTargetSha $targetSha `
                    -ArtifactPath $botRoot `
                    -AllowedArtifactRoot $runRoot `
                    -PythonExecutable $python
                return [ordered]@{ artifacts = $botRoot }
            } | Out-Null
        }
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
Write-Host "[godot-lab] Agent host acceptance passed. Receipt: $receiptPath"
