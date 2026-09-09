from __future__ import annotations

from pathlib import Path


def test_top_multiplayer_ladder_requires_source_bound_authority_acceptance() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "src" / "godot_game_test_lab" / "multiplayer_evidence_ladder.py").read_text(
        encoding="utf-8"
    )
    docs = (root / "docs" / "MULTIPLAYER_EVIDENCE_LADDER.md").read_text(encoding="utf-8")

    required_source = (
        "verify_authority_peer_exchange_acceptance",
        'accepted.get("acceptanceSchemaVersion") != 4',
        'accepted.get("receiptSchemaVersion") != 3',
        'accepted.get("sourceBound") is not True',
        'authority.get("targetSha") != authority_source_sha',
        '"schemaVersion": 3',
        '"highestTier": "source-bound-godot-web-player-cryptographic-release"',
        'parser.add_argument("authority_acceptance_manifest"',
    )
    for marker in required_source:
        assert marker in source, f"multiplayer top tier lost source-binding marker: {marker}"

    forbidden_source = (
        'parser.add_argument("authority_receipt"',
        '"highestTier": "godot-web-player-cryptographic-release"',
    )
    for marker in forbidden_source:
        assert marker not in source, f"multiplayer top tier regressed to legacy authority input: {marker}"

    required_docs = (
        "authority-run/acceptance.json",
        "acceptance schema v4",
        "clean authority target Git SHA",
        "source-bound-godot-web-player-cryptographic-release",
        "schemaVersion=3",
    )
    for marker in required_docs:
        assert marker in docs, f"multiplayer evidence docs lost source-binding marker: {marker}"
