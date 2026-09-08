from __future__ import annotations

import json
from pathlib import Path

import pytest

from godot_game_test_lab import authority_peer_exchange as subject


def _receipt_v3() -> dict[str, object]:
    return {
        "schemaVersion": "3.0",
        "kind": "evavo-authority-peer-exchange-lifecycle",
        "gameId": "galactic-cycle-online",
        "authority": "GalacticCycleRoom",
        "protocol": "galactic-cycle.v1",
        "sessionId": "persistent-galaxy",
        "departedRoleId": "beta",
        "phases": [
            {
                "id": "single",
                "roles": [{
                    "id": "alpha",
                    "sessionId": "persistent-galaxy",
                    "localPeerId": 1,
                    "observedPeerIds": [],
                }],
            },
            {
                "id": "reciprocal",
                "roles": [
                    {
                        "id": "alpha",
                        "sessionId": "persistent-galaxy",
                        "localPeerId": 1,
                        "observedPeerIds": [2],
                    },
                    {
                        "id": "beta",
                        "sessionId": "persistent-galaxy",
                        "localPeerId": 2,
                        "observedPeerIds": [1],
                    },
                ],
            },
            {
                "id": "departure",
                "roles": [{
                    "id": "alpha",
                    "sessionId": "persistent-galaxy",
                    "localPeerId": 1,
                    "observedPeerIds": [],
                }],
            },
            {
                "id": "reconnect",
                "roles": [
                    {
                        "id": "alpha",
                        "sessionId": "persistent-galaxy",
                        "localPeerId": 1,
                        "observedPeerIds": [2],
                    },
                    {
                        "id": "beta",
                        "sessionId": "persistent-galaxy",
                        "localPeerId": 2,
                        "observedPeerIds": [1],
                    },
                ],
            },
        ],
        "privacy": {
            "rawPlayerIdsTransmitted": False,
            "runtimeSessionIdsTransmitted": False,
            "credentialsTransmitted": False,
        },
        "authoritySafety": {
            "supersededSocketRetired": True,
            "staleSocketSendRejected": True,
            "staleSocketMessageRejected": True,
        },
        "truthBoundary": "server authority lifecycle only",
    }


def _write(tmp_path: Path, receipt: dict[str, object]) -> Path:
    path = tmp_path / "authority-peer-exchange.json"
    path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return path


def test_v3_binds_inbound_and_outbound_stale_socket_rejection(tmp_path: Path) -> None:
    result = subject.verify_authority_peer_exchange(_write(tmp_path, _receipt_v3()))
    assert result["receiptSchemaVersion"] == 3
    assert result["authorityLifecycleProven"] is True
    assert result["authoritySafetyProven"] is True
    assert result["staleSocketInboundRejectedProven"] is True
    assert result["transportProven"] is False
    assert result["browserTransportProven"] is False


def test_v3_requires_all_three_authority_safety_claims(tmp_path: Path) -> None:
    for key in (
        "supersededSocketRetired",
        "staleSocketSendRejected",
        "staleSocketMessageRejected",
    ):
        receipt = _receipt_v3()
        receipt["authoritySafety"][key] = False
        with pytest.raises(
            subject.AuthorityPeerExchangeError,
            match="does not prove stale-socket authority retirement",
        ):
            subject.verify_authority_peer_exchange(_write(tmp_path, receipt))


def test_v3_rejects_v2_shape_missing_inbound_rejection(tmp_path: Path) -> None:
    receipt = _receipt_v3()
    del receipt["authoritySafety"]["staleSocketMessageRejected"]
    with pytest.raises(subject.AuthorityPeerExchangeError, match="safety statement is invalid"):
        subject.verify_authority_peer_exchange(_write(tmp_path, receipt))


def test_v2_compatibility_does_not_claim_inbound_rejection(tmp_path: Path) -> None:
    receipt = _receipt_v3()
    receipt["schemaVersion"] = "2.0"
    del receipt["authoritySafety"]["staleSocketMessageRejected"]
    result = subject.verify_authority_peer_exchange(_write(tmp_path, receipt))
    assert result["receiptSchemaVersion"] == 2
    assert result["authoritySafetyProven"] is True
    assert result["staleSocketInboundRejectedProven"] is False
