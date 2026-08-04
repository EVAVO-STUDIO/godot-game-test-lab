from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts" / "Install-GodotLab.ps1"
INITIALIZER = ROOT / "scripts" / "Initialize-GodotLabAgentHost.ps1"


def test_installer_rejects_root_overlap_before_directory_creation() -> None:
    source = INSTALLER.read_text(encoding="utf-8")

    candidate = source.index(
        "$candidateEngine = [IO.Path]::GetFullPath($EngineRoot)"
    )
    evidence_overlap = source.index(
        "Test-PathsOverlap -Left $candidateEvidence -Right $resolvedLab",
        candidate,
    )
    engine_overlap = source.index(
        "Test-PathsOverlap -Left $candidateEngine -Right $protected",
        evidence_overlap,
    )
    create = source.index(
        "New-Item -ItemType Directory -Force -Path "
        "$candidateEngine, $candidateEvidence",
        engine_overlap,
    )

    assert candidate < evidence_overlap < engine_overlap < create
    assert "Assert-NoReparsePointForCandidate -Path $candidateEngine" in source
    assert "Assert-NoReparsePointForCandidate -Path $candidateEvidence" in source
    assert "EvidenceRoot must remain disjoint from every allowed target root." in source
    assert (
        "EngineRoot must remain disjoint from Lab, target, and evidence roots."
        in source
    )


def test_installer_preserves_all_roots_and_offline_engine_policy() -> None:
    source = INSTALLER.read_text(encoding="utf-8")

    for token in (
        "[string[]]$AdditionalTargetRoots = @()",
        "foreach ($root in @($TargetRoot) + @($AdditionalTargetRoots))",
        "$allowedRootValue = @($resolvedRoots) -join [IO.Path]::PathSeparator",
        "EVAVO_GODOT_LAB_ALLOWED_ROOTS = $allowedRootValue",
        '"managed-engine-estate-{0:D2}.json"',
        "foreach ($root in $resolvedRoots)",
        '$mcpArguments += @("--allowed-root", $root)',
        "AllowedTargetRoots = @($resolvedRoots)",
        "$mcpConfigParameters.NoAutoProvision = $true",
        "allowedTargetRoots = @($resolvedRoots)",
        "estateReports = @($estateReports)",
        "engineOffline = [bool]$offlineEnginePolicy",
    ):
        assert token in source, token

    assert source.count('elseif ($EngineOffline) {') == 2
    assert source.count('$engineArgs += "--offline"') == 1
    assert source.count('$prepareArgs += "--offline"') == 1


def test_initializer_delegates_complete_roots_and_offline_policy() -> None:
    source = INITIALIZER.read_text(encoding="utf-8")

    offline = source.index(
        "$workerOffline = $EngineOffline -or [bool]$OfflineSourceDir"
    )
    install = source.index("$installParameters = @{", offline)
    invoke = source.index("& $installer @installParameters", install)

    assert offline < install < invoke
    assert (
        "AdditionalTargetRoots = @($allTargetRoots | Select-Object -Skip 1)"
        in source
    )
    assert "if ($workerOffline) { $installParameters.EngineOffline = $true }" in source
    assert source.count("AllowedTargetRoots = @($allTargetRoots)") == 2
