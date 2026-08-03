$receipt.hostReceiptPolicy = "explicit-target-root-v1"
$failure = $null
$receiptWriteFailure = $null
$mutexAcquired = $false
$mutexAbandoned = $false
$estateMutex = [Threading.Mutex]::new(
    $false,
    "Global\EVAVO.GodotLab.EstateAcceptance"
)

try {
    try {
        $mutexAcquired = $estateMutex.WaitOne(
            [TimeSpan]::FromSeconds($EstateLockTimeoutSeconds)
        )
    }
    catch [Threading.AbandonedMutexException] {
        $mutexAcquired = $true
        $mutexAbandoned = $true
    }
    if (-not $mutexAcquired) {
        throw "Another Godot estate acceptance owns the machine-wide lease."
    }
    $receipt.abandonedMutexRecovered = $mutexAbandoned
    $targetsRoot = Join-Path $runRoot "targets"
    New-Item -ItemType Directory -Path $targetsRoot | Out-Null
    Assert-NoReparsePoint -Path $targetsRoot
    for ($index = 0; $index -lt $targets.Count; $index++) {
        $target = $targets[$index]
        $targetDirectoryName = "{0:D2}-{1}-{2}" -f @(
            ($index + 1),
            $target.id,
            $target.expectedSha.Substring(0, 12)
        )
        $targetEvidenceRoot = Join-Path $targetsRoot $targetDirectoryName
        $hostRunRoot = Join-Path $targetEvidenceRoot "host"
        $hostReceiptPath = Join-Path $hostRunRoot "host-acceptance.json"
        $targetResult = [ordered]@{
            id = $target.id
            repositoryPath = $target.repositoryPath
            expectedSha = $target.expectedSha
            expectedProjectKind = $target.expectedProjectKind
            acceptanceMode = $target.acceptanceMode
            nativeProfileSha256 = $target.nativeProfileSha256
            botProfileSha256 = $target.botProfileSha256
            hostReceiptPolicy = "explicit-target-root-v1"
            evidenceDirectoryName = $targetDirectoryName
            hostRunRoot = $hostRunRoot
            hostReceipt = $hostReceiptPath
            ignoredConcurrentHostReceipts = @()
            status = "running"
            startedAt = [DateTimeOffset]::UtcNow.ToString("o")
        }
        [void]$targetResults.Add($targetResult)

        try {
            New-Item -ItemType Directory -Path $targetEvidenceRoot |
                Out-Null
            Assert-NoReparsePoint -Path $targetEvidenceRoot
            $parameters = @{
                LabRoot = $lab
                AllowedTargetRoots = @($resolvedRoots)
                EvidenceRoot = $evidence
                HostRunRoot = $hostRunRoot
                EngineRoot = $engines
                TaskName = $TaskName
                Port = $Port
                WorkerStartupTimeoutSeconds = $WorkerStartupTimeoutSeconds
                ExpectedLabSha = $labSha
                AcceptanceRepositoryPath = $target.repositoryPath
                ExpectedTargetSha = $target.expectedSha
                ProjectSubpath = $target.projectSubpath
                AcceptanceMode = $target.acceptanceMode
            }
            if ($target.nativeProfilePath) {
                $parameters.NativeProfilePath = $target.nativeProfilePath
            }
            if ($target.botProfilePath) {
                $parameters.BotProfilePath = $target.botProfilePath
            }
            if ($EngineOffline) {
                $parameters.EngineOffline = $true
            }
            if ($index -eq 0) {
                if ($RegisterWorker) {
                    $parameters.RegisterWorker = $true
                }
                if ($StartWorker) {
                    $parameters.StartWorker = $true
                }
            }

            Write-Host (
                "[godot-lab] Estate target $($target.id): " +
                $target.acceptanceMode
            )
            & $hostAcceptance @parameters

            if (-not (Test-Path -LiteralPath $hostReceiptPath `
                -PathType Leaf)) {
                throw (
                    "Target $($target.id) did not create its exact " +
                    "host receipt: $hostReceiptPath"
                )
            }
            $accepted = Test-HostReceiptCandidate `
                -Path $hostReceiptPath `
                -Target $target `
                -LabRoot $lab `
                -LabSha $labSha `
                -AllowedTargetRoots @($resolvedRoots) `
                -EvidenceRoot $evidence `
                -EngineRoot $engines `
                -EngineOffline ([bool]$EngineOffline) `
                -PythonExecutable $python
            if ($null -eq $accepted) {
                throw (
                    "Target $($target.id) target-bound accepted host receipt failed. " +
                    "The exact host receipt failed admission: $hostReceiptPath"
                )
            }
            $hostReceipt = $accepted.HostReceipt

            $shaAfter = Get-GitText -Root $target.repositoryPath -Arguments @(
                "rev-parse",
                "HEAD"
            ) -Label "Recheck target $($target.id) SHA"
            $statusAfter = Get-GitText -Root $target.repositoryPath -Arguments @(
                "status",
                "--porcelain=v1",
                "--untracked-files=all"
            ) -Label "Recheck target $($target.id) status"
            if ($shaAfter -ne $target.expectedSha -or $statusAfter) {
                throw "Target $($target.id) changed during estate acceptance."
            }

            $targetResult.status = "passed"
            $targetResult.hostReceiptSha256 = $accepted.HostReceiptSha256
            $targetResult.hostRunRoot = [string]$hostReceipt.runRoot
            $targetResult.validationReceipt = $accepted.ValidationReceiptPath
            $targetResult.validationReceiptSha256 = `
                $accepted.ValidationReceiptSha256
            $targetResult.workerProtocolReceipt = $accepted.WorkerReceiptPath
            $targetResult.workerProtocolReceiptSha256 = `
                $accepted.WorkerReceiptSha256
            $targetResult.nativeSummary = $accepted.NativeSummaryPath
            $targetResult.nativeSummarySha256 = $accepted.NativeSummarySha256
            $targetResult.botSummary = $accepted.BotSummaryPath
            $targetResult.botSummarySha256 = $accepted.BotSummarySha256
            $targetResult.workerProtocolProbed = $true
        }
        catch {
            $targetResult.status = "failed"
            $targetResult.error = $_.Exception.Message
            throw
        }
        finally {
            $targetResult.finishedAt = [DateTimeOffset]::UtcNow.ToString("o")
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
    $sourceErrors = [Collections.ArrayList]::new()

    $labCheck = [ordered]@{
        id = "lab"
        repositoryPath = $lab
        expectedSha = $labSha
        status = "running"
    }
    try {
        $labShaAfter = Get-GitText -Root $lab -Arguments @(
            "rev-parse",
            "HEAD"
        ) -Label "Final Lab SHA"
        $labStatusAfter = Get-GitText -Root $lab -Arguments @(
            "status",
            "--porcelain=v1",
            "--untracked-files=all"
        ) -Label "Final Lab status"
        $labCheck.observedSha = $labShaAfter
        $labCheck.gitStatus = $labStatusAfter
        if ($labShaAfter -ne $labSha -or $labStatusAfter) {
            throw "The Lab checkout changed during estate acceptance."
        }
        $labCheck.status = "passed"
    }
    catch {
        $labCheck.status = "failed"
        $labCheck.error = $_.Exception.Message
        [void]$sourceErrors.Add($_.Exception.Message)
    }
    finally {
        [void]$sourceChecks.Add($labCheck)
    }

    foreach ($target in $targets) {
        $targetCheck = [ordered]@{
            id = $target.id
            repositoryPath = $target.repositoryPath
            expectedSha = $target.expectedSha
            status = "running"
        }
        try {
            $finalSha = Get-GitText -Root $target.repositoryPath -Arguments @(
                "rev-parse",
                "HEAD"
            ) -Label "Final target $($target.id) SHA"
            $finalStatus = Get-GitText -Root $target.repositoryPath -Arguments @(
                "status",
                "--porcelain=v1",
                "--untracked-files=all"
            ) -Label "Final target $($target.id) status"
            $targetCheck.observedSha = $finalSha
            $targetCheck.gitStatus = $finalStatus
            if ($finalSha -ne $target.expectedSha -or $finalStatus) {
                throw "Target $($target.id) changed during estate acceptance."
            }
            $targetCheck.status = "passed"
        }
        catch {
            $targetCheck.status = "failed"
            $targetCheck.error = $_.Exception.Message
            [void]$sourceErrors.Add($_.Exception.Message)
        }
        finally {
            [void]$sourceChecks.Add($targetCheck)
        }
    }

    if ($sourceErrors.Count -ne 0) {
        $sourceMessage = "Final source verification failed: " + `
            ($sourceErrors -join " | ")
        $receipt.status = "failed"
        if ($receipt.error) {
            $receipt.error = "$($receipt.error) | $sourceMessage"
        }
        else {
            $receipt.error = $sourceMessage
        }
        if (-not $failure) {
            $failure = [InvalidOperationException]::new($sourceMessage)
        }
    }

    $receipt.finishedAt = [DateTimeOffset]::UtcNow.ToString("o")
    try {
        Write-AtomicJson -Path $receiptPath -Value $receipt
    }
    catch {
        $receiptWriteFailure = $_.Exception
        if ($failure) {
            $failure = [InvalidOperationException]::new(
                "$($failure.Message) | Receipt write failed: " +
                $receiptWriteFailure.Message,
                $failure
            )
        }
        else {
            $failure = $receiptWriteFailure
        }
    }
    finally {
        if ($mutexAcquired) {
            try {
                $estateMutex.ReleaseMutex()
            }
            catch [ApplicationException] {
            }
        }
        $estateMutex.Dispose()
    }
}

if ($failure) {
    throw $failure
}
Write-Host "[godot-lab] Estate acceptance passed. Receipt: $receiptPath"
