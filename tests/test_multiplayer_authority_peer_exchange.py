from __future__ import annotations

import json
from pathlib import Path

import pytest

from godot_game_test_lab import multiplayer_authority_peer_exchange as subject


def _receipt() -> dict[str, object]:
    return {
        "schemaVersion": "2.0",
        "kind": "evavo-authority-peer-exchange-lifecycle",
        "gameId": "galactic-cycle-online",
        "authority": "GalacticCycleRoom",
        "protocol": "galactic-cycle.v1",
        "sessionId": "persistent-galaxy",
        "departedRoleId": "beta",
        "phases": [
            {
                "id": "single",
                "roles": [
                    {
                        "id": "alpha",
                        "sessionId": "persistent-galaxy",
                        "localPeerId": 1,
                        "observedPeerIds": [],
                    }
                ],
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
                "roles": [
                    {
                        "id": "alpha",
                        "sessionId": "persistent-galaxy",
                        "localPeerId": 1,
                        "observedPeerIds": [],
                    }
                ],
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
        "truthBoundary": (
            "Server-authority lifecycle proof only; this does not prove browser traversal."
        ),
    }


def _write(root: Path, value: dict[str, object]) -> Path:
    path = root / subject.SOURCE_RECEIPT_NAME
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return path


def test_accepts_complete_authority_lifecycle_and_returns_reconnect_roles(tmp_path: Path) -> None:
    result = subject.verify_authority_peer_exchange_source(_write(tmp_path, _receipt()))
    assert result["sourceBound"] is True
    assert result["gameId"] == "galactic-cycle-online"
    assert result["requiredRoleCount"] == 2
    assert result["departedRoleId"] == "beta"
    assert result["roles"] == _receipt()["phases"][3]["roles"]


def test_reconnect_must_restore_exact_reciprocal_role_evidence(tmp_path: Path) -> None:
    receipt = _receipt()
    receipt["phases"][3]["roles"][1]["observedPeerIds"] = []
    with pytest.raises(subject.AuthorityPeerExchangeSourceError, match="reconnect"):
        subject.verify_authority_peer_exchange_source(_write(tmp_path, receipt))


def test_departure_must_revoke_departed_peer(tmp_path: Path) -> None:
    receipt = _receipt()
    receipt["phases"][2]["roles"][0]["observedPeerIds"] = [2]
    with pytest.raises(subject.AuthorityPeerExchangeSourceError, match="departure"):
        subject.verify_authority_peer_exchange_source(_write(tmp_path, receipt))


def test_privacy_claims_fail_closed(tmp_path: Path) -> None:
    receipt = _receipt()
    receipt["privacy"]["credentialsTransmitted"] = True
    with pytest.raises(subject.AuthorityPeerExchangeSourceError, match="privacy"):
        subject.verify_authority_peer_exchange_source(_write(tmp_path, receipt))


def test_all_stale_socket_safety_claims_are_required(tmp_path: Path) -> None:
    receipt = _receipt()
    receipt["authoritySafety"].pop("staleSocketMessageRejected")
    with pytest.raises(subject.AuthorityPeerExchangeSourceError, match="safety receipt"):
        subject.verify_authority_peer_exchange_source(_write(tmp_path, receipt))


def test_source_rejects_unexpected_fields_instead_of_normalizing(tmp_path: Path) -> None:
    receipt = _receipt()
    receipt["playerId"] = "p_secret"
    with pytest.raises(subject.AuthorityPeerExchangeSourceError, match="top-level fields"):
        subject.verify_authority_peer_exchange_source(_write(tmp_path, receipt))
