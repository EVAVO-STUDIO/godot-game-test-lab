function Test-HostReceiptCandidate {
    param(
        [string]$Path,
        [object]$Target,
        [string]$LabSha,
        [string]$EvidenceRoot
    )
    try {
        if (-not (Test-IsWithinPath -Candidate $Path -Parent $EvidenceRoot)) {
            return $null
        }
        $host = Get-Content -Raw -LiteralPath $Path | ConvertFrom-Json
        if ([string]$host.status -ne "passed" -or
            [string]$host.labSha -ne $LabSha) {
            return $null
        }
        $runRoot = (Resolve-Path -LiteralPath ([string]$host.runRoot)).Path
        $receiptParent = (Resolve-Path -LiteralPath (
            Split-Path -Parent $Path
        )).Path
        if (-not (Test-IsWithinPath -Candidate $runRoot -Parent $EvidenceRoot) -or
            -not $runRoot.Equals(
                $receiptParent,
                [StringComparison]::OrdinalIgnoreCase
            )) {
            return $null
        }
        $passedStages = @(
            $host.stages |
                Where-Object { [string]$_.status -eq "passed" } |
                ForEach-Object { [string]$_.id }
        )
        foreach ($requiredId in (Get-RequiredHostStageIds `
            -AcceptanceMode $Target.acceptanceMode)) {
            if ($passedStages -notcontains $requiredId) {
                return $null
            }
        }

        $validationPath = Join-Path $runRoot `
            "target-validation\native-validation-receipt.json"
        if (-not (Test-Path -LiteralPath $validationPath -PathType Leaf)) {
            return $null
        }
        $validation = Get-Content -Raw -LiteralPath $validationPath |
            ConvertFrom-Json
        $expectedRepository = [IO.Path]::GetFullPath($Target.repositoryPath)
        $observedRepository = [IO.Path]::GetFullPath(
            [string]$validation.targetRepositoryPath
        )
        if ([string]$validation.status -ne "passed" -or
            [string]$validation.labSha -ne $LabSha -or
            [string]$validation.targetSha -ne $Target.expectedSha -or
            -not $observedRepository.Equals(
                $expectedRepository,
                [StringComparison]::OrdinalIgnoreCase
            ) -or
            [string]$validation.projectSubpath -ne $Target.projectSubpath -or
            [bool]$validation.targetUnchanged -ne $true) {
            return $null
        }

        $workerStage = @(
            $host.stages | Where-Object {
                [string]$_.id -eq "worker-protocol-acceptance" -and
                [string]$_.status -eq "passed"
            }
        )
        if ($workerStage.Count -ne 1) {
            return $null
        }
        $workerReceiptPath = [string]$workerStage[0].result.receipt
        if (-not (Test-Path -LiteralPath $workerReceiptPath -PathType Leaf) -or
            -not (Test-IsWithinPath -Candidate $workerReceiptPath -Parent $runRoot)) {
            return $null
        }
        $worker = Get-Content -Raw -LiteralPath $workerReceiptPath |
            ConvertFrom-Json
        if ([string]$worker.status -ne "passed" -or
            [string]$worker.capabilities.bridge -ne "evavo-godot-lab-agent") {
            return $null
        }

        $nativeSummaryPath = $null
        if ($Target.acceptanceMode -in @("native", "all")) {
            $nativeSummaryPath = Join-Path $runRoot `
                "target-native\native-agent-summary.json"
            if (-not (Test-Path -LiteralPath $nativeSummaryPath -PathType Leaf)) {
                return $null
            }
            $native = Get-Content -Raw -LiteralPath $nativeSummaryPath |
                ConvertFrom-Json
            if ([string]$native.status -ne "passed" -or
                [string]$native.targetSha -ne $Target.expectedSha -or
                [string]$native.profileSha256 -ne $Target.nativeProfileSha256 -or
                [bool]$native.nativeDesktopEvidence -ne $true -or
                [bool]$native.targetMutationDetected -ne $false) {
                return $null
            }
        }

        $botSummaryPath = $null
        if ($Target.acceptanceMode -in @("bot", "all")) {
            $botSummaryPath = Join-Path $runRoot `
                "target-bot\bot-agent-summary.json"
            if (-not (Test-Path -LiteralPath $botSummaryPath -PathType Leaf)) {
                return $null
            }
            $bot = Get-Content -Raw -LiteralPath $botSummaryPath |
                ConvertFrom-Json
            if ([string]$bot.status -ne "passed" -or
                [string]$bot.targetSha -ne $Target.expectedSha -or
                [string]$bot.profileSha256 -ne $Target.botProfileSha256 -or
                [bool]$bot.nativeDesktopEvidence -ne $true -or
                [bool]$bot.targetMutationDetected -ne $false) {
                return $null
            }
        }

        return [pscustomobject]@{
            Path = $Path
            HostReceipt = $host
            HostReceiptSha256 = Get-FileSha256 -Path $Path
            ValidationReceiptPath = $validationPath
            ValidationReceiptSha256 = Get-FileSha256 -Path $validationPath
            WorkerReceiptPath = $workerReceiptPath
            WorkerReceiptSha256 = Get-FileSha256 -Path $workerReceiptPath
            NativeSummaryPath = $nativeSummaryPath
            NativeSummarySha256 = if ($nativeSummaryPath) {
                Get-FileSha256 -Path $nativeSummaryPath
            }
            else { $null }
            BotSummaryPath = $botSummaryPath
            BotSummarySha256 = if ($botSummaryPath) {
                Get-FileSha256 -Path $botSummaryPath
            }
            else { $null }
        }
    }
    catch {
        return $null
    }
}

function Get-ProjectFileInventory {
    param([string]$RepositoryPath, [string]$ProjectSubpath)
    $allFiles = Get-GitLines -Root $RepositoryPath -Arguments @("ls-files") `
        -Label "Read tracked project files"
    $normalized = $ProjectSubpath.Replace('\', '/').Trim('/')
    if (-not $normalized -or $normalized -eq ".") {
        return $allFiles
    }
    $prefix = "$normalized/"
    return @($allFiles | Where-Object {
        $_ -eq $normalized -or $_.StartsWith($prefix, [StringComparison]::Ordinal)
    })
}
