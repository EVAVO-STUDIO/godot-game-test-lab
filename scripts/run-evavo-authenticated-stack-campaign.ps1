[CmdletBinding()]
param(
    [string]$Campaign = 'campaigns\evavo-authenticated-stack.example.json',
    [switch]$NoBuild
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw 'Python 3.11 or newer is required.'
}
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    throw 'Node.js 22 or newer is required by the EVAVO authenticated client workers.'
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw 'npm is required to build evavo-game-services.'
}
if (-not (Test-Path $Campaign)) {
    throw "Campaign file does not exist: $Campaign"
}

$Arguments = @(
    'tools\run_evavo_authenticated_stack_campaign.py',
    '--config',
    (Resolve-Path $Campaign).Path
)
if ($NoBuild) {
    $Arguments += '--no-build'
}

& python @Arguments
if ($LASTEXITCODE -ne 0) {
    throw "EVAVO authenticated stack campaign failed with exit code $LASTEXITCODE."
}
