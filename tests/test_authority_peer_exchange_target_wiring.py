from __future__ import annotations

from pathlib import Path


def test_authority_target_requires_receipt_v3_and_acceptance_v4() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "scripts" / "Invoke-AuthorityPeerExchangeTarget.ps1").read_text(encoding="utf-8")

    required = (
        "$Verified.receiptSchemaVersion -ne 3",
        "$Verified.staleSocketInboundRejectedProven -ne $true",
        'schemaVersion = "4.0"',
        "staleSocketInboundRejectedProven = $true",
        "$Accepted.acceptanceSchemaVersion -ne 4",
        "$Accepted.receiptSchemaVersion -ne 3",
        "$Accepted.staleSocketInboundRejectedProven -ne $true",
        '$EvidenceGrade = "source-bound-v4"',
        "source-bound v4 contract",
    )
    for marker in required:
        assert marker in source, f"authority target runner lost required v4 marker: {marker}"

    forbidden = (
        "$Verified.receiptSchemaVersion -ne 2",
        "$Accepted.acceptanceSchemaVersion -ne 3",
        "$Accepted.receiptSchemaVersion -ne 2",
        '$EvidenceGrade = "source-bound-v3"',
        "source-bound v3 contract",
    )
    for marker in forbidden:
        assert marker not in source, f"authority target runner regressed to legacy contract: {marker}"
