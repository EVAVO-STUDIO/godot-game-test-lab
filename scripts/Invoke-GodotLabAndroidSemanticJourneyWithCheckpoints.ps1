[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Python,
    [Parameter(Mandatory)][int]$Port,
    [Parameter(Mandatory)][string]$Journey,
    [Parameter(Mandatory)][string]$Output,
    [Parameter(Mandatory)][string]$CheckpointDirectory,
    [Parameter(Mandatory)][string]$BridgeCli,
    [Parameter(Mandatory)][string]$Target,
    [Parameter(Mandatory)][string]$Package,
    [Parameter(Mandatory)][string]$EvidenceBase,
    [ValidateRange(100,10000)][int]$LogLines = 2000,
    [ValidateRange(30,600)][int]$TimeoutSeconds = 240
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

if ($Port -lt 1024 -or $Port -gt 65535) { throw 'Port must be between 1024 and 65535.' }
if ($Target -notmatch '^android-[0-9a-f]{16}$') { throw 'Target must be a privacy-safe Android targetRef.' }
if ($Package -notmatch '^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+$') { throw 'Package is invalid.' }
foreach ($Path in @($Python,$Journey,$BridgeCli)) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "Required file is unavailable: $Path" }
}

$CheckpointDirectory = [IO.Path]::GetFullPath($CheckpointDirectory)
$Output = [IO.Path]::GetFullPath($Output)
New-Item -ItemType Directory -Force -Path $CheckpointDirectory | Out-Null
Get-ChildItem -LiteralPath $CheckpointDirectory -File -ErrorAction SilentlyContinue | Remove-Item -Force
$OutputParent = Split-Path -Parent $Output
if ($OutputParent) { New-Item -ItemType Directory -Force -Path $OutputParent | Out-Null }

$stdout = [IO.Path]::GetTempFileName()
$stderr = [IO.Path]::GetTempFileName()
$handled = @{}
$checkpointEvidence = New-Object System.Collections.Generic.List[object]
$process = $null
$started = [DateTimeOffset]::UtcNow

function Write-Resume {
    param([string]$Path,[bool]$Ok,[string]$EvidenceRef,[string]$ErrorMessage)
    $value = [ordered]@{
        schema = 'evavo.godot.android-visual-checkpoint-resume.v1'
        ok = $Ok
        evidenceRef = $EvidenceRef
        error = $ErrorMessage
    }
    $tmp = "$Path.tmp"
    [IO.File]::WriteAllText($tmp, ($value | ConvertTo-Json -Depth 8), (New-Object Text.UTF8Encoding($false)))
    Move-Item -LiteralPath $tmp -Destination $Path -Force
}

try {
    $arguments = @(
        '-m','godot_game_test_lab.android_semantic_driver_cli',
        '--port',[string]$Port,
        '--journey',$Journey,
        '--output',$Output,
        '--checkpoint-directory',$CheckpointDirectory
    )
    $process = Start-Process -FilePath $Python -ArgumentList $arguments -NoNewWindow -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    $deadline = [DateTimeOffset]::UtcNow.AddSeconds($TimeoutSeconds)

    while (-not $process.HasExited) {
        if ([DateTimeOffset]::UtcNow -gt $deadline) {
            try { & taskkill.exe /PID $process.Id /T /F 2>$null | Out-Null } catch { try { $process.Kill() } catch {} }
            throw "Semantic Android journey exceeded $TimeoutSeconds seconds."
        }

        foreach ($requestFile in @(Get-ChildItem -LiteralPath $CheckpointDirectory -Filter '*.request.json' -File -ErrorAction SilentlyContinue | Sort-Object Name)) {
            if ($handled.ContainsKey($requestFile.FullName)) { continue }
            $handled[$requestFile.FullName] = $true
            $resumePath = $requestFile.FullName -replace '\.request\.json$','.resume.json'
            try {
                $request = Get-Content -LiteralPath $requestFile.FullName -Raw -Encoding UTF8 | ConvertFrom-Json -ErrorAction Stop
                if ($request.schema -ne 'evavo.godot.android-visual-checkpoint-request.v1') { throw 'Checkpoint request schema mismatch.' }
                $name = [string]$request.name
                if ($name -notmatch '^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$') { throw 'Checkpoint name is invalid.' }
                $index = [int]$request.index
                if ($index -lt 0 -or $index -gt 255) { throw 'Checkpoint index is invalid.' }
                $safeStem = ('{0:d3}-{1}' -f $index,$name)
                $evidenceRef = "$EvidenceBase/$safeStem"
                & node $BridgeCli evidence --target $Target --package $Package --output-dir $evidenceRef --lines ([string]$LogLines) --json | Out-Null
                if ($LASTEXITCODE -ne 0) { throw "Android checkpoint evidence capture failed with exit code $LASTEXITCODE." }
                $checkpointEvidence.Add([ordered]@{
                    index = $index
                    name = $name
                    evidenceRef = $evidenceRef
                    projectState = $request.state.projectState
                })
                Write-Resume -Path $resumePath -Ok $true -EvidenceRef $evidenceRef -ErrorMessage $null
            } catch {
                Write-Resume -Path $resumePath -Ok $false -EvidenceRef $null -ErrorMessage $_.Exception.Message
                throw
            }
        }
        Start-Sleep -Milliseconds 50
        $process.Refresh()
    }

    $process.WaitForExit()
    if ($process.ExitCode -ne 0) {
        $errorText = (Get-Content -LiteralPath $stderr -Raw -Encoding UTF8 -ErrorAction SilentlyContinue).Trim()
        if ($errorText.Length -gt 2000) { $errorText = $errorText.Substring($errorText.Length - 2000) }
        throw "Semantic Android journey failed with exit code $($process.ExitCode): $errorText"
    }
    if (-not (Test-Path -LiteralPath $Output -PathType Leaf)) { throw 'Semantic Android journey did not produce its output receipt.' }
    $journeyResult = Get-Content -LiteralPath $Output -Raw -Encoding UTF8 | ConvertFrom-Json -ErrorAction Stop
    if ($journeyResult.ok -ne $true) { throw 'Semantic Android journey output was not successful.' }
    if ([int]$journeyResult.checkpointCount -ne $checkpointEvidence.Count) { throw 'Semantic Android checkpoint evidence count did not match the journey result.' }
    if ([int]$journeyResult.checkpointCount -gt 0 -and $journeyResult.truth.visualCheckpointHostEvidence -ne $true) { throw 'Semantic journey requested visual checkpoints without host evidence truth.' }

    [ordered]@{
        schema = 'evavo_godot_lab_android_checkpoint_host_v1'
        ok = $true
        checkpointCount = $checkpointEvidence.Count
        checkpoints = @($checkpointEvidence)
        journeyOutput = $Output
        elapsedMs = [math]::Round(([DateTimeOffset]::UtcNow - $started).TotalMilliseconds)
        semanticInputOwnedByGodotDriver = $true
        visualEvidenceOwnedByAndroidBridge = $true
        rawCoordinatesUsed = $false
        arbitraryAdbShellExposed = $false
    } | ConvertTo-Json -Depth 12
}
finally {
    Remove-Item -LiteralPath $stdout,$stderr -Force -ErrorAction SilentlyContinue
}
