from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_authority_peer_lifecycle_cli_is_exposed() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert (
        'godot-lab-authority-peer-lifecycle = "godot_game_test_lab.authority_peer_lifecycle:main"'
        in pyproject
    )


def test_local_authority_lifecycle_lane_requires_exact_evidence_and_clean_sha_by_default() -> None:
    script = (ROOT / "scripts" / "Verify-AuthorityPeerLifecycle.ps1").read_text(encoding="utf-8")
    required = [
        "git -C $repo rev-parse HEAD",
        "status --porcelain=v1 --untracked-files=all",
        "EVAVO_AUTHORITY_PEER_EXCHANGE_RECEIPT=PASS",
        "godot_game_test_lab.authority_peer_lifecycle",
        "authorityLifecycleProven",
        "transportProven",
        "browserTransportProven",
        "EVAVO_AUTHORITY_PEER_LIFECYCLE=PASS",
    ]
    for marker in required:
        assert marker in script
    assert "-and -not $AllowDirty" in script
    assert "transportProven -ne $false" in script
    assert "browserTransportProven -ne $false" in script


def test_lifecycle_verifier_reuses_portable_peer_semantics() -> None:
    source = (ROOT / "src" / "godot_game_test_lab" / "authority_peer_lifecycle.py").read_text(encoding="utf-8")
    assert "verify_peer_observations" in source
    assert '"authorityLifecycleProven": proven' in source
    assert '"transportProven": False' in source
    assert '"browserTransportProven": False' in source
    assert '"reconnectPeerSemanticsProven"' in source
