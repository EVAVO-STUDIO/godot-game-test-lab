from __future__ import annotations

from pathlib import Path

import pytest

import godot_game_test_lab.multiplayer_evidence_ladder as ladder


def _authority() -> dict[str, object]:
    return {
        "proven": True,
        "gameId": "galactic-cycle-online",
        "protocol": "galactic-cycle.v1",
        "sessionId": "persistent-galaxy",
        "requiredRoleCount": 2,
        "departedRoleId": "beta",
        "survivorRoleId": "alpha",
        "privacySafe": True,
        "receiptSchemaVersion": 3,
        "authoritySafetyProven": True,
        "staleSocketInboundRejectedProven": True,
    }


def _acceptance(*, target_sha: str = "a" * 40, schema: int = 4) -> dict[str, object]:
    return {
        "proven": True,
        "acceptanceSchemaVersion": schema,
        "receiptSchemaVersion": 3,
        "sourceBound": True,
        "authoritySafetyProven": True,
        "staleSocketInboundRejectedProven": True,
        "gameId": "galactic-cycle-online",
        "protocol": "galactic-cycle.v1",
        "requiredRoleCount": 2,
        "targetSha": target_sha,
        "testLabSha": "c" * 40,
        "receiptSha256": "d" * 64,
    }


def _transport(*, browser: bool = False, godot: bool = False) -> dict[str, object]:
    return {
        "proven": True,
        "gameId": "galactic-cycle-online",
        "protocol": "galactic-cycle.v1",
        "roomId": "persistent-galaxy",
        "releaseId": "0.1.0-dev",
        "releaseChannel": "production",
        "runtimeOrigin": "https://runtime.example.test",
        "authorityOrigin": "wss://authority.example.test",
        "authoritySourceSha": "a" * 40,
        "requiredRoleCount": 2,
        "departedRoleId": "beta",
        "survivorRoleId": "alpha",
        "transportProven": True,
        "browserTransportProven": browser,
        "godotPlayerTransportProven": godot if browser and not godot else False,
        "godotWebPlayerTransportProven": godot,
        "runtimeHandoffConsumedByGodotProven": godot,
        "descriptorSignatureCryptographicallyVerifiedByThisProbe": godot,
        "deploymentSourceBound": True,
        "privacySafe": True,
        "reconnectIdentityContinuityProven": True,
        "runtimeSessionRotationProven": True,
    }


def _acceptance_path(tmp_path: Path) -> Path:
    path = tmp_path / "acceptance.json"
    path.write_text("{}\n", encoding="utf-8")
    return path


def _patch(
    monkeypatch: pytest.MonkeyPatch,
    *,
    sha: str = "a" * 40,
    target_sha: str | None = None,
    acceptance_schema: int = 4,
) -> None:
    authority = _authority()
    acceptance = _acceptance(
        target_sha=target_sha if target_sha is not None else sha,
        schema=acceptance_schema,
    )
    runtime = _transport()
    browser = _transport(browser=True)
    godot = _transport(browser=True, godot=True)
    for item in (runtime, browser, godot):
        item["authoritySourceSha"] = sha
    monkeypatch.setattr(ladder, "verify_authority_peer_exchange_acceptance", lambda _path: acceptance)
    monkeypatch.setattr(ladder, "verify_authority_peer_exchange", lambda _path: authority)
    monkeypatch.setattr(ladder, "verify_runtime_authority_peer_exchange", lambda _path: runtime)
    monkeypatch.setattr(ladder, "verify_browser_runtime_authority_peer_exchange", lambda _path: browser)
    monkeypatch.setattr(ladder, "verify_godot_web_authority_peer_exchange", lambda _path: godot)


def test_accepts_four_aligned_source_bound_evidence_tiers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch(monkeypatch)
    result = ladder.verify_multiplayer_evidence_ladder(
        _acceptance_path(tmp_path),
        Path("runtime.json"),
        Path("browser.json"),
        Path("godot.json"),
    )
    assert result["proven"] is True
    assert result["schemaVersion"] == 3
    assert result["tierCount"] == 4
    assert result["highestTier"] == "source-bound-godot-web-player-cryptographic-release"
    assert result["authoritySourceBound"] is True
    assert result["authorityAcceptanceSchemaVersion"] == 4
    assert result["authorityReceiptSchemaVersion"] == 3
    assert result["authoritySourceSha"] == "a" * 40
    assert result["godotWebPlayerTransportProven"] is True
    assert result["descriptorSignatureCryptographicallyVerified"] is True


def test_rejects_authority_acceptance_target_sha_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch(monkeypatch, sha="a" * 40, target_sha="b" * 40)
    with pytest.raises(ladder.MultiplayerEvidenceLadderError, match="target SHA"):
        ladder.verify_multiplayer_evidence_ladder(
            _acceptance_path(tmp_path),
            Path("runtime.json"),
            Path("browser.json"),
            Path("godot.json"),
        )


def test_rejects_cross_deployment_transport_authority_sha_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch(monkeypatch)
    browser = _transport(browser=True)
    browser["authoritySourceSha"] = "b" * 40
    monkeypatch.setattr(ladder, "verify_browser_runtime_authority_peer_exchange", lambda _path: browser)
    with pytest.raises(ladder.MultiplayerEvidenceLadderError, match="authoritySourceSha"):
        ladder.verify_multiplayer_evidence_ladder(
            _acceptance_path(tmp_path),
            Path("runtime.json"),
            Path("browser.json"),
            Path("godot.json"),
        )


def test_rejects_legacy_authority_acceptance_schema(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch(monkeypatch, acceptance_schema=3)
    with pytest.raises(ladder.MultiplayerEvidenceLadderError, match="acceptance schema v4"):
        ladder.verify_multiplayer_evidence_ladder(
            _acceptance_path(tmp_path),
            Path("runtime.json"),
            Path("browser.json"),
            Path("godot.json"),
        )


def test_rejects_authority_room_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch(monkeypatch)
    authority = _authority()
    authority["sessionId"] = "other-room"
    monkeypatch.setattr(ladder, "verify_authority_peer_exchange", lambda _path: authority)
    with pytest.raises(ladder.MultiplayerEvidenceLadderError, match="session does not match"):
        ladder.verify_multiplayer_evidence_ladder(
            _acceptance_path(tmp_path),
            Path("runtime.json"),
            Path("browser.json"),
            Path("godot.json"),
        )


def test_rejects_browser_tier_that_claims_godot_transport(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch(monkeypatch)
    browser = _transport(browser=True)
    browser["godotPlayerTransportProven"] = True
    monkeypatch.setattr(ladder, "verify_browser_runtime_authority_peer_exchange", lambda _path: browser)
    with pytest.raises(ladder.MultiplayerEvidenceLadderError, match="non-Godot-player boundary"):
        ladder.verify_multiplayer_evidence_ladder(
            _acceptance_path(tmp_path),
            Path("runtime.json"),
            Path("browser.json"),
            Path("godot.json"),
        )


def test_rejects_missing_current_authority_stale_socket_safety(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch(monkeypatch)
    acceptance = _acceptance()
    acceptance["staleSocketInboundRejectedProven"] = False
    monkeypatch.setattr(ladder, "verify_authority_peer_exchange_acceptance", lambda _path: acceptance)
    with pytest.raises(ladder.MultiplayerEvidenceLadderError, match="stale-socket safety"):
        ladder.verify_multiplayer_evidence_ladder(
            _acceptance_path(tmp_path),
            Path("runtime.json"),
            Path("browser.json"),
            Path("godot.json"),
        )


def test_rejects_legacy_envelope_only_godot_web_top_tier(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch(monkeypatch)
    godot = _transport(browser=True, godot=True)
    godot["descriptorSignatureCryptographicallyVerifiedByThisProbe"] = False
    monkeypatch.setattr(ladder, "verify_godot_web_authority_peer_exchange", lambda _path: godot)
    with pytest.raises(ladder.MultiplayerEvidenceLadderError, match="cryptographic descriptor verification"):
        ladder.verify_multiplayer_evidence_ladder(
            _acceptance_path(tmp_path),
            Path("runtime.json"),
            Path("browser.json"),
            Path("godot.json"),
        )
