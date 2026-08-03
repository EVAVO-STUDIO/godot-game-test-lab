from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATHS = (
    ROOT / "scripts" / "Invoke-GodotLabEstateAcceptance.ps1",
    ROOT / "scripts" / "GodotLabEstateAcceptance.Common.ps1",
    ROOT / "scripts" / "GodotLabEstateAcceptance.Receipt.ps1",
    ROOT / "scripts" / "GodotLabEstateAcceptance.Preflight.ps1",
    ROOT / "scripts" / "GodotLabEstateAcceptance.Execute.ps1",
)
STRICT_JSON = ROOT / "src" / "godot_game_test_lab" / "strict_json.py"
DOC = ROOT / "docs" / "WINDOWS_ESTATE_ACCEPTANCE.md"


def test_estate_acceptance_is_exact_bounded_and_fail_closed() -> None:
    source = "\n".join(path.read_text(encoding="utf-8") for path in SCRIPT_PATHS)
    strict_json = STRICT_JSON.read_text(encoding="utf-8")
    for token in (
        "GodotLabEstateAcceptance.Common.ps1",
        "GodotLabEstateAcceptance.Receipt.ps1",
        "GodotLabEstateAcceptance.Preflight.ps1",
        "GodotLabEstateAcceptance.Execute.ps1",
        "Estate acceptance must run on Windows",
        "strict_json.py",
        "Read-StrictJsonFile",
        "Assert-ExactProperties",
        "Assert-JsonString",
        "Assert-JsonBoolean",
        "Assert-JsonInteger",
        "Assert-JsonStringArray",
        "Assert-JsonObjectArray",
        "bounded-utf8-unique-names-stable-file-v2",
        "closed-authority-types-v1",
        "global-before-preflight-v1",
        "schemaVersion must be 1.0",
        "between 2 and 16 targets",
        "exact 40-character expectedSha",
        "Target ids must be unique",
        "At least one allowed target root is required",
        "repository-relative",
        "ls-files",
        "--error-unmatch",
        "Target $id is outside every allowed target root",
        "Target $id repositoryPath must be the Git top-level directory",
        "projectSubpath must be a traversal-free",
        "project.godot",
        "expectedProjectKind must be gdscript or csharp",
        "tracked .csproj or .cs files",
        "pure tracked ",
        "GDScript project.",
        "ManifestPath must remain outside",
        "at least one GDScript target and one C# target",
        "at least one native visible journey",
        "at least one deterministic bot journey",
        "Test-GodotLabAgentHost.ps1",
        "ExpectedTargetSha = $target.expectedSha",
        "HostRunRoot = $hostRunRoot",
        'hostReceiptPolicy = "explicit-target-root-v1"',
        'Join-Path $runRoot "targets"',
        '"{0:D2}-{1}-{2}" -f @(',
        "expectedSha.Substring(0, 12)",
        "evidenceDirectoryName = $targetDirectoryName",
        "ignoredConcurrentHostReceipts = @()",
        "Join-Path $targetsRoot $targetDirectoryName",
        "did not create its exact",
        "exact host receipt failed",
        "EstateLockTimeoutSeconds",
        "Global\\EVAVO.GodotLab.EstateAcceptance",
        "machine-wide lease",
        "worker-protocol-acceptance",
        "Test-HostReceiptCandidate",
        "Test-HostSourceChecksPassed",
        "Test-StageSetPassed",
        "Test-RequiredItemsPassed",
        "native-validation-receipt.json",
        "native-agent-summary.json",
        "bot-agent-summary.json",
        "requireInteractiveDesktop",
        "autoProvisionEngines",
        "profileSha256",
        "hostReceiptSha256",
        "workerProtocolReceiptSha256",
        "validationReceiptSha256",
        "Final source verification failed",
        "sourceChecks",
        'schemaVersion = "1.3"',
        'schemaVersion -ne "1.1"',
        "estate-acceptance.json",
        "Write-AtomicJson -Path $receiptPath",
        "$estateMutex.ReleaseMutex()",
        "$estateMutex.Dispose()",
    ):
        assert token in source, token

    for token in (
        "os.open(source, flags)",
        "os.fstat(descriptor)",
        "os.path.samestat",
        "JSON path changed before it was opened",
        "JSON file changed while it was read",
        "maximum_bytes + 1",
        "hashlib.sha256(payload).hexdigest()",
    ):
        assert token in strict_json, token

    for forbidden in (
        "git commit",
        "git push",
        "git reset --hard",
        "gh pr",
        "Start-Process powershell -Verb RunAs",
        "0.0.0.0",
        "wrangler deploy",
        "vercel deploy",
        "SkipWorkerProbe = $true",
        "Local\\EVAVO.GodotLab.EstateAcceptance",
        "Get-HostReceiptPaths -Root $evidence",
        "$beforeReceipts",
        "$newReceipts",
        "[bool]$host.engineOffline",
        "[int]$host.sessionId",
        "[bool]$validation.targetUnchanged",
    ):
        assert forbidden not in source

    assert source.count("[Threading.Mutex]::new(") == 1
    wait = source.index("$estateMutex.WaitOne(")
    preflight = source.index(
        '. $modulePaths["GodotLabEstateAcceptance.Preflight.ps1"]'
    )
    execute = source.index(
        '. $modulePaths["GodotLabEstateAcceptance.Execute.ps1"]'
    )
    assert wait < preflight < execute


def test_estate_acceptance_documentation_preserves_truth_boundary() -> None:
    source = DOC.read_text(encoding="utf-8")
    for token in (
        "Invoke-GodotLabEstateAcceptance.ps1",
        '"expectedProjectKind": "gdscript"',
        '"expectedProjectKind": "csharp"',
        '"acceptanceMode": "all"',
        "estate-acceptance.json",
        "mcp-worker-acceptance.json",
        "Every target",
        "target-bound",
        "machine-wide Windows named mutex",
        "before manifest and target preflight",
        "duplicate JSON",
        "tracked repository-relative",
        "stable open file descriptor",
        "exact JSON types",
        "explicit target-owned host run root",
        "<ordinal>-<target-id>-<sha-prefix>",
        "Windows device-name and",
        "not scan the shared host receipt tree",
        "schema 1.3",
        "host-acceptance.json schema 1.1",
        "every exit path",
        "SHA-256",
        "physical controller",
        "human game-feel",
    ):
        assert token in source, token
