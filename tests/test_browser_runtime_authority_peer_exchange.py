from __future__ import annotations

import json
from pathlib import Path

import pytest

from godot_game_test_lab import browser_runtime_authority_peer_exchange as subject


def _role(role_id: str, peer_id: int, observed: list[int], connected: int) -> dict[str, object]:
    return {
        "id": role_id,
        "sessionId": "persistent-galaxy",
        "localPeerId": peer_id,
        "observedPeerIds": observed,
        "connectedCount": connected,
    }


def _receipt() -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "kind": "evavo-browser-runtime-authority-peer-exchange-transport",
        "gameId": "galactic-cycle-online",
        "protocol": "galactic-cycle.v1",
        "roomId": "persistent-galaxy",
        "phases": [
            {"id": "single", "roles": [_role("alpha", 1, [], 1)]},
            {
                "id": "reciprocal",
                "roles": [
                    _role("alpha", 1, [2], 2),
                    _role("beta", 2, [1], 2),
                ],
            },
            {"id": "departure", "roles": [_role("alpha", 1, [], 1)]},
            {
                "id": "reconnect",
                "roles": [
                    _role("alpha", 1, [2], 2),
                    _role("beta", 2, [1], 2),
                ],
            },
        ],
        "transportProven": True,
        "browserTransportProven": True,
        "privacy": {
            "rawPlayerIdsRetained": False,
            "runtimeSessionIdsRetained": False,
            "ticketsRetained": False,
            "installationIdsRetained": False,
        },
        "truthBoundary": (
            "This proves Chromium browser transport, but does not prove that a Godot web export "
            "executed gameplay correctly or that the game is release-ready."
        ),
        "runtimeOrigin": "https://runtime.example.test",
        "authorityOrigin": "wss://authority.example.test",
        "authoritySourceSha": "a" * 40,
        "releaseId": "0.1.0-dev",
        "releaseChannel": "development",
        "runtimeSessionIssuerProven": True,
        "boundTicketAdmissionProven": True,
        "reconnectIdentityContinuityProven": True,
        "runtimeSessionRotationProven": True,
        "authorityCapabilities": [
            "authoritative-room-presence",
            "stale-socket-send-rejection",
            "source-bound-deployment",
        ],
        "browserEngine": "chromium",
        "browserVersion": "140.0.0.0",
        "browserParticipantContextCount": 2,
        "browserIsolationContextCount": 3,
        "browserNativeFetchProven": True,
        "browserNativeWebSocketProven": True,
        "browserHostileOriginRejectionProven": True,
    }


def _write(tmp_path: Path, receipt: dict[str, object]) -> Path:
    path = tmp_path / "browser-runtime-authority-peer-exchange.json"
    path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return path


def test_verifies_chromium_browser_runtime_authority_lifecycle(tmp_path: Path) -> None:
    result = subject.verify_browser_runtime_authority_peer_exchange(_write(tmp_path, _receipt()))
    assert result["proven"] is True
    assert result["transportProven"] is True
    assert result["browserTransportProven"] is True
    assert result["godotPlayerTransportProven"] is False
    assert result["browserNativeFetchProven"] is True
    assert result["browserNativeWebSocketProven"] is True
    assert result["browserOpaqueHostileOriginRejectionProven"] is True
    assert result["deploymentSourceBound"] is True
    assert result["privacySafe"] is True
    assert result["browserEngine"] == "chromium"
    assert result["browserParticipantContextCount"] == 2
    assert result["browserIsolationContextCount"] == 3
    assert result["requiredRoleCount"] == 2
    assert result["departedRoleId"] == "beta"


def test_browser_proof_requires_native_fetch_websocket_and_origin_rejection(tmp_path: Path) -> None:
    for field in (
        "browserNativeFetchProven",
        "browserNativeWebSocketProven",
        "browserHostileOriginRejectionProven",
    ):
        receipt = _receipt()
        receipt[field] = False
        with pytest.raises(subject.BrowserRuntimeAuthorityPeerExchangeError, match=f"{field} must be true"):
            subject.verify_browser_runtime_authority_peer_exchange(_write(tmp_path, receipt))


def test_browser_transport_cannot_be_downgraded_or_use_another_engine(tmp_path: Path) -> None:
    receipt = _receipt()
    receipt["browserTransportProven"] = False
    with pytest.raises(subject.BrowserRuntimeAuthorityPeerExchangeError, match="browserTransportProven must be true"):
        subject.verify_browser_runtime_authority_peer_exchange(_write(tmp_path, receipt))

    receipt = _receipt()
    receipt["browserEngine"] = "webkit"
    with pytest.raises(subject.BrowserRuntimeAuthorityPeerExchangeError, match="engine must be chromium"):
        subject.verify_browser_runtime_authority_peer_exchange(_write(tmp_path, receipt))


def test_browser_context_inventory_must_match_the_two_role_probe(tmp_path: Path) -> None:
    receipt = _receipt()
    receipt["browserParticipantContextCount"] = 3
    with pytest.raises(subject.BrowserRuntimeAuthorityPeerExchangeError, match="browserParticipantContextCount must be 2"):
        subject.verify_browser_runtime_authority_peer_exchange(_write(tmp_path, receipt))

    receipt = _receipt()
    receipt["browserIsolationContextCount"] = 2
    with pytest.raises(subject.BrowserRuntimeAuthorityPeerExchangeError, match="browserIsolationContextCount must be 3"):
        subject.verify_browser_runtime_authority_peer_exchange(_write(tmp_path, receipt))


def test_browser_receipt_still_requires_source_binding_privacy_and_complete_room(tmp_path: Path) -> None:
    receipt = _receipt()
    receipt["authoritySourceSha"] = "not-a-sha"
    with pytest.raises(subject.BrowserRuntimeAuthorityPeerExchangeError, match="authority source SHA"):
        subject.verify_browser_runtime_authority_peer_exchange(_write(tmp_path, receipt))

    receipt = _receipt()
    receipt["privacy"]["ticketsRetained"] = True
    with pytest.raises(subject.BrowserRuntimeAuthorityPeerExchangeError, match="privacy.ticketsRetained must be false"):
        subject.verify_browser_runtime_authority_peer_exchange(_write(tmp_path, receipt))

    receipt = _receipt()
    receipt["phases"][1]["roles"] = [_role("alpha", 1, [2], 2)]
    with pytest.raises(subject.BrowserRuntimeAuthorityPeerExchangeError, match="exactly two browser participant roles"):
        subject.verify_browser_runtime_authority_peer_exchange(_write(tmp_path, receipt))


def test_browser_truth_boundary_cannot_escalate_to_godot_game_or_release_proof(tmp_path: Path) -> None:
    receipt = _receipt()
    receipt["truthBoundary"] = "The production Godot game is fully multiplayer release-ready."
    with pytest.raises(subject.BrowserRuntimeAuthorityPeerExchangeError, match="Godot gameplay and release distinction"):
        subject.verify_browser_runtime_authority_peer_exchange(_write(tmp_path, receipt))


def test_unexpected_browser_receipt_fields_fail_closed(tmp_path: Path) -> None:
    receipt = _receipt()
    receipt["ticket"] = "secret"
    with pytest.raises(subject.BrowserRuntimeAuthorityPeerExchangeError, match="unexpected fields"):
        subject.verify_browser_runtime_authority_peer_exchange(_write(tmp_path, receipt))
