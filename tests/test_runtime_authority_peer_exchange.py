from __future__ import annotations

import json
from pathlib import Path

import pytest

from godot_game_test_lab import runtime_authority_peer_exchange as subject


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
        "kind": "evavo-runtime-authority-peer-exchange-transport",
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
        "browserTransportProven": False,
        "privacy": {
            "rawPlayerIdsRetained": False,
            "runtimeSessionIdsRetained": False,
            "ticketsRetained": False,
            "installationIdsRetained": False,
        },
        "truthBoundary": "This proves WebSocket transport, but does not prove that a browser-hosted Godot player traversed the path.",
        "runtimeOrigin": "https://runtime.example.test",
        "authorityOrigin": "wss://authority.example.test",
        "releaseId": "0.1.0-dev",
        "releaseChannel": "development",
        "runtimeSessionIssuerProven": True,
        "boundTicketAdmissionProven": True,
        "reconnectIdentityContinuityProven": True,
        "runtimeSessionRotationProven": True,
        "authorityCapabilities": [
            "authoritative-room-presence",
            "stale-socket-send-rejection",
        ],
    }


def _write(tmp_path: Path, receipt: dict[str, object]) -> Path:
    path = tmp_path / "runtime-authority-peer-exchange.json"
    path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return path


def test_verifies_runtime_to_authority_websocket_lifecycle_without_claiming_browser(tmp_path: Path) -> None:
    result = subject.verify_runtime_authority_peer_exchange(_write(tmp_path, _receipt()))
    assert result["proven"] is True
    assert result["transportProven"] is True
    assert result["browserTransportProven"] is False
    assert result["runtimeSessionIssuerProven"] is True
    assert result["boundTicketAdmissionProven"] is True
    assert result["reconnectIdentityContinuityProven"] is True
    assert result["runtimeSessionRotationProven"] is True
    assert result["completeRoomCoverageProven"] is True
    assert result["privacySafe"] is True
    assert result["requiredRoleCount"] == 2
    assert result["departedRoleId"] == "beta"


def test_partial_room_evidence_fails_closed(tmp_path: Path) -> None:
    receipt = _receipt()
    receipt["phases"][1]["roles"] = [
        _role("alpha", 1, [2, 3], 3),
        _role("beta", 2, [1, 3], 3),
    ]
    with pytest.raises(subject.RuntimeAuthorityPeerExchangeError, match="complete connected room"):
        subject.verify_runtime_authority_peer_exchange(_write(tmp_path, receipt))


def test_reconnect_peer_mapping_must_remain_stable(tmp_path: Path) -> None:
    receipt = _receipt()
    receipt["phases"][3]["roles"] = [
        _role("alpha", 2, [1], 2),
        _role("beta", 1, [2], 2),
    ]
    with pytest.raises(subject.RuntimeAuthorityPeerExchangeError, match="stable ephemeral peer mapping"):
        subject.verify_runtime_authority_peer_exchange(_write(tmp_path, receipt))


def test_browser_transport_claim_cannot_be_promoted_by_receipt(tmp_path: Path) -> None:
    receipt = _receipt()
    receipt["browserTransportProven"] = True
    with pytest.raises(subject.RuntimeAuthorityPeerExchangeError, match="browserTransportProven must be false"):
        subject.verify_runtime_authority_peer_exchange(_write(tmp_path, receipt))


def test_identity_or_credential_retention_claim_fails_closed(tmp_path: Path) -> None:
    for key in (
        "rawPlayerIdsRetained",
        "runtimeSessionIdsRetained",
        "ticketsRetained",
        "installationIdsRetained",
    ):
        receipt = _receipt()
        receipt["privacy"][key] = True
        with pytest.raises(subject.RuntimeAuthorityPeerExchangeError, match=f"privacy.{key} must be false"):
            subject.verify_runtime_authority_peer_exchange(_write(tmp_path, receipt))


def test_insecure_non_loopback_origins_are_rejected(tmp_path: Path) -> None:
    receipt = _receipt()
    receipt["runtimeOrigin"] = "http://runtime.example.test"
    with pytest.raises(subject.RuntimeAuthorityPeerExchangeError, match="must use https"):
        subject.verify_runtime_authority_peer_exchange(_write(tmp_path, receipt))

    receipt = _receipt()
    receipt["authorityOrigin"] = "ws://authority.example.test"
    with pytest.raises(subject.RuntimeAuthorityPeerExchangeError, match="must use wss"):
        subject.verify_runtime_authority_peer_exchange(_write(tmp_path, receipt))


def test_required_authority_capabilities_cannot_be_forged_or_omitted(tmp_path: Path) -> None:
    receipt = _receipt()
    receipt["authorityCapabilities"] = ["authoritative-room-presence", "other"]
    with pytest.raises(subject.RuntimeAuthorityPeerExchangeError, match="required capabilities"):
        subject.verify_runtime_authority_peer_exchange(_write(tmp_path, receipt))


def test_truth_boundary_must_keep_browser_distinction(tmp_path: Path) -> None:
    receipt = _receipt()
    receipt["truthBoundary"] = "All production multiplayer is proven."
    with pytest.raises(subject.RuntimeAuthorityPeerExchangeError, match="browser distinction"):
        subject.verify_runtime_authority_peer_exchange(_write(tmp_path, receipt))


def test_unexpected_fields_and_duplicate_json_keys_are_rejected(tmp_path: Path) -> None:
    receipt = _receipt()
    receipt["ticket"] = "secret"
    with pytest.raises(subject.RuntimeAuthorityPeerExchangeError, match="unexpected fields"):
        subject.verify_runtime_authority_peer_exchange(_write(tmp_path, receipt))

    path = tmp_path / "duplicate.json"
    valid = json.dumps(_receipt(), separators=(",", ":"))
    path.write_text(valid[:-1] + ',"transportProven":true}', encoding="utf-8")
    with pytest.raises(subject.RuntimeAuthorityPeerExchangeError, match="encoding is invalid"):
        subject.verify_runtime_authority_peer_exchange(path)
