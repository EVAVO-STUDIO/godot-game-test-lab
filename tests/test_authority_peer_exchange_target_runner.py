from __future__ import annotations

from pathlib import Path


def test_authority_peer_exchange_target_runner_stays_fail_closed() -> None:
    root = Path(__file__).resolve().parents[1]
    runner = root / "scripts" / "Invoke-AuthorityPeerExchangeTarget.ps1"
    source = runner.read_text(encoding="utf-8")

    required_markers = (
        'branch -ne "main"',
        "-AllowDirty",
        "EmitterRelativePath must remain inside the target repository",
        "ArtifactRelativePath must remain inside the target repository",
        "Node.js 20+ is required",
        "EVAVO_AUTHORITY_PEER_EXCHANGE_RECEIPT=PASS",
        "EVAVO_AUTHORITY_PEER_EXCHANGE=PASS roles=",
        "receiptSchemaVersion -ne 2",
        "authoritySafetyProven -ne $true",
        "departureRevocationProven -ne $true",
        "reconnectPeerSemanticsProven -ne $true",
        "transportProven -ne $false",
        "browserTransportProven -ne $false",
        "ExpectedGameId",
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
