from __future__ import annotations

from pathlib import Path


def test_authority_peer_exchange_target_runner_stays_fail_closed() -> None:
    root = Path(__file__).resolve().parents[1]
    runner = root / "scripts" / "Invoke-AuthorityPeerExchangeTarget.ps1"
    source = runner.read_text(encoding="utf-8")

    required_markers = (
        'branch -ne "main"',
        "-AllowDirty",
        "GetRelativePath",
        "EmitterRelativePath must remain inside the target repository",
        "ArtifactRelativePath must remain inside the target repository",
        "must not be a symbolic link or junction",
        "System.Collections.IDictionary",
        "Assert-RepoStateUnchanged",
        "Node.js 20+ is required",
        "EVAVO_AUTHORITY_PEER_EXCHANGE_RECEIPT=PASS",
        "EVAVO_AUTHORITY_PEER_EXCHANGE=PASS roles=",
        "receiptSchemaVersion -ne 2",
        "authoritySafetyProven -ne $true",
        "authorityLifecycleProven -ne $true",
        "departureRevocationProven -ne $true",
        "reconnectPeerSemanticsProven -ne $true",
        "transportProven -ne $false",
        "browserTransportProven -ne $false",
        "ExpectedGameId",
        'schemaVersion = "3.0"',
        'kind = "evavo-authority-peer-exchange-acceptance"',
        "godot_game_test_lab.authority_peer_exchange_acceptance",
        "EVAVO_AUTHORITY_PEER_EXCHANGE_ACCEPTANCE_VERIFY=PASS",
        'sourceUnchanged = $true',
        'sourceBound -ne $true',
        'EvidenceGrade = "source-bound-v3"',
        "EVAVO_AUTHORITY_PEER_EXCHANGE_TARGET=PASS",
    )
    for marker in required_markers:
        assert marker in source, f"authority target runner lost fail-closed marker: {marker}"


def test_authority_peer_exchange_target_runner_does_not_promote_transport_proof() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "scripts" / "Invoke-AuthorityPeerExchangeTarget.ps1").read_text(encoding="utf-8")

    assert "browserTransportProven = $false" in source
    assert "transportProven = $false" in source
    assert "browserTransportProven = $true" not in source
    assert "transportProven = $true" not in source


def test_dirty_authority_peer_exchange_runs_cannot_issue_source_bound_acceptance() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "scripts" / "Invoke-AuthorityPeerExchangeTarget.ps1").read_text(encoding="utf-8")

    assert "if (-not $AllowDirty)" in source
    assert 'kind = "evavo-authority-peer-exchange-diagnostic"' in source
    assert 'sourceBound = $false' in source
    assert 'EvidenceGrade = "diagnostic"' in source
    assert 'EvidenceGrade = "source-bound-v3"' in source


def test_authority_peer_exchange_runner_rechecks_source_after_acceptance() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "scripts" / "Invoke-AuthorityPeerExchangeTarget.ps1").read_text(encoding="utf-8")

    assert source.count("Assert-RepoStateUnchanged -Path $TargetRepoRoot") >= 2
    assert source.count("Assert-RepoStateUnchanged -Path $TestLabRoot") >= 2
    assert "working-tree status changed during authority peer-exchange verification" in source
