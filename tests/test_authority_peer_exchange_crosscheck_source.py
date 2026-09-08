from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "src" / "godot_game_test_lab" / "authority_peer_exchange_crosscheck.py"
RUNNER = ROOT / "scripts" / "Invoke-AuthorityPeerExchangeCrosscheck.ps1"
DOC = ROOT / "docs" / "AUTHORITY_PEER_EXCHANGE_CROSSCHECK.md"


def test_authority_peer_crosscheck_surface_is_present_and_fail_closed() -> None:
    module = MODULE.read_text(encoding="utf-8")
    runner = RUNNER.read_text(encoding="utf-8")
    doc = DOC.read_text(encoding="utf-8")

    for token in (
        "verify_authority_peer_exchange",
        "verify_peer_exchange",
        "authoritySafetyProven",
        "dynamicCaptureRoleCount",
        "semanticViewsAgree",
        "local peer id disagrees",
        "observed peer set disagrees",
        "EVAVO_AUTHORITY_PEER_EXCHANGE_CROSSCHECK=PASS",
    ):
        assert token in module

    for token in (
        "ExpectedTargetSha",
        "ExpectedLabSha",
        "emit_test_lab_peer_exchange_bundle.mjs",
        "Target repository must be clean",
        "godot-game-test-lab must be clean",
        "Assert-Unchanged",
        "Get-FileHash",
        "EVAVO_AUTHORITY_PEER_EXCHANGE_CROSSCHECK_ACCEPTANCE=PASS",
    ):
        assert token in runner

    for token in (
        "metadata_capture",
        "authority-peer-exchange-lifecycle.json",
        "profile.normalized.json",
        "multiplayer-agent-summary.json",
        "two-browser production-path acceptance",
    ):
        assert token in doc
