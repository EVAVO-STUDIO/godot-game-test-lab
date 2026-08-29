param(
    [Parameter(Mandatory=$true)][string]$GodotPath,
    [string]$RuntimeRepo = "C:\GitRepos\evavo-game-runtime",
    [string]$OutputDir = "artifacts\evavo-game-runtime-ui"
)

$ErrorActionPreference = "Stop"
$matrixPath = Join-Path $PSScriptRoot "..\config\evavo-game-runtime-ui-matrix.v1.json"
$matrix = Get-Content $matrixPath -Raw | ConvertFrom-Json
$projectPath = Join-Path $RuntimeRepo $matrix.project_relative_path
$resolvedOutput = Join-Path (Resolve-Path (Join-Path $PSScriptRoot "..")).Path $OutputDir
New-Item -ItemType Directory -Force -Path $resolvedOutput | Out-Null

if (-not (Test-Path $GodotPath)) { throw "Godot executable not found: $GodotPath" }
if (-not (Test-Path (Join-Path $projectPath "project.godot"))) { throw "Reference project not found: $projectPath" }

$receipts = @()
foreach ($scenario in $matrix.scenarios) {
    $env:EVAVO_QA_SCENARIO = [string]$scenario.id
    $env:EVAVO_QA_LAYOUT = [string]$scenario.layout_preset
    $env:EVAVO_QA_MIN_TARGET = [string]$scenario.minimum_target_px
    $env:EVAVO_QA_AUTOQUIT = "1"

    $args = @(
        "--path", $projectPath,
        "--resolution", ("{0}x{1}" -f $scenario.width, $scenario.height)
    )
    $lines = & $GodotPath @args 2>&1 | ForEach-Object { [string]$_ }
    $exitCode = $LASTEXITCODE
    $marker = $lines | Where-Object { $_ -like "EVAVO_UI_EVIDENCE=*" } | Select-Object -Last 1
    if (-not $marker) { throw "No EVAVO_UI_EVIDENCE emitted for scenario $($scenario.id). Godot exit=$exitCode" }

    $payload = ($marker -replace '^EVAVO_UI_EVIDENCE=', '') | ConvertFrom-Json
    $receipt = [ordered]@{
        version = 1
        scenario = $scenario.id
        layout_preset = $scenario.layout_preset
        requested_resolution = @([int]$scenario.width, [int]$scenario.height)
        godot_exit_code = $exitCode
        evidence = $payload
    }
    $receiptPath = Join-Path $resolvedOutput ("{0}.json" -f $scenario.id)
    $receipt | ConvertTo-Json -Depth 20 | Set-Content -Path $receiptPath -Encoding utf8
    $receipts += $receipt

    if ($exitCode -ne 0) { throw "Godot failed for scenario $($scenario.id) with exit code $exitCode" }
    $issues = @($payload.geometry.issues)
    if ($issues.Count -gt 0) {
        Write-Warning ("{0}: {1} geometry issue(s)" -f $scenario.id, $issues.Count)
    } else {
        Write-Host ("PASS {0}" -f $scenario.id)
    }
}

$summary = [ordered]@{
    version = 1
    generated_utc = [DateTime]::UtcNow.ToString("o")
    runtime_repo = $RuntimeRepo
    scenarios = $receipts
}
$summary | ConvertTo-Json -Depth 30 | Set-Content -Path (Join-Path $resolvedOutput "summary.json") -Encoding utf8
Write-Host "EVAVO game runtime UI matrix completed: $resolvedOutput"
