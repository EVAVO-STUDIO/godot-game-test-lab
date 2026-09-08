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
        "authoritySafetyProven": True,
        "staleSocketInboundRejectedProven": True,
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
        "deploymentSourceBound": True,
        "privacySafe": True,
        "reconnectIdentityContinuityProven": True,
        "runtimeSessionRotationProven": True,
    }


def _patch(monkeypatch: pytest.MonkeyPatch, *, sha: str = "a" * 40) -> None:
    authority = _authority()
    runtime = _transport()
    browser = _transport(browser=True)
    godot = _transport(browser=True, godot=True)
    for item in (runtime, browser, godot):
        item["authoritySourceSha"] = sha
    monkeypatch.setattr(ladder, "verify_authority_peer_exchange", lambda _path: authority)
    monkeypatch.setattr(ladder, "verify_runtime_authority_peer_exchange", lambda _path: runtime)
    monkeypatch.setattr(ladder, "verify_browser_runtime_authority_peer_exchange", lambda _path: browser)
    monkeypatch.setattr(ladder, "verify_godot_web_authority_peer_exchange", lambda _path: godot)


def test_accepts_four_aligned_evidence_tiers(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch)
    result = ladder.verify_multiplayer_evidence_ladder(
        Path("authority.json"), Path("runtime.json"), Path("browser.json"), Path("godot.json")
    )
    assert result["proven"] is True
    assert result["tierCount"] == 4
    assert result["highestTier"] == "godot-web-player"
    assert result["godotWebPlayerTransportProven"] is True


def test_rejects_cross_deployment_authority_sha_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch)
    browser = _transport(browser=True)
    browser["authoritySourceSha"] = "b" * 40
    monkeypatch.setattr(ladder, "verify_browser_runtime_authority_peer_exchange", lambda _path: browser)
    with pytest.raises(ladder.MultiplayerEvidenceLadderError, match="authoritySourceSha"):
        ladder.verify_multiplayer_evidence_ladder(
            Path("authority.json"), Path("runtime.json"), Path("browser.json"), Path("godot.json")
        )


def test_rejects_authority_room_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch)
    authority = _authority()
    authority["sessionId"] = "other-room"
    monkeypatch.setattr(ladder, "verify_authority_peer_exchange", lambda _path: authority)
    with pytest.raises(ladder.MultiplayerEvidenceLadderError, match="session does not match"):
        ladder.verify_multiplayer_evidence_ladder(
            Path("authority.json"), Path("runtime.json"), Path("browser.json"), Path("godot.json")
        )


def test_rejects_browser_tier_that_claims_godot_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch)
    browser = _transport(browser=True)
    browser["godotPlayerTransportProven"] = True
    monkeypatch.setattr(ladder, "verify_browser_runtime_authority_peer_exchange", lambda _path: browser)
    with pytest.raises(ladder.MultiplayerEvidenceLadderError, match="non-Godot-player boundary"):
        ladder.verify_multiplayer_evidence_ladder(
            Path("authority.json"), Path("runtime.json"), Path("browser.json"), Path("godot.json")
        )


def test_rejects_missing_current_authority_stale_socket_safety(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch)
    authority = _authority()
    authority["staleSocketInboundRejectedProven"] = False
    monkeypatch.setattr(ladder, "verify_authority_peer_exchange", lambda _path: authority)
    with pytest.raises(ladder.MultiplayerEvidenceLadderError, match="stale-socket safety"):
        ladder.verify_multiplayer_evidence_ladder(
            Path("authority.json"), Path("runtime.json"), Path("browser.json"), Path("godot.json")
        )
