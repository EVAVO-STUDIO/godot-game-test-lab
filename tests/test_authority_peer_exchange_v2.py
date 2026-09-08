from __future__ import annotations

import json
from pathlib import Path

import pytest

from godot_game_test_lab import authority_peer_exchange as subject


def _base_receipt(schema: str = "2.0") -> dict[str, object]:
    receipt: dict[str, object] = {
        "schemaVersion": schema,
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
        "truthBoundary": "server authority lifecycle only",
    }
    if schema == "2.0":
        receipt["authoritySafety"] = {
            "supersededSocketRetired": True,
            "staleSocketSendRejected": True,
        }
    return receipt


def _write(tmp_path: Path, receipt: dict[str, object]) -> Path:
    path = tmp_path / "authority-peer-exchange.json"
    path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return path


def test_v2_binds_stale_socket_authority_safety(tmp_path: Path) -> None:
    result = subject.verify_authority_peer_exchange(_write(tmp_path, _base_receipt()))
    assert result["proven"] is True
    assert result["receiptSchemaVersion"] == 2
    assert result["authoritySafetyProven"] is True
    assert result["privacySafe"] is True


def test_v1_remains_valid_but_does_not_claim_new_authority_safety(tmp_path: Path) -> None:
    result = subject.verify_authority_peer_exchange(_write(tmp_path, _base_receipt("1.0")))
    assert result["proven"] is True
    assert result["receiptSchemaVersion"] == 1
    assert result["authoritySafetyProven"] is False


@pytest.mark.parametrize("key", ["supersededSocketRetired", "staleSocketSendRejected"])
def test_v2_false_safety_claim_fails_closed(tmp_path: Path, key: str) -> None:
    receipt = _base_receipt()
    receipt["authoritySafety"][key] = False
    with pytest.raises(subject.AuthorityPeerExchangeError, match="does not prove stale-socket authority retirement"):
        subject.verify_authority_peer_exchange(_write(tmp_path, receipt))


def test_v2_safety_values_must_be_literal_booleans(tmp_path: Path) -> None:
    receipt = _base_receipt()
    receipt["authoritySafety"]["staleSocketSendRejected"] = 1
    with pytest.raises(subject.AuthorityPeerExchangeError, match="safety values must be booleans"):
        subject.verify_authority_peer_exchange(_write(tmp_path, receipt))


def test_v1_cannot_smuggle_v2_authority_safety_fields(tmp_path: Path) -> None:
    receipt = _base_receipt("1.0")
    receipt["authoritySafety"] = {
        "supersededSocketRetired": True,
        "staleSocketSendRejected": True,
    }
    with pytest.raises(subject.AuthorityPeerExchangeError, match="unexpected fields"):
        subject.verify_authority_peer_exchange(_write(tmp_path, receipt))


def test_v2_rejects_missing_or_extra_safety_fields(tmp_path: Path) -> None:
    missing = _base_receipt()
    del missing["authoritySafety"]["staleSocketSendRejected"]
    with pytest.raises(subject.AuthorityPeerExchangeError, match="safety statement is invalid"):
        subject.verify_authority_peer_exchange(_write(tmp_path, missing))

    extra = _base_receipt()
    extra["authoritySafety"]["rawPlayerIdsVisible"] = False
    with pytest.raises(subject.AuthorityPeerExchangeError, match="safety statement is invalid"):
        subject.verify_authority_peer_exchange(_write(tmp_path, extra))
