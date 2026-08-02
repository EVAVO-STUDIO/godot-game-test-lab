[CmdletBinding()]
param(
    [string]$LabRoot = "",
    [string]$GodotVersion = "4.6.3",
    [ValidateSet("standard", "mono", "all")]
    [string]$Flavor = "all",
    [string]$ImageRepository = "evavo/godot-lab-sandbox",
    [string]$ReceiptPath = "",
    [switch]$NoCache,
    [switch]$PullBaseImage
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

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

if (-not $LabRoot) {
    $LabRoot = Split-Path -Parent $PSScriptRoot
}
$resolvedLab = (Resolve-Path -LiteralPath $LabRoot).Path
$dockerfile = Join-Path $resolvedLab "containers\linux-sandbox\Dockerfile"
if (-not (Test-Path -LiteralPath $dockerfile -PathType Leaf)) {
    throw "Linux sandbox Dockerfile is missing: $dockerfile"
}
if ($GodotVersion -notmatch '^4\.[0-9]+\.[0-9]+$') {
    throw "GodotVersion must be an explicit stable Godot 4.x.y version."
}
$docker = Get-Command docker -ErrorAction SilentlyContinue
if (-not $docker) {
    throw "Docker Desktop or Docker Engine is required to build the Linux sandbox images."
}
Invoke-Checked $docker.Source version --format '{{.Server.Version}}'

$flavors = if ($Flavor -eq "all") { @("standard", "mono") } else { @($Flavor) }
$records = @()
foreach ($selectedFlavor in $flavors) {
    $tag = "$ImageRepository`:$GodotVersion-$selectedFlavor"
    $arguments = @(
        "build",
        "--file", $dockerfile,
        "--build-arg", "GODOT_VERSION=$GodotVersion",
        "--build-arg", "GODOT_FLAVOR=$selectedFlavor",
        "--label", "dev.evavo.godot-lab.version=0.7.0",
        "--label", "dev.evavo.godot.version=$GodotVersion",
        "--label", "dev.evavo.godot.flavor=$selectedFlavor",
        "--tag", $tag
    )
    if ($NoCache) {
        $arguments += "--no-cache"
    }
    if ($PullBaseImage) {
        $arguments += "--pull"
    }
    $arguments += $resolvedLab
    Write-Host "[godot-lab] Building $tag"
    Invoke-Checked $docker.Source @arguments
    $imageId = (& $docker.Source image inspect $tag --format '{{.Id}}').Trim()
    if ($LASTEXITCODE -ne 0 -or -not $imageId) {
        throw "Docker did not return an image identity for $tag"
    }
    $records += [ordered]@{
        tag = $tag
        imageId = $imageId
        godotVersion = $GodotVersion
        flavor = $selectedFlavor
    }
}

$receipt = [ordered]@{
    schemaVersion = "1.0"
    status = "ready"
    labRoot = $resolvedLab
    createdAt = [DateTimeOffset]::UtcNow.ToString("o")
    images = $records
}
if ($ReceiptPath) {
    $destination = [IO.Path]::GetFullPath($ReceiptPath)
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination) | Out-Null
    [IO.File]::WriteAllText(
        $destination,
        ($receipt | ConvertTo-Json -Depth 8) + [Environment]::NewLine,
        [Text.UTF8Encoding]::new($false)
    )
}
$receipt | ConvertTo-Json -Depth 8
