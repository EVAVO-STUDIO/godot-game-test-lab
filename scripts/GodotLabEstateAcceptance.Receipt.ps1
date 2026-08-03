function Test-StageSetPassed {
    param(
        [object[]]$Stages,
        [string[]]$RequiredIds
    )
    $allStages = @($Stages)
    if ($allStages.Count -eq 0) {
        return $false
    }
    $ids = @()
    foreach ($stage in $allStages) {
        if ([string]$stage.status -ne "passed") {
            return $false
        }
        $id = [string]$stage.id
        if (-not $id) {
            return $false
        }
        $ids += $id
    }
    if (@($ids | Sort-Object -Unique).Count -ne $ids.Count) {
        return $false
    }
    foreach ($required in $RequiredIds) {
        if ($ids -notcontains $required) {
            return $false
        }
    }
    return $true
}

function Test-RequiredItemsPassed {
    param([object[]]$Items)
    $required = @($Items | Where-Object { [bool]$_.required })
    if ($required.Count -eq 0) {
        return $false
    }
    return @(
        $required | Where-Object { [string]$_.status -ne "passed" }
    ).Count -eq 0
}

function Test-HostReceiptCandidate {
    param(
        [string]$Path,
        [object]$Target,
        [string]$LabRoot,
        [string]$LabSha,
        [string[]]$AllowedTargetRoots,
        [string]$EvidenceRoot,
        [string]$EngineRoot,
        [bool]$EngineOffline,
        [string]$PythonExecutable
    )
    try {
        $receiptPath = (Resolve-Path -LiteralPath $Path).Path
        Assert-NoReparsePoint -Path $receiptPath
        if (-not (Test-IsWithinPath -Candidate $receiptPath `
            -Parent $EvidenceRoot)) {
            return $null
        }
        $hostRecord = Read-StrictJsonFile -Path $receiptPath `
            -PythonExecutable $PythonExecutable `
            -Label "Host acceptance receipt" `
            -MaximumBytes 4194304
        $host = $hostRecord.Value
        if ([string]$host.schemaVersion -ne "1.0" -or
            [string]$host.status -ne "passed" -or
            [string]$host.labSha -ne $LabSha -or
            [bool]$host.engineOffline -ne $EngineOffline) {
            return $null
        }
        if ((Get-NormalizedPathIdentity -Path ([string]$host.labRoot)) -ne
            (Get-NormalizedPathIdentity -Path $LabRoot) -or
            (Get-NormalizedPathIdentity -Path ([string]$host.evidenceRoot)) -ne
            (Get-NormalizedPathIdentity -Path $EvidenceRoot) -or
            (Get-NormalizedPathIdentity -Path ([string]$host.engineRoot)) -ne
            (Get-NormalizedPathIdentity -Path $EngineRoot)) {
            return $null
        }
        if (-not (Test-PathSetExact -Observed @($host.allowedTargetRoots) `
            -Expected $AllowedTargetRoots)) {
            return $null
        }
        $sessionId = [int]$host.sessionId
        if ($sessionId -eq 0 -or
            @($host.explorerSessions | ForEach-Object { [int]$_ }) `
                -notcontains $sessionId) {
            return $null
        }

        $runRoot = (Resolve-Path -LiteralPath ([string]$host.runRoot)).Path
        Assert-NoReparsePoint -Path $runRoot
        $receiptParent = (Resolve-Path -LiteralPath (
            Split-Path -Parent $receiptPath
        )).Path
        if (-not (Test-IsWithinPath -Candidate $runRoot `
            -Parent $EvidenceRoot) -or
            -not $runRoot.Equals(
                $receiptParent,
                [StringComparison]::OrdinalIgnoreCase
            )) {
            return $null
        }
        $requiredHostStages = Get-RequiredHostStageIds `
            -AcceptanceMode $Target.acceptanceMode
        if (-not (Test-StageSetPassed -Stages @($host.stages) `
            -RequiredIds $requiredHostStages)) {
            return $null
        }

        $validationPath = Join-Path $runRoot `
            "target-validation\native-validation-receipt.json"
        if (-not (Test-Path -LiteralPath $validationPath -PathType Leaf)) {
            return $null
        }
        $validationPath = (Resolve-Path -LiteralPath $validationPath).Path
        Assert-NoReparsePoint -Path $validationPath
        $validationRecord = Read-StrictJsonFile -Path $validationPath `
            -PythonExecutable $PythonExecutable `
            -Label "Native validation receipt" `
            -MaximumBytes 4194304
        $validation = $validationRecord.Value
        $expectedRepository = Get-NormalizedPathIdentity `
            -Path $Target.repositoryPath
        $observedRepository = Get-NormalizedPathIdentity `
            -Path ([string]$validation.targetRepositoryPath)
        $validationArtifacts = Get-NormalizedPathIdentity `
            -Path ([string]$validation.artifacts)
        $validationParent = Get-NormalizedPathIdentity `
            -Path (Split-Path -Parent $validationPath)
        if ([string]$validation.schemaVersion -ne "2.0" -or
            [string]$validation.status -ne "passed" -or
            [string]$validation.labSha -ne $LabSha -or
            [string]$validation.targetSha -ne $Target.expectedSha -or
            $observedRepository -ne $expectedRepository -or
            [string]$validation.projectSubpath -ne $Target.projectSubpath -or
            [bool]$validation.targetUnchanged -ne $true -or
            [string]$validation.targetStatusBefore -ne "" -or
            [string]$validation.targetStatusAfter -ne "" -or
            $validationArtifacts -ne $validationParent -or
            (Get-NormalizedPathIdentity `
                -Path ([string]$validation.artifactRoot)) -ne
            (Get-NormalizedPathIdentity -Path $runRoot)) {
            return $null
        }
        if (-not (Test-StageSetPassed -Stages @($validation.stages) `
            -RequiredIds @(
                "toolchain",
                "compile",
                "ruff",
                "pytest",
                "doctor",
                "validate"
            ))) {
            return $null
        }

        $workerStages = @(
            $host.stages | Where-Object {
                [string]$_.id -eq "worker-protocol-acceptance"
            }
        )
        if ($workerStages.Count -ne 1 -or
            [string]$workerStages[0].status -ne "passed") {
            return $null
        }
        $workerReceiptPath = [string]$workerStages[0].result.receipt
        if (-not [IO.Path]::IsPathRooted($workerReceiptPath) -or
            -not (Test-Path -LiteralPath $workerReceiptPath -PathType Leaf) -or
            -not (Test-IsWithinPath -Candidate $workerReceiptPath `
                -Parent $runRoot)) {
            return $null
        }
        $workerReceiptPath = (Resolve-Path `
            -LiteralPath $workerReceiptPath).Path
        Assert-NoReparsePoint -Path $workerReceiptPath
        $workerRecord = Read-StrictJsonFile -Path $workerReceiptPath `
            -PythonExecutable $PythonExecutable `
            -Label "MCP worker receipt" `
            -MaximumBytes 2097152
        $worker = $workerRecord.Value
        $capabilities = $worker.capabilities
        if ([string]$worker.schemaVersion -ne "1.0" -or
            [string]$worker.status -ne "passed" -or
            [string]$worker.server.name -ne "EVAVO Godot Game Test Lab" -or
            [string]$capabilities.bridge -ne "evavo-godot-lab-agent" -or
            [bool]$capabilities.requireInteractiveDesktop -ne $true -or
            [bool]$capabilities.autoProvisionEngines -ne (-not $EngineOffline)) {
            return $null
        }
        if ((Get-NormalizedPathIdentity -Path ([string]$capabilities.labRoot)) -ne
            (Get-NormalizedPathIdentity -Path $LabRoot) -or
            (Get-NormalizedPathIdentity `
                -Path ([string]$capabilities.evidenceRoot)) -ne
            (Get-NormalizedPathIdentity -Path $EvidenceRoot) -or
            (Get-NormalizedPathIdentity `
                -Path ([string]$capabilities.engineRoot)) -ne
            (Get-NormalizedPathIdentity -Path $EngineRoot) -or
            -not (Test-PathSetExact `
                -Observed @($capabilities.allowedTargetRoots) `
                -Expected $AllowedTargetRoots)) {
            return $null
        }
        $requiredTools = @(
            "godot_capabilities",
            "godot_doctor",
            "godot_ensure_engine",
            "godot_inspect",
            "godot_audit",
            "godot_validate",
            "godot_run_bot_qa",
            "godot_run_native_qa",
            "godot_run_linux_sandbox",
            "godot_analyze_run_media",
            "godot_view_image",
            "godot_hear_audio"
        )
        foreach ($tool in $requiredTools) {
            if (@($capabilities.tools) -notcontains $tool) {
                return $null
            }
        }

        $nativeSummaryPath = $null
        $nativeRecord = $null
        if ($Target.acceptanceMode -in @("native", "all")) {
            $nativeSummaryPath = Join-Path $runRoot `
                "target-native\native-agent-summary.json"
            if (-not (Test-Path -LiteralPath $nativeSummaryPath `
                -PathType Leaf)) {
                return $null
            }
            $nativeSummaryPath = (Resolve-Path `
                -LiteralPath $nativeSummaryPath).Path
            Assert-NoReparsePoint -Path $nativeSummaryPath
            $nativeRecord = Read-StrictJsonFile -Path $nativeSummaryPath `
                -PythonExecutable $PythonExecutable `
                -Label "Native journey summary" `
                -MaximumBytes 67108864
            $native = $nativeRecord.Value
            if ([string]$native.schemaVersion -ne "2.0" -or
                [string]$native.status -ne "passed" -or
                [string]$native.labSha -ne $LabSha -or
                [string]$native.targetSha -ne $Target.expectedSha -or
                (Get-NormalizedPathIdentity `
                    -Path ([string]$native.targetGitRoot)) -ne
                $expectedRepository -or
                [string]$native.projectSubpath -ne $Target.projectSubpath -or
                [string]$native.profileSha256 -ne
                $Target.nativeProfileSha256 -or
                [string]$native.validationStatus -ne "passed" -or
                [bool]$native.nativeDesktopEvidence -ne $true -or
                [bool]$native.targetMutationDetected -ne $false -or
                -not (Test-RequiredItemsPassed -Items @($native.journeys))) {
                return $null
            }
        }

        $botSummaryPath = $null
        $botRecord = $null
        if ($Target.acceptanceMode -in @("bot", "all")) {
            $botSummaryPath = Join-Path $runRoot `
                "target-bot\bot-agent-summary.json"
            if (-not (Test-Path -LiteralPath $botSummaryPath `
                -PathType Leaf)) {
                return $null
            }
            $botSummaryPath = (Resolve-Path `
                -LiteralPath $botSummaryPath).Path
            Assert-NoReparsePoint -Path $botSummaryPath
            $botRecord = Read-StrictJsonFile -Path $botSummaryPath `
                -PythonExecutable $PythonExecutable `
                -Label "Deterministic bot summary" `
                -MaximumBytes 67108864
            $bot = $botRecord.Value
            if ([string]$bot.schemaVersion -ne "1.0" -or
                [string]$bot.status -ne "passed" -or
                [string]$bot.labSha -ne $LabSha -or
                [string]$bot.targetSha -ne $Target.expectedSha -or
                (Get-NormalizedPathIdentity `
                    -Path ([string]$bot.targetGitRoot)) -ne
                $expectedRepository -or
                [string]$bot.projectSubpath -ne $Target.projectSubpath -or
                [string]$bot.profileSha256 -ne $Target.botProfileSha256 -or
                [string]$bot.validationStatus -ne "passed" -or
                [bool]$bot.nativeDesktopEvidence -ne $true -or
                [bool]$bot.targetMutationDetected -ne $false -or
                -not (Test-RequiredItemsPassed -Items @($bot.campaigns))) {
                return $null
            }
        }

        return [pscustomobject]@{
            Path = $receiptPath
            HostReceipt = $host
            HostReceiptSha256 = $hostRecord.Sha256
            ValidationReceiptPath = $validationPath
            ValidationReceiptSha256 = $validationRecord.Sha256
            WorkerReceiptPath = $workerReceiptPath
            WorkerReceiptSha256 = $workerRecord.Sha256
            NativeSummaryPath = $nativeSummaryPath
            NativeSummarySha256 = if ($nativeRecord) {
                $nativeRecord.Sha256
            }
            else { $null }
            BotSummaryPath = $botSummaryPath
            BotSummarySha256 = if ($botRecord) {
                $botRecord.Sha256
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
        $_ -eq $normalized -or
        $_.StartsWith($prefix, [StringComparison]::Ordinal)
    })
}
