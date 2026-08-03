$failure = $null
$mutexAcquired = $false
$mutexAbandoned = $false
$estateMutex = [Threading.Mutex]::new(
    $false,
    "Local\EVAVO.GodotLab.EstateAcceptance"
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
        throw "Another Godot estate acceptance owns the machine-level lease."
    }
    $receipt.abandonedMutexRecovered = $mutexAbandoned
    for ($index = 0; $index -lt $targets.Count; $index++) {
        $target = $targets[$index]
        $targetResult = [ordered]@{
            id = $target.id
            repositoryPath = $target.repositoryPath
            expectedSha = $target.expectedSha
            expectedProjectKind = $target.expectedProjectKind
            acceptanceMode = $target.acceptanceMode
            nativeProfileSha256 = $target.nativeProfileSha256
            botProfileSha256 = $target.botProfileSha256
            status = "running"
            startedAt = [DateTimeOffset]::UtcNow.ToString("o")
        }
        [void]$targetResults.Add($targetResult)
        $beforeReceipts = [Collections.Generic.HashSet[string]]::new(
            [StringComparer]::OrdinalIgnoreCase
        )
        foreach ($path in (Get-HostReceiptPaths -Root $evidence)) {
            [void]$beforeReceipts.Add($path)
        }

        try {
            $parameters = @{
                LabRoot = $lab
                AllowedTargetRoots = @($resolvedRoots)
                EvidenceRoot = $evidence
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
                if ($RegisterWorker) { $parameters.RegisterWorker = $true }
                if ($StartWorker) { $parameters.StartWorker = $true }
            }

            Write-Host "[godot-lab] Estate target $($target.id): $($target.acceptanceMode)"
            & $hostAcceptance @parameters

            $newReceipts = @(
                Get-HostReceiptPaths -Root $evidence |
                    Where-Object { -not $beforeReceipts.Contains($_) }
            )
            $matches = @(
                $newReceipts | ForEach-Object {
                    Test-HostReceiptCandidate -Path $_ -Target $target `
                        -LabSha $labSha -EvidenceRoot $evidence
                } | Where-Object { $null -ne $_ }
            )
            if ($matches.Count -ne 1) {
                throw (
                    "Target $($target.id) did not create exactly one " +
                    "target-bound accepted host receipt."
                )
            }
            $accepted = $matches[0]
            $hostReceiptPath = $accepted.Path
            $hostReceipt = $accepted.HostReceipt

            $shaAfter = Get-GitText -Root $target.repositoryPath -Arguments @(
                "rev-parse", "HEAD"
            ) -Label "Recheck target $($target.id) SHA"
            $statusAfter = Get-GitText -Root $target.repositoryPath -Arguments @(
                "status", "--porcelain=v1", "--untracked-files=all"
            ) -Label "Recheck target $($target.id) status"
            if ($shaAfter -ne $target.expectedSha -or $statusAfter) {
                throw "Target $($target.id) changed during estate acceptance."
            }

            $targetResult.status = "passed"
            $targetResult.hostReceipt = $hostReceiptPath
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
            $targetResult.ignoredConcurrentHostReceipts = @(
                $newReceipts | Where-Object { $_ -ne $hostReceiptPath }
            )
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

    $labShaAfter = Get-GitText -Root $lab -Arguments @(
        "rev-parse", "HEAD"
    ) -Label "Recheck Lab SHA"
    $labStatusAfter = Get-GitText -Root $lab -Arguments @(
        "status", "--porcelain=v1", "--untracked-files=all"
    ) -Label "Recheck Lab status"
    if ($labShaAfter -ne $labSha -or $labStatusAfter) {
        throw "The Lab checkout changed during estate acceptance."
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
    if ($mutexAcquired) {
        try {
            $estateMutex.ReleaseMutex()
        }
        catch [ApplicationException] {
        }
    }
    $estateMutex.Dispose()
}

if ($failure) {
    throw $failure
}
Write-Host "[godot-lab] Estate acceptance passed. Receipt: $receiptPath"
