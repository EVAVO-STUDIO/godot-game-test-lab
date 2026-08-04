[CmdletBinding()]
param(
    [string]$LabRoot = "",
    [string]$PythonLauncher = "py",
    [string]$EngineVersion = "4.6.3",
    [string]$EngineRoot = "$env:LOCALAPPDATA\EVAVO\GodotGameTestLab\engines",
    [string]$TargetRoot = "C:\GitRepos",
    [string[]]$AdditionalTargetRoots = @(),
    [string]$EvidenceRoot = "C:\GodotLabEvidence",
    [string]$OfflineSourceDir = "",
    [switch]$EngineOffline,
    [switch]$PrepareEstate,
    [switch]$PrepareLinuxSandboxImages,
    [switch]$SkipAgentBridge,
    [switch]$SkipExportTemplates,
    [switch]$ForceEngineInstall,
    [switch]$NoUserPath,
    [bool]$InstallPrerequisites = $true,
    [switch]$RequireFullMediaToolchain
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Test-IsWithinPath {
    param(
        [Parameter(Mandatory = $true)][string]$Candidate,
        [Parameter(Mandatory = $true)][string]$Parent
    )
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
    param(
        [Parameter(Mandatory = $true)][string]$Left,
        [Parameter(Mandatory = $true)][string]$Right
    )
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

function Add-ProcessPath {
    param([Parameter(Mandatory = $true)][string]$Directory)
    if (-not (Test-Path -LiteralPath $Directory -PathType Container)) { return }
    $parts = @($env:Path -split ';' | Where-Object { $_ })
    if ($parts -notcontains $Directory) {
        $env:Path = "$Directory;$env:Path"
    }
}

function Add-UserPath {
    param([Parameter(Mandatory = $true)][string]$Directory)
    if (-not (Test-Path -LiteralPath $Directory -PathType Container)) { return }
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    $parts = @($userPath -split ';' | Where-Object { $_ })
    if ($parts -notcontains $Directory) {
        [Environment]::SetEnvironmentVariable(
            'Path',
            (@($Directory) + $parts) -join ';',
            'User'
        )
    }
    Add-ProcessPath $Directory
}

function Refresh-ProcessPath {
    $machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = (@($machinePath, $userPath) | Where-Object { $_ }) -join ';'
    Add-ProcessPath (Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Links')
}

function Install-WinGetPackage {
    param([Parameter(Mandatory = $true)][string]$Identifier)
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $winget) {
        throw "WinGet is required to install prerequisite package $Identifier."
    }
    & $winget.Source install --id $Identifier --exact --silent `
        --accept-package-agreements --accept-source-agreements `
        --disable-interactivity
    if ($LASTEXITCODE -ne 0) {
        throw "WinGet could not install prerequisite package $Identifier."
    }
    Refresh-ProcessPath
}

if ($env:OS -ne "Windows_NT") {
    throw (
        "Install-GodotLab.ps1 is the Windows installer. " +
        "Use scripts/install-godot-lab.sh on Linux."
    )
}
if (-not $LabRoot) {
    $LabRoot = Split-Path -Parent $PSScriptRoot
}
$resolvedLab = (Resolve-Path -LiteralPath $LabRoot).Path
Assert-NoReparsePoint -Path $resolvedLab
$projectFile = Join-Path $resolvedLab "pyproject.toml"
if (-not (Test-Path -LiteralPath $projectFile -PathType Leaf)) {
    throw "LabRoot does not identify the Godot Game Test Lab repository: $resolvedLab"
}

$resolvedRoots = [Collections.Generic.List[string]]::new()
$seenRoots = [Collections.Generic.HashSet[string]]::new(
    [StringComparer]::OrdinalIgnoreCase
)
foreach ($root in @($TargetRoot) + @($AdditionalTargetRoots)) {
    $resolved = (Resolve-Path -LiteralPath $root).Path
    Assert-NoReparsePoint -Path $resolved
    if ($seenRoots.Add($resolved)) {
        $resolvedRoots.Add($resolved)
    }
}
if ($resolvedRoots.Count -eq 0) {
    throw "At least one allowed target root is required."
}
$resolvedTarget = $resolvedRoots[0]
$offlineEnginePolicy = $EngineOffline -or [bool]$OfflineSourceDir

$candidateEngine = [IO.Path]::GetFullPath($EngineRoot)
$candidateEvidence = [IO.Path]::GetFullPath($EvidenceRoot)
Assert-NoReparsePointForCandidate -Path $candidateEngine
Assert-NoReparsePointForCandidate -Path $candidateEvidence
if (Test-PathsOverlap -Left $candidateEvidence -Right $resolvedLab) {
    throw "EvidenceRoot must remain disjoint from the Lab checkout."
}
foreach ($root in $resolvedRoots) {
    if (Test-PathsOverlap -Left $candidateEvidence -Right $root) {
        throw "EvidenceRoot must remain disjoint from every allowed target root."
    }
}
foreach ($protected in @($resolvedLab, $candidateEvidence) + @($resolvedRoots)) {
    if (Test-PathsOverlap -Left $candidateEngine -Right $protected) {
        throw "EngineRoot must remain disjoint from Lab, target, and evidence roots."
    }
}

New-Item -ItemType Directory -Force -Path $candidateEngine, $candidateEvidence |
    Out-Null
$resolvedEngine = (Resolve-Path -LiteralPath $candidateEngine).Path
$resolvedEvidence = (Resolve-Path -LiteralPath $candidateEvidence).Path
Assert-NoReparsePoint -Path $resolvedEngine
Assert-NoReparsePoint -Path $resolvedEvidence
if (Test-PathsOverlap -Left $resolvedEvidence -Right $resolvedLab) {
    throw "EvidenceRoot must remain disjoint from the Lab checkout."
}
foreach ($root in $resolvedRoots) {
    if (Test-PathsOverlap -Left $resolvedEvidence -Right $root) {
        throw "EvidenceRoot must remain disjoint from every allowed target root."
    }
}
foreach ($protected in @($resolvedLab, $resolvedEvidence) + @($resolvedRoots)) {
    if (Test-PathsOverlap -Left $resolvedEngine -Right $protected) {
        throw "EngineRoot must remain disjoint from Lab, target, and evidence roots."
    }
}

if ($InstallPrerequisites) {
    Refresh-ProcessPath
    if (-not (Get-Command dotnet -ErrorAction SilentlyContinue)) {
        Install-WinGetPackage "Microsoft.DotNet.SDK.8"
    }
    if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue) -or
        -not (Get-Command ffprobe -ErrorAction SilentlyContinue)) {
        Install-WinGetPackage "Gyan.FFmpeg"
        $packageRoot = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages"
        if (Test-Path -LiteralPath $packageRoot -PathType Container) {
            $ffmpeg = Get-ChildItem -LiteralPath $packageRoot -Filter ffmpeg.exe `
                -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($ffmpeg) { Add-UserPath $ffmpeg.Directory.FullName }
        }
    }
}

$venv = Join-Path $resolvedLab ".venv"
$python = Join-Path $venv "Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    & $PythonLauncher -3.11 -m venv $venv
    if ($LASTEXITCODE -ne 0) {
        throw "Python 3.11 virtual-environment creation failed."
    }
}
& $python -c "import sys; assert sys.version_info[:2] == (3, 11), sys.version"
if ($LASTEXITCODE -ne 0) {
    throw "The Lab virtual environment must use Python 3.11.x."
}

$extras = if ($SkipAgentBridge) { ".[dev]" } else { ".[dev,agent]" }
Push-Location $resolvedLab
try {
    & $python -m pip install --disable-pip-version-check --editable $extras
    if ($LASTEXITCODE -ne 0) {
        throw "Godot Game Test Lab package installation failed."
    }

    $bootstrapReport = Join-Path $resolvedEvidence "managed-engine-bootstrap.json"
    $engineArgs = @(
        "-m", "godot_game_test_lab.cli", "engine", "bootstrap",
        "--version", $EngineVersion,
        "--flavors", "standard,mono",
        "--root", $resolvedEngine,
        "--output", $bootstrapReport
    )
    if ($SkipExportTemplates) {
        $engineArgs += "--no-templates"
    }
    if ($ForceEngineInstall) {
        $engineArgs += "--force"
    }
    $offline = ""
    if ($OfflineSourceDir) {
        $offline = (Resolve-Path -LiteralPath $OfflineSourceDir).Path
        Assert-NoReparsePoint -Path $offline
        $engineArgs += @("--source-dir", $offline, "--offline")
    }
    elseif ($EngineOffline) {
        $engineArgs += "--offline"
    }
    & $python @engineArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Managed Godot editor bootstrap failed."
    }

    $bootstrap = Get-Content -Raw -LiteralPath $bootstrapReport | ConvertFrom-Json
    $standard = $bootstrap.installations |
        Where-Object { $_.flavor -eq "standard" } |
        Select-Object -First 1
    $mono = $bootstrap.installations |
        Where-Object { $_.flavor -eq "mono" } |
        Select-Object -First 1
    if (-not $standard -or -not $mono) {
        throw "Bootstrap did not produce both standard and .NET Godot editors."
    }

    $allowedRootValue = @($resolvedRoots) -join [IO.Path]::PathSeparator
    $environment = [ordered]@{
        EVAVO_GODOT_LAB_ROOT = $resolvedLab
        EVAVO_GODOT_HOME = $resolvedEngine
        EVAVO_GODOT_LAB_ALLOWED_ROOTS = $allowedRootValue
        EVAVO_GODOT_LAB_EVIDENCE_ROOT = $resolvedEvidence
        GODOT_BIN = [string]$standard.executable
        GODOT_MONO_BIN = [string]$mono.executable
    }
    foreach ($entry in $environment.GetEnumerator()) {
        [Environment]::SetEnvironmentVariable($entry.Key, $entry.Value, "Process")
        [Environment]::SetEnvironmentVariable($entry.Key, $entry.Value, "User")
    }

    $scriptsDirectory = Join-Path $venv "Scripts"
    if (-not $NoUserPath) {
        $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
        $parts = @($userPath -split ";" | Where-Object { $_ })
        if ($parts -notcontains $scriptsDirectory) {
            $newPath = (@($scriptsDirectory) + $parts) -join ";"
            [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
        }
        if (($env:Path -split ";") -notcontains $scriptsDirectory) {
            $env:Path = "$scriptsDirectory;$env:Path"
        }
    }

    $envFile = Join-Path $resolvedEvidence "godot-lab-env.ps1"
    $envLines = @(
        "`$env:EVAVO_GODOT_LAB_ROOT = '$($resolvedLab.Replace("'", "''"))'",
        "`$env:EVAVO_GODOT_HOME = '$($resolvedEngine.Replace("'", "''"))'",
        "`$env:EVAVO_GODOT_LAB_ALLOWED_ROOTS = '$($allowedRootValue.Replace("'", "''"))'",
        "`$env:EVAVO_GODOT_LAB_EVIDENCE_ROOT = '$($resolvedEvidence.Replace("'", "''"))'",
        "`$env:GODOT_BIN = '$(([string]$standard.executable).Replace("'", "''"))'",
        "`$env:GODOT_MONO_BIN = '$(([string]$mono.executable).Replace("'", "''"))'"
    )
    [System.IO.File]::WriteAllLines(
        $envFile,
        $envLines,
        [System.Text.UTF8Encoding]::new($false)
    )

    $estateReports = [Collections.Generic.List[string]]::new()
    if ($PrepareEstate) {
        for ($index = 0; $index -lt $resolvedRoots.Count; $index++) {
            $reportName = if ($index -eq 0) {
                "managed-engine-estate.json"
            }
            else {
                "managed-engine-estate-{0:D2}.json" -f ($index + 1)
            }
            $estateReport = Join-Path $resolvedEvidence $reportName
            $prepareArgs = @(
                "-m", "godot_game_test_lab.cli", "engine", "prepare",
                $resolvedRoots[$index],
                "--root", $resolvedEngine,
                "--output", $estateReport
            )
            if ($SkipExportTemplates) {
                $prepareArgs += "--no-templates"
            }
            if ($ForceEngineInstall) {
                $prepareArgs += "--force"
            }
            if ($OfflineSourceDir) {
                $prepareArgs += @("--source-dir", $offline, "--offline")
            }
            elseif ($EngineOffline) {
                $prepareArgs += "--offline"
            }
            & $python @prepareArgs
            if ($LASTEXITCODE -ne 0) {
                Write-Warning (
                    "One or more estate projects beneath $($resolvedRoots[$index]) " +
                    "could not be prepared. Review $estateReport."
                )
            }
            [void]$estateReports.Add($estateReport)
        }
    }

    & $python -m godot_game_test_lab.cli doctor
    if ($LASTEXITCODE -ne 0) {
        throw "The managed Godot editors did not pass the Lab doctor probe."
    }

    $mcpConfig = Join-Path $resolvedEvidence "godot-lab-mcp.json"
    if (-not $SkipAgentBridge) {
        $mcpArguments = @(
            "-m", "godot_game_test_lab.mcp_server",
            "--lab-root", $resolvedLab,
            "--evidence-root", $resolvedEvidence,
            "--engine-root", $resolvedEngine,
            "--self-test"
        )
        foreach ($root in $resolvedRoots) {
            $mcpArguments += @("--allowed-root", $root)
        }
        if ($offlineEnginePolicy) {
            $mcpArguments += "--no-auto-provision"
        }
        & $python @mcpArguments
        if ($LASTEXITCODE -ne 0) {
            throw "The MCP agent bridge self-test failed."
        }
        $mcpConfigParameters = @{
            LabRoot = $resolvedLab
            PythonExecutable = $python
            AllowedTargetRoots = @($resolvedRoots)
            EvidenceRoot = $resolvedEvidence
            EngineRoot = $resolvedEngine
            OutputPath = $mcpConfig
        }
        if ($offlineEnginePolicy) {
            $mcpConfigParameters.NoAutoProvision = $true
        }
        & (Join-Path $resolvedLab "scripts\Write-GodotLabMcpConfig.ps1") `
            @mcpConfigParameters
    }

    $sandboxImages = @()
    if ($PrepareLinuxSandboxImages) {
        $sandboxStatus = Join-Path $resolvedEvidence "linux-sandbox-status.json"
        & $python -m godot_game_test_lab.cli sandbox status --output $sandboxStatus
        if ($LASTEXITCODE -ne 0) {
            throw (
                "Docker Desktop must be running with Linux containers enabled " +
                "before sandbox images can be prepared."
            )
        }
        foreach ($flavor in @("standard", "mono")) {
            $imageReport = Join-Path $resolvedEvidence "linux-sandbox-$flavor.json"
            & $python -m godot_game_test_lab.cli sandbox image `
                --lab-root $resolvedLab `
                --version $EngineVersion `
                --flavor $flavor `
                --output $imageReport
            if ($LASTEXITCODE -ne 0) {
                throw "The governed Linux $flavor sandbox image could not be prepared."
            }
            $sandboxImages += (
                Get-Content -Raw -LiteralPath $imageReport | ConvertFrom-Json
            )
        }
    }

    $missingMediaTools = @("ffmpeg", "ffprobe") | Where-Object {
        -not (Get-Command $_ -ErrorAction SilentlyContinue)
    }
    $dotnetMissing = -not (Get-Command dotnet -ErrorAction SilentlyContinue)
    if ($RequireFullMediaToolchain -and
        ($missingMediaTools.Count -gt 0 -or $dotnetMissing)) {
        $missing = @($missingMediaTools)
        if ($dotnetMissing) { $missing += ".NET SDK 8" }
        throw "The required full QA toolchain is incomplete: $($missing -join ', ')."
    }
    if ($missingMediaTools.Count -gt 0) {
        Write-Warning (
            "Audio/video evidence needs FFmpeg and FFprobe. Missing: " +
            ($missingMediaTools -join ", ") +
            ". Run again with -InstallPrerequisites or install Gyan.FFmpeg."
        )
    }
    if ($dotnetMissing) {
        Write-Warning (
            "C# projects also need .NET SDK 8. Run again with -InstallPrerequisites " +
            "or set DOTNET_BIN before C# validation."
        )
    }

    $receipt = [ordered]@{
        schemaVersion = "1.0"
        status = "ready"
        labRoot = $resolvedLab
        python = $python
        engineVersion = $EngineVersion
        engineRoot = $resolvedEngine
        standardGodot = [string]$standard.executable
        monoGodot = [string]$mono.executable
        evidenceRoot = $resolvedEvidence
        targetRoot = $resolvedTarget
        allowedTargetRoots = @($resolvedRoots)
        environmentFile = $envFile
        mcpConfig = if ($SkipAgentBridge) { $null } else { $mcpConfig }
        estatePrepared = [bool]$PrepareEstate
        estateReports = @($estateReports)
        engineOffline = [bool]$offlineEnginePolicy
        sandboxImagesPrepared = [bool]$PrepareLinuxSandboxImages
        sandboxImages = $sandboxImages
        installedAt = [DateTimeOffset]::UtcNow.ToString("o")
    }
    $receiptPath = Join-Path $resolvedEvidence "godot-lab-installation.json"
    $receipt | ConvertTo-Json -Depth 8 |
        Set-Content -LiteralPath $receiptPath -Encoding utf8
    Write-Host "[godot-lab] Installation complete. Receipt: $receiptPath"
    Write-Host "[godot-lab] Reload the terminal or run: . '$envFile'"
}
finally {
    Pop-Location
}
