from __future__ import annotations

import json
from pathlib import Path

import pytest

from godot_game_test_lab import authority_peer_exchange as subject


def _receipt() -> dict[str, object]:
    return {
        "schemaVersion": "1.0",
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
        "truthBoundary": "server authority lifecycle only",
    }


def _write(tmp_path: Path, receipt: dict[str, object]) -> Path:
    path = tmp_path / "authority-peer-exchange.json"
    path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return path


def test_proves_reciprocal_departure_and_reconnect_lifecycle(tmp_path: Path) -> None:
    result = subject.verify_authority_peer_exchange(_write(tmp_path, _receipt()))
    assert result["proven"] is True
    assert result["requiredRoleCount"] == 2
    assert result["privacySafe"] is True
    assert result["stablePeerMapping"] is True
    assert result["survivorRoleId"] == "alpha"
    assert result["receiptBytes"] > 0
    assert result["phases"] == ["single", "reciprocal", "departure", "reconnect"]


def test_missing_reciprocal_observation_fails_closed(tmp_path: Path) -> None:
    receipt = _receipt()
    receipt["phases"][1]["roles"][1]["observedPeerIds"] = []
    with pytest.raises(subject.AuthorityPeerExchangeError, match="exact reciprocal peer set"):
        subject.verify_authority_peer_exchange(_write(tmp_path, receipt))


def test_departure_must_remove_exactly_the_declared_role(tmp_path: Path) -> None:
    receipt = _receipt()
    receipt["phases"][2]["roles"] = receipt["phases"][1]["roles"]
    with pytest.raises(subject.AuthorityPeerExchangeError, match="remove exactly the departed role"):
        subject.verify_authority_peer_exchange(_write(tmp_path, receipt))


def test_departure_cannot_renumber_surviving_peer(tmp_path: Path) -> None:
    receipt = _receipt()
    receipt["phases"][2]["roles"][0]["localPeerId"] = 9
    with pytest.raises(subject.AuthorityPeerExchangeError, match="changed peer id for surviving role"):
        subject.verify_authority_peer_exchange(_write(tmp_path, receipt))


def test_reconnect_must_restore_reciprocal_role_inventory(tmp_path: Path) -> None:
    receipt = _receipt()
    receipt["phases"][3]["roles"] = receipt["phases"][3]["roles"][:1]
    with pytest.raises(subject.AuthorityPeerExchangeError, match="restore the reciprocal role inventory"):
        subject.verify_authority_peer_exchange(_write(tmp_path, receipt))


def test_reconnect_cannot_silently_renumber_peers(tmp_path: Path) -> None:
    receipt = _receipt()
    receipt["phases"][3]["roles"][0]["localPeerId"] = 7
    receipt["phases"][3]["roles"][0]["observedPeerIds"] = [8]
    receipt["phases"][3]["roles"][1]["localPeerId"] = 8
    receipt["phases"][3]["roles"][1]["observedPeerIds"] = [7]
    with pytest.raises(subject.AuthorityPeerExchangeError, match="changed the reciprocal peer mapping"):
        subject.verify_authority_peer_exchange(_write(tmp_path, receipt))


def test_single_role_must_exist_in_reciprocal_phase(tmp_path: Path) -> None:
    receipt = _receipt()
    receipt["phases"][0]["roles"][0]["id"] = "observer"
    with pytest.raises(subject.AuthorityPeerExchangeError, match="single phase role"):
        subject.verify_authority_peer_exchange(_write(tmp_path, receipt))


def test_departed_role_cannot_be_the_single_phase_survivor(tmp_path: Path) -> None:
    receipt = _receipt()
    receipt["departedRoleId"] = "alpha"
    with pytest.raises(subject.AuthorityPeerExchangeError, match="departed role cannot be the single-phase survivor"):
        subject.verify_authority_peer_exchange(_write(tmp_path, receipt))


def test_identity_or_credential_leak_claim_fails_closed(tmp_path: Path) -> None:
    for key in ("rawPlayerIdsTransmitted", "runtimeSessionIdsTransmitted", "credentialsTransmitted"):
        receipt = _receipt()
        receipt["privacy"][key] = True
        with pytest.raises(subject.AuthorityPeerExchangeError, match="identity or credential leakage"):
            subject.verify_authority_peer_exchange(_write(tmp_path, receipt))


def test_privacy_values_must_be_literal_booleans(tmp_path: Path) -> None:
    for invalid in (0, "", None):
        receipt = _receipt()
        receipt["privacy"]["credentialsTransmitted"] = invalid
        with pytest.raises(subject.AuthorityPeerExchangeError, match="privacy values must be booleans"):
            subject.verify_authority_peer_exchange(_write(tmp_path, receipt))


def test_unexpected_fields_are_rejected(tmp_path: Path) -> None:
    receipt = _receipt()
    receipt["rawPlayerIds"] = ["secret"]
    with pytest.raises(subject.AuthorityPeerExchangeError, match="unexpected fields"):
        subject.verify_authority_peer_exchange(_write(tmp_path, receipt))


def test_duplicate_json_keys_are_rejected_by_strict_loader(tmp_path: Path) -> None:
    path = tmp_path / "authority-peer-exchange.json"
    valid = json.dumps(_receipt(), separators=(",", ":"))
    tampered = valid[:-1] + ',"kind":"evavo-authority-peer-exchange-lifecycle"}'
    path.write_text(tampered, encoding="utf-8")
    with pytest.raises(subject.AuthorityPeerExchangeError, match="receipt is unreadable"):
        subject.verify_authority_peer_exchange(path)


def test_oversized_receipt_is_rejected_before_json_parsing(tmp_path: Path) -> None:
    path = tmp_path / "authority-peer-exchange.json"
    path.write_bytes(b"{" + (b" " * (subject._MAX_RECEIPT_BYTES + 1)) + b"}")
    with pytest.raises(subject.AuthorityPeerExchangeError, match="receipt size is invalid"):
        subject.verify_authority_peer_exchange(path)


def test_utf16_receipt_is_rejected_instead_of_silently_transcoded(tmp_path: Path) -> None:
    path = tmp_path / "authority-peer-exchange.json"
    path.write_text(json.dumps(_receipt()), encoding="utf-16")
    with pytest.raises(subject.AuthorityPeerExchangeError, match="receipt encoding is invalid"):
        subject.verify_authority_peer_exchange(path)
