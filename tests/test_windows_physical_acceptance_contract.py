from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "Invoke-GodotLabPhysicalAcceptance.ps1"
DOC = ROOT / "docs" / "PHYSICAL_WINDOWS_ACCEPTANCE.md"


def test_physical_acceptance_builds_exact_two_family_estate() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    for token in (
        "Physical estate acceptance must run on Windows.",
        "GodotLabEstateAcceptance.Common.ps1",
        "Invoke-GodotLabEstateAcceptance.ps1",
        "Initialize-GodotLabAgentHost.ps1",
        "GdscriptRepositoryPath",
        "CSharpRepositoryPath",
        "NativeProfilePath",
        "BotProfilePath",
        "AllowedTargetRoots",
        "Resolve-TargetOwnedFile",
        "The Lab checkout must be completely clean",
        "$Label must be completely clean before physical acceptance.",
        'id = "gdscript-game"',
        'expectedProjectKind = "gdscript"',
        'acceptanceMode = "validate"',
        'id = "csharp-game"',
        'expectedProjectKind = "csharp"',
        'acceptanceMode = "all"',
        'Join-Path $evidence "estate-manifests"',
        "Write-AtomicJson -Path $manifestPath",
        "ExpectedLabSha = $labSha",
        "RegisterWorker = $true",
        "StartWorker = $true",
        "Physical estate acceptance completed.",
    ):
        assert token in source, token

    for forbidden in (
        "git commit",
        "git push",
        "git reset --hard",
        "gh pr",
        "Start-Process powershell -Verb RunAs",
        "wrangler deploy",
        "vercel deploy",
        "0.0.0.0",
        "SkipWorkerProbe",
    ):
        assert forbidden not in source


def test_physical_acceptance_writes_manifest_before_estate_execution() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    manifest = source.index("Write-AtomicJson -Path $manifestPath")
    initialize = source.index("if ($InitializeHost)")
    execute = source.index("& $estate @estateParameters")

    assert manifest < initialize < execute
    assert source.count('schemaVersion = "1.0"') == 1
    assert source.count('acceptanceMode = "all"') == 1
    assert source.count('acceptanceMode = "validate"') == 1


def test_physical_acceptance_runbook_preserves_machine_truth_boundary() -> None:
    source = DOC.read_text(encoding="utf-8")

    for token in (
        "Invoke-GodotLabPhysicalAcceptance.ps1",
        "one pure GDScript project",
        "one C# project",
        "estate-manifests",
        "estate-acceptance.json schema 1.3",
        "host-acceptance.json schema 1.1",
        "mcp-worker-acceptance.json",
        "native-validation-receipt.json",
        "native-agent-summary.json",
        "bot-agent-summary.json",
        "actual non-Session-0 Windows desktop",
        "physical USB or Bluetooth enumeration",
        "human game-feel",
    ):
        assert token in source, token
