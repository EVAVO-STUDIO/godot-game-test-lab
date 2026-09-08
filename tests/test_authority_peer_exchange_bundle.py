from __future__ import annotations

import json
from pathlib import Path

import pytest

from godot_game_test_lab import attended_multiplayer_common as common
from godot_game_test_lab import authority_peer_exchange_bundle as subject


def _source() -> dict[str, object]:
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
                "roles": [
                    {"id": "alpha", "sessionId": "persistent-galaxy", "localPeerId": 1, "observedPeerIds": []}
                ],
            },
            {
                "id": "reciprocal",
                "roles": [
                    {"id": "alpha", "sessionId": "persistent-galaxy", "localPeerId": 1, "observedPeerIds": [2]},
                    {"id": "beta", "sessionId": "persistent-galaxy", "localPeerId": 2, "observedPeerIds": [1]},
                ],
            },
            {
                "id": "departure",
                "roles": [
                    {"id": "alpha", "sessionId": "persistent-galaxy", "localPeerId": 1, "observedPeerIds": []}
                ],
            },
            {
                "id": "reconnect",
                "roles": [
                    {"id": "alpha", "sessionId": "persistent-galaxy", "localPeerId": 1, "observedPeerIds": [2]},
                    {"id": "beta", "sessionId": "persistent-galaxy", "localPeerId": 2, "observedPeerIds": [1]},
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
        "truthBoundary": "authority fixture only",
    }


def _profile() -> dict[str, object]:
    assertions = [
        {"type": "metadata_capture", "path": "/root/PeerExchangeEvidence", "key": "evavo_peer_session_id"},
        {"type": "metadata_capture", "path": "/root/PeerExchangeEvidence", "key": "evavo_local_peer_id"},
        {"type": "metadata_capture", "path": "/root/PeerExchangeEvidence", "key": "evavo_observed_peer_ids"},
    ]
    return {
        "schemaVersion": "1.0",
        "roles": [
            {
                "id": "alpha",
                "personaId": "authority-fixture-alpha",
                "required": True,
                "startDelayMs": 0,
                "journey": {"id": "authority-alpha", "assertions": assertions},
            },
            {
                "id": "beta",
                "personaId": "authority-fixture-beta",
                "required": True,
                "startDelayMs": 0,
                "journey": {"id": "authority-beta", "assertions": assertions},
            },
        ],
        "truthBoundary": "authority fixture only",
    }


def _harness(session: str, local_peer: int, observed: list[int]) -> dict[str, object]:
    return {
        "status": "passed",
        "assertions": [
            {"index": 0, "type": "metadata_capture", "accepted": True, "actual": session},
            {"index": 1, "type": "metadata_capture", "accepted": True, "actual": local_peer},
            {"index": 2, "type": "metadata_capture", "accepted": True, "actual": observed},
        ],
    }


def _write_bundle(tmp_path: Path) -> Path:
    root = tmp_path / "bundle"
    root.mkdir()
    (root / subject.SOURCE_RECEIPT).write_text(json.dumps(_source(), indent=2) + "\n", encoding="utf-8")
    (root / subject.PROFILE).write_text(json.dumps(_profile(), indent=2) + "\n", encoding="utf-8")
    inventory = common.inventory_artifacts(root)
    summary = {
        "schemaVersion": "1.0",
        "status": "passed",
        "peerExchangeEvidenceClass": "authority-fixture",
        "peerExchangeSourceReceipt": subject.SOURCE_RECEIPT,
        "roles": [
            {"id": "alpha", "required": True, "status": "passed", "harness": _harness("persistent-galaxy", 1, [2])},
            {"id": "beta", "required": True, "status": "passed", "harness": _harness("persistent-galaxy", 2, [1])},
        ],
        "artifacts": inventory,
        "truthBoundary": "authority fixture only",
    }
    (root / subject.SUMMARY).write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return root


def _refresh_inventory(root: Path) -> dict[str, object]:
    summary_path = root / subject.SUMMARY
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["artifacts"] = common.inventory_artifacts(root)
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def test_source_bound_authority_bundle_is_proven_but_not_transport_evidence(tmp_path: Path) -> None:
    result = subject.verify_authority_peer_exchange_bundle(artifact_root=_write_bundle(tmp_path))
    assert result["status"] == "passed"
    assert result["evidenceClass"] == "authority-fixture"
    assert result["peerExchangeProven"] is True
    assert result["departureRevocationProven"] is True
    assert result["reconnectRestorationProven"] is True
    assert result["staleSocketRetirementProven"] is True
    assert result["staleSocketInboundRejectedProven"] is True
    assert result["fixtureConvertedToTestLabShape"] is True
    assert result["nativeGodotJourneyObserved"] is False
    assert result["browserJourneyObserved"] is False
    assert result["transportProven"] is False
    assert result["browserTransportProven"] is False
    assert len(result["sourceReceiptSha256"]) == 64


def test_missing_authority_fixture_classification_fails_closed(tmp_path: Path) -> None:
    root = _write_bundle(tmp_path)
    summary_path = root / subject.SUMMARY
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary.pop("peerExchangeEvidenceClass")
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(subject.AuthorityPeerExchangeBundleError, match="authority-fixture evidence class"):
        subject.verify_authority_peer_exchange_bundle(artifact_root=root)


def test_schema_two_source_is_insufficient_for_source_bound_bundle(tmp_path: Path) -> None:
    root = _write_bundle(tmp_path)
    source_path = root / subject.SOURCE_RECEIPT
    source = json.loads(source_path.read_text(encoding="utf-8"))
    source["schemaVersion"] = "2.0"
    source["authoritySafety"].pop("staleSocketMessageRejected")
    source_path.write_text(json.dumps(source, indent=2) + "\n", encoding="utf-8")
    _refresh_inventory(root)
    with pytest.raises(subject.AuthorityPeerExchangeBundleError, match="schema-3 source receipt"):
        subject.verify_authority_peer_exchange_bundle(artifact_root=root)


def test_converted_peer_values_must_match_retained_source_reconnect_phase(tmp_path: Path) -> None:
    root = _write_bundle(tmp_path)
    source_path = root / subject.SOURCE_RECEIPT
    source = json.loads(source_path.read_text(encoding="utf-8"))
    for phase_id in ("reciprocal", "reconnect"):
        phase = next(phase for phase in source["phases"] if phase["id"] == phase_id)
        phase["roles"][0]["observedPeerIds"] = [3]
        phase["roles"][1]["localPeerId"] = 3
        phase["roles"][1]["observedPeerIds"] = [1]
    source_path.write_text(json.dumps(source, indent=2) + "\n", encoding="utf-8")
    _refresh_inventory(root)
    with pytest.raises(subject.AuthorityPeerExchangeBundleError, match="does not match the retained source reconnect phase"):
        subject.verify_authority_peer_exchange_bundle(artifact_root=root)


def test_source_receipt_binding_name_is_exact(tmp_path: Path) -> None:
    root = _write_bundle(tmp_path)
    summary_path = root / subject.SUMMARY
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["peerExchangeSourceReceipt"] = "other.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(subject.AuthorityPeerExchangeBundleError, match="source receipt binding is invalid"):
        subject.verify_authority_peer_exchange_bundle(artifact_root=root)
