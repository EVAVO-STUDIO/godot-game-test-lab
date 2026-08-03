function Test-StageSetPassed {
    param(
        [object]$Stages,
        [string[]]$RequiredIds
    )
    Assert-JsonObjectArray -Value $Stages -Label "Receipt stages"
    $allStages = @($Stages)
    if ($allStages.Count -eq 0) {
        return $false
    }
    $ids = @()
    foreach ($stage in $allStages) {
        Assert-JsonString -Value $stage.id -Label "Receipt stage id"
        Assert-JsonString -Value $stage.status -Label "Receipt stage status"
        Assert-JsonString -Value $stage.startedAt `
            -Label "Receipt stage startedAt"
        Assert-JsonString -Value $stage.finishedAt `
            -Label "Receipt stage finishedAt"
        if ($stage.status -ne "passed") {
            return $false
        }
        if (-not $stage.id) {
            return $false
        }
        $ids += $stage.id
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
    param([object]$Items)
    Assert-JsonObjectArray -Value $Items -Label "Required result items"
    $required = @()
    foreach ($item in $Items) {
        Assert-JsonBoolean -Value $item.required `
            -Label "Required result item required"
        Assert-JsonString -Value $item.status `
            -Label "Required result item status"
        if ($item.required) {
            $required += $item
        }
    }
    if ($required.Count -eq 0) {
        return $false
    }
    return @(
        $required | Where-Object { $_.status -ne "passed" }
    ).Count -eq 0
}

function Test-HostSourceChecksPassed {
    param(
        [object]$Checks,
        [object]$Target,
        [string]$LabRoot,
        [string]$LabSha
    )
    Assert-JsonObjectArray -Value $Checks -Label "Host sourceChecks"
    $allChecks = @($Checks)
    if ($allChecks.Count -ne 2) {
        return $false
    }
    foreach ($check in $allChecks) {
        Assert-ExactProperties -Value $check `
            -Expected @(
                "id",
                "repositoryPath",
                "expectedSha",
                "observedSha",
                "gitStatus",
                "status"
            ) `
            -Label "Host source check"
        foreach ($property in @(
            "id",
            "repositoryPath",
            "expectedSha",
            "observedSha",
            "gitStatus",
            "status"
        )) {
            Assert-JsonString -Value $check.$property `
                -Label "Host source check $property"
        }
        if ($check.status -ne "passed" -or
            $check.observedSha -ne $check.expectedSha -or
            $check.gitStatus -ne "") {
            return $false
        }
    }

    $labChecks = @($allChecks | Where-Object { $_.id -eq "lab" })
    $targetChecks = @($allChecks | Where-Object { $_.id -eq $Target.id })
    if ($labChecks.Count -ne 1 -or $targetChecks.Count -ne 1) {
        return $false
    }
    $labCheck = $labChecks[0]
    $targetCheck = $targetChecks[0]
    return (
        $labCheck.expectedSha -eq $LabSha -and
        (Get-NormalizedPathIdentity -Path $labCheck.repositoryPath) -eq
        (Get-NormalizedPathIdentity -Path $LabRoot) -and
        $targetCheck.expectedSha -eq $Target.expectedSha -and
        (Get-NormalizedPathIdentity -Path $targetCheck.repositoryPath) -eq
        (Get-NormalizedPathIdentity -Path $Target.repositoryPath)
    )
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
        Assert-ExactProperties -Value $host `
            -Expected @(
                "schemaVersion",
                "status",
                "startedAt",
                "labRoot",
                "labSha",
                "evidenceRoot",
                "runRoot",
                "engineRoot",
                "allowedTargetRoots",
                "engineOffline",
                "machine",
                "user",
                "sessionId",
                "explorerSessions",
                "endpoint",
                "stages",
                "sourceChecks",
                "finishedAt"
            ) `
            -Label "Host acceptance receipt"
        foreach ($property in @(
            "schemaVersion",
            "status",
            "startedAt",
            "labRoot",
            "labSha",
            "evidenceRoot",
            "runRoot",
            "engineRoot",
            "machine",
            "user",
            "endpoint",
            "finishedAt"
        )) {
            Assert-JsonString -Value $host.$property `
                -Label "Host acceptance $property"
        }
        Assert-JsonBoolean -Value $host.engineOffline `
            -Label "Host acceptance engineOffline"
        Assert-JsonInteger -Value $host.sessionId `
            -Label "Host acceptance sessionId"
        Assert-JsonStringArray -Value $host.allowedTargetRoots `
            -Label "Host acceptance allowedTargetRoots"
        Assert-JsonIntegerArray -Value $host.explorerSessions `
            -Label "Host acceptance explorerSessions"
        Assert-JsonObjectArray -Value $host.stages `
            -Label "Host acceptance stages"
        Assert-JsonObjectArray -Value $host.sourceChecks `
            -Label "Host acceptance sourceChecks"
        if ($host.schemaVersion -ne "1.1" -or
            $host.status -ne "passed" -or
            $host.labSha -ne $LabSha -or
            $host.engineOffline -ne $EngineOffline) {
            return $null
        }
        if ((Get-NormalizedPathIdentity -Path $host.labRoot) -ne
            (Get-NormalizedPathIdentity -Path $LabRoot) -or
            (Get-NormalizedPathIdentity -Path $host.evidenceRoot) -ne
            (Get-NormalizedPathIdentity -Path $EvidenceRoot) -or
            (Get-NormalizedPathIdentity -Path $host.engineRoot) -ne
            (Get-NormalizedPathIdentity -Path $EngineRoot)) {
            return $null
        }
        if (-not (Test-PathSetExact -Observed $host.allowedTargetRoots `
            -Expected $AllowedTargetRoots)) {
            return $null
        }
        if ($host.sessionId -eq 0 -or
            $host.explorerSessions -notcontains $host.sessionId) {
            return $null
        }
        if (-not (Test-HostSourceChecksPassed `
            -Checks $host.sourceChecks `
            -Target $Target `
            -LabRoot $LabRoot `
            -LabSha $LabSha)) {
            return $null
        }

        $runRoot = (Resolve-Path -LiteralPath $host.runRoot).Path
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
        if (-not (Test-StageSetPassed -Stages $host.stages `
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
        Assert-ExactProperties -Value $validation `
            -Expected @(
                "schemaVersion",
                "status",
                "startedAt",
                "labRepository",
                "labRoot",
                "labSha",
                "targetRepositoryPath",
                "targetSha",
                "projectSubpath",
                "projectPath",
                "allowedTargetRoots",
                "artifactRoot",
                "artifacts",
                "python",
                "minimumGodotVersion",
                "timeoutSeconds",
                "bootFrames",
                "targetUnchanged",
                "stages",
                "targetStatusBefore",
                "targetStatusAfter",
                "finishedAt"
            ) `
            -Label "Native validation receipt"
        foreach ($property in @(
            "schemaVersion",
            "status",
            "startedAt",
            "labRepository",
            "labRoot",
            "labSha",
            "targetRepositoryPath",
            "targetSha",
            "projectSubpath",
            "projectPath",
            "artifactRoot",
            "artifacts",
            "python",
            "minimumGodotVersion",
            "targetStatusBefore",
            "targetStatusAfter",
            "finishedAt"
        )) {
            Assert-JsonString -Value $validation.$property `
                -Label "Native validation $property"
        }
        Assert-JsonStringArray -Value $validation.allowedTargetRoots `
            -Label "Native validation allowedTargetRoots"
        Assert-JsonInteger -Value $validation.timeoutSeconds `
            -Label "Native validation timeoutSeconds"
        Assert-JsonInteger -Value $validation.bootFrames `
            -Label "Native validation bootFrames"
        Assert-JsonBoolean -Value $validation.targetUnchanged `
            -Label "Native validation targetUnchanged"
        Assert-JsonObjectArray -Value $validation.stages `
            -Label "Native validation stages"

        $expectedRepository = Get-NormalizedPathIdentity `
            -Path $Target.repositoryPath
        $observedRepository = Get-NormalizedPathIdentity `
            -Path $validation.targetRepositoryPath
        $validationArtifacts = Get-NormalizedPathIdentity `
            -Path $validation.artifacts
        $validationParent = Get-NormalizedPathIdentity `
            -Path (Split-Path -Parent $validationPath)
        if ($validation.schemaVersion -ne "2.0" -or
            $validation.status -ne "passed" -or
            $validation.labSha -ne $LabSha -or
            $validation.targetSha -ne $Target.expectedSha -or
            $observedRepository -ne $expectedRepository -or
            $validation.projectSubpath -ne $Target.projectSubpath -or
            $validation.targetUnchanged -ne $true -or
            $validation.targetStatusBefore -ne "" -or
            $validation.targetStatusAfter -ne "" -or
            $validationArtifacts -ne $validationParent -or
            (Get-NormalizedPathIdentity `
                -Path $validation.artifactRoot) -ne
            (Get-NormalizedPathIdentity -Path $runRoot)) {
            return $null
        }
        if (-not (Test-PathSetExact `
            -Observed $validation.allowedTargetRoots `
            -Expected $AllowedTargetRoots)) {
            return $null
        }
        if (-not (Test-StageSetPassed -Stages $validation.stages `
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
                $_.id -eq "worker-protocol-acceptance"
            }
        )
        if ($workerStages.Count -ne 1 -or
            $workerStages[0].status -ne "passed") {
            return $null
        }
        Assert-JsonObject -Value $workerStages[0].result `
            -Label "Worker protocol stage result"
        Assert-ExactProperties -Value $workerStages[0].result `
            -Expected @(
                "receipt",
                "bridge",
                "allowedTargetRoots",
                "autoProvisionEngines"
            ) `
            -Label "Worker protocol stage result"
        Assert-JsonString -Value $workerStages[0].result.receipt `
            -Label "Worker protocol receipt path"
        Assert-JsonString -Value $workerStages[0].result.bridge `
            -Label "Worker protocol bridge"
        Assert-JsonStringArray `
            -Value $workerStages[0].result.allowedTargetRoots `
            -Label "Worker protocol allowedTargetRoots"
        Assert-JsonBoolean `
            -Value $workerStages[0].result.autoProvisionEngines `
            -Label "Worker protocol autoProvisionEngines"
        $workerReceiptPath = $workerStages[0].result.receipt
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
        Assert-ExactProperties -Value $worker `
            -Expected @(
                "schemaVersion",
                "status",
                "endpoint",
                "server",
                "capabilities"
            ) `
            -Label "MCP worker receipt"
        Assert-JsonString -Value $worker.schemaVersion `
            -Label "MCP worker schemaVersion"
        Assert-JsonString -Value $worker.status `
            -Label "MCP worker status"
        Assert-JsonString -Value $worker.endpoint `
            -Label "MCP worker endpoint"
        Assert-ExactProperties -Value $worker.server `
            -Expected @("name", "version") `
            -Label "MCP worker server"
        Assert-JsonString -Value $worker.server.name `
            -Label "MCP worker server name"
        Assert-JsonString -Value $worker.server.version `
            -Label "MCP worker server version"
        Assert-ExactProperties -Value $worker.capabilities `
            -Expected @(
                "bridge",
                "labRoot",
                "allowedTargetRoots",
                "evidenceRoot",
                "engineRoot",
                "requireInteractiveDesktop",
                "autoProvisionEngines",
                "tools"
            ) `
            -Label "MCP worker capabilities"
        $capabilities = $worker.capabilities
        foreach ($property in @(
            "bridge",
            "labRoot",
            "evidenceRoot",
            "engineRoot"
        )) {
            Assert-JsonString -Value $capabilities.$property `
                -Label "MCP capability $property"
        }
        Assert-JsonStringArray -Value $capabilities.allowedTargetRoots `
            -Label "MCP capability allowedTargetRoots"
        Assert-JsonBoolean -Value $capabilities.requireInteractiveDesktop `
            -Label "MCP capability requireInteractiveDesktop"
        Assert-JsonBoolean -Value $capabilities.autoProvisionEngines `
            -Label "MCP capability autoProvisionEngines"
        Assert-JsonStringArray -Value $capabilities.tools `
            -Label "MCP capability tools"
        if ($worker.schemaVersion -ne "1.0" -or
            $worker.status -ne "passed" -or
            $worker.server.name -ne "EVAVO Godot Game Test Lab" -or
            $capabilities.bridge -ne "evavo-godot-lab-agent" -or
            $capabilities.requireInteractiveDesktop -ne $true -or
            $capabilities.autoProvisionEngines -ne (-not $EngineOffline)) {
            return $null
        }
        if ((Get-NormalizedPathIdentity -Path $capabilities.labRoot) -ne
            (Get-NormalizedPathIdentity -Path $LabRoot) -or
            (Get-NormalizedPathIdentity `
                -Path $capabilities.evidenceRoot) -ne
            (Get-NormalizedPathIdentity -Path $EvidenceRoot) -or
            (Get-NormalizedPathIdentity `
                -Path $capabilities.engineRoot) -ne
            (Get-NormalizedPathIdentity -Path $EngineRoot) -or
            -not (Test-PathSetExact `
                -Observed $capabilities.allowedTargetRoots `
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
            if ($capabilities.tools -notcontains $tool) {
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
            foreach ($property in @(
                "schemaVersion",
                "status",
                "labSha",
                "targetSha",
                "targetGitRoot",
                "projectSubpath",
                "profileSha256",
                "validationStatus"
            )) {
                Assert-JsonString -Value $native.$property `
                    -Label "Native journey $property"
            }
            Assert-JsonBoolean -Value $native.nativeDesktopEvidence `
                -Label "Native journey nativeDesktopEvidence"
            Assert-JsonBoolean -Value $native.targetMutationDetected `
                -Label "Native journey targetMutationDetected"
            Assert-JsonObjectArray -Value $native.journeys `
                -Label "Native journey journeys"
            if ($native.schemaVersion -ne "2.0" -or
                $native.status -ne "passed" -or
                $native.labSha -ne $LabSha -or
                $native.targetSha -ne $Target.expectedSha -or
                (Get-NormalizedPathIdentity `
                    -Path $native.targetGitRoot) -ne
                $expectedRepository -or
                $native.projectSubpath -ne $Target.projectSubpath -or
                $native.profileSha256 -ne
                $Target.nativeProfileSha256 -or
                $native.validationStatus -ne "passed" -or
                $native.nativeDesktopEvidence -ne $true -or
                $native.targetMutationDetected -ne $false -or
                -not (Test-RequiredItemsPassed -Items $native.journeys)) {
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
            foreach ($property in @(
                "schemaVersion",
                "status",
                "labSha",
                "targetSha",
                "targetGitRoot",
                "projectSubpath",
                "profileSha256",
                "validationStatus"
            )) {
                Assert-JsonString -Value $bot.$property `
                    -Label "Deterministic bot $property"
            }
            Assert-JsonBoolean -Value $bot.nativeDesktopEvidence `
                -Label "Deterministic bot nativeDesktopEvidence"
            Assert-JsonBoolean -Value $bot.targetMutationDetected `
                -Label "Deterministic bot targetMutationDetected"
            Assert-JsonObjectArray -Value $bot.campaigns `
                -Label "Deterministic bot campaigns"
            if ($bot.schemaVersion -ne "1.0" -or
                $bot.status -ne "passed" -or
                $bot.labSha -ne $LabSha -or
                $bot.targetSha -ne $Target.expectedSha -or
                (Get-NormalizedPathIdentity `
                    -Path $bot.targetGitRoot) -ne
                $expectedRepository -or
                $bot.projectSubpath -ne $Target.projectSubpath -or
                $bot.profileSha256 -ne $Target.botProfileSha256 -or
                $bot.validationStatus -ne "passed" -or
                $bot.nativeDesktopEvidence -ne $true -or
                $bot.targetMutationDetected -ne $false -or
                -not (Test-RequiredItemsPassed -Items $bot.campaigns)) {
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
