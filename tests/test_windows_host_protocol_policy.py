from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTER = ROOT / "scripts" / "Register-GodotLabMcpWorker.ps1"
PROBE = ROOT / "scripts" / "Test-GodotLabMcpWorker.ps1"
HOST = ROOT / "scripts" / "Test-GodotLabAgentHost.ps1"
INITIALIZE = ROOT / "scripts" / "Initialize-GodotLabAgentHost.ps1"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _assert_precreation_policy(source: str) -> None:
    candidate_index = source.index("$candidateEvidence = [IO.Path]::GetFullPath")
    overlap_index = source.index(
        "Test-PathsOverlap -Left $candidateEvidence",
        candidate_index,
    )
    create_index = source.index("New-Item -ItemType Directory -Force -Path")
    assert candidate_index < overlap_index < create_index
    assert "Assert-NoReparsePointForCandidate -Path $candidateEvidence" in source
    assert "Assert-NoReparsePointForCandidate -Path $candidateEngine" in source
    assert (
        "EngineRoot must remain disjoint from Lab, target, and evidence roots."
        in source
    )


def test_windows_worker_registration_rejects_overlaps_before_creation() -> None:
    source = _source(REGISTER)
    _assert_precreation_policy(source)
    assert 'allowedTargetRoots = @($resolvedRoots)' in source
    assert 'autoProvisionEngines = -not [bool]$EngineOffline' in source


def test_windows_worker_probe_confines_receipts_and_roots() -> None:
    source = _source(PROBE)
    _assert_precreation_policy(source)
    assert "Worker acceptance output must remain beneath EvidenceRoot." in source
    assert "Worker acceptance output already exists:" in source
    output_check = source.index(
        "Worker acceptance output must remain beneath EvidenceRoot."
    )
    output_parent_create = source.index(
        "New-Item -ItemType Directory -Force -Path $parent",
        output_check,
    )
    assert output_check < output_parent_create
    assert '"--expect-no-auto-provision"' in source


def test_agent_host_uses_protocol_identity_and_complete_root_set() -> None:
    source = _source(HOST)
    _assert_precreation_policy(source)
    assert "Test-LoopbackPort" not in source
    assert '"scripts\\Test-GodotLabMcpWorker.ps1"' in source
    assert 'AllowedTargetRoots = @($resolvedRoots)' in source
    assert 'OutputPath = $workerReceipt' in source
    assert 'RequireScheduledTask = $true' in source
    assert '"--no-auto-provision"' in source
    assert '"status", "--porcelain=v1", "--untracked-files=all"' in source


def test_initializer_preserves_offline_policy_in_host_acceptance() -> None:
    source = _source(INITIALIZE)
    assert 'if ($workerOffline) { $acceptanceParameters.EngineOffline = $true }' in source
