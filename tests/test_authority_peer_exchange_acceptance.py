from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from godot_game_test_lab import authority_peer_exchange_acceptance as subject


def _authority_receipt() -> dict[str, object]:
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


def _authority_receipt_v2() -> dict[str, object]:
    receipt = _authority_receipt()
    receipt["schemaVersion"] = "2.0"
    receipt["authoritySafety"] = {
        "supersededSocketRetired": True,
        "staleSocketSendRejected": True,
    }
    return receipt


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _base_manifest(receipt_path: Path) -> dict[str, object]:
    digest = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    return {
        "kind": "evavo-authority-peer-exchange-acceptance",
        "status": "passed",
        "runId": "20260908T010203004Z-bbbbbbbbbbbb-0123abcd",
        "testLab": {"sha": "a" * 40, "branch": "main", "dirty": False},
        "target": {"sha": "b" * 40, "branch": "main", "dirty": False},
        "nodeVersion": "v20.19.0",
        "emitter": {
            "relativePath": "authority/scripts/emit_peer_exchange_evidence.mjs",
            "marker": "EVAVO_AUTHORITY_PEER_EXCHANGE_RECEIPT=PASS",
            "markerOccurrences": 1,
        },
        "receipt": {
            "path": "authority-peer-exchange.json",
            "sha256": digest,
            "bytes": receipt_path.stat().st_size,
        },
        "sourceUnchanged": True,
    }


def _fixture(root: Path) -> tuple[Path, Path, dict[str, object]]:
    root.mkdir(parents=True)
    receipt_path = root / "authority-peer-exchange.json"
    _write_json(receipt_path, _authority_receipt())
    manifest = _base_manifest(receipt_path)
    manifest["schemaVersion"] = "2.0"
    manifest["verifier"] = {
        "marker": "EVAVO_AUTHORITY_PEER_EXCHANGE=PASS roles=2",
        "markerOccurrences": 1,
        "proven": True,
        "privacySafe": True,
        "stablePeerMapping": True,
        "requiredRoleCount": 2,
        "gameId": "galactic-cycle-online",
        "authority": "GalacticCycleRoom",
        "protocol": "galactic-cycle.v1",
        "sessionId": "persistent-galaxy",
    }
    manifest_path = root / "acceptance.json"
    _write_json(manifest_path, manifest)
    return manifest_path, receipt_path, manifest


def _fixture_v3(root: Path) -> tuple[Path, Path, dict[str, object]]:
    root.mkdir(parents=True)
    receipt_path = root / "authority-peer-exchange.json"
    _write_json(receipt_path, _authority_receipt_v2())
    manifest = _base_manifest(receipt_path)
    manifest["schemaVersion"] = "3.0"
    manifest["verifier"] = {
        "marker": "EVAVO_AUTHORITY_PEER_EXCHANGE=PASS roles=2",
        "markerOccurrences": 1,
        "proven": True,
        "privacySafe": True,
        "stablePeerMapping": True,
        "requiredRoleCount": 2,
        "gameId": "galactic-cycle-online",
        "authority": "GalacticCycleRoom",
        "protocol": "galactic-cycle.v1",
        "sessionId": "persistent-galaxy",
        "receiptSchemaVersion": 2,
        "authoritySafetyProven": True,
        "authorityLifecycleProven": True,
        "transportProven": False,
        "browserTransportProven": False,
    }
    manifest_path = root / "acceptance.json"
    _write_json(manifest_path, manifest)
    return manifest_path, receipt_path, manifest


def _refresh_receipt_binding(manifest_path: Path, receipt_path: Path) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["receipt"]["sha256"] = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    manifest["receipt"]["bytes"] = receipt_path.stat().st_size
    _write_json(manifest_path, manifest)


def test_verifies_legacy_v2_source_bound_authority_acceptance(tmp_path: Path) -> None:
    manifest_path, _receipt_path, _manifest = _fixture(tmp_path / "run")
    result = subject.verify_authority_peer_exchange_acceptance(manifest_path)
    assert result["proven"] is True
    assert result["acceptanceSchemaVersion"] == 2
    assert result["receiptSchemaVersion"] == 1
    assert result["authoritySafetyProven"] is False
    assert result["sourceBound"] is True
    assert result["privacySafe"] is True
    assert result["stablePeerMapping"] is True
    assert result["transportProven"] is False
    assert result["browserTransportProven"] is False
    assert result["testLabSha"] == "a" * 40
    assert result["targetSha"] == "b" * 40


def test_v3_acceptance_binds_receipt_v2_authority_safety(tmp_path: Path) -> None:
    manifest_path, _receipt_path, _manifest = _fixture_v3(tmp_path / "run")
    result = subject.verify_authority_peer_exchange_acceptance(manifest_path)
    assert result["proven"] is True
    assert result["acceptanceSchemaVersion"] == 3
    assert result["receiptSchemaVersion"] == 2
    assert result["authorityLifecycleProven"] is True
    assert result["authoritySafetyProven"] is True
    assert result["transportProven"] is False
    assert result["browserTransportProven"] is False


def test_v3_rejects_v1_receipt_even_if_manifest_claims_safety(tmp_path: Path) -> None:
    manifest_path, receipt_path, manifest = _fixture_v3(tmp_path / "run")
    _write_json(receipt_path, _authority_receipt())
    manifest["receipt"]["sha256"] = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    manifest["receipt"]["bytes"] = receipt_path.stat().st_size
    _write_json(manifest_path, manifest)
    with pytest.raises(subject.AuthorityPeerExchangeAcceptanceError, match="requires a receipt v2 authority-safety proof"):
        subject.verify_authority_peer_exchange_acceptance(manifest_path)


def test_v3_rejects_forged_authority_safety_or_transport_claim(tmp_path: Path) -> None:
    manifest_path, _receipt_path, manifest = _fixture_v3(tmp_path / "run")
    manifest["verifier"]["authoritySafetyProven"] = False
    _write_json(manifest_path, manifest)
    with pytest.raises(subject.AuthorityPeerExchangeAcceptanceError, match="verifier claim disagrees"):
        subject.verify_authority_peer_exchange_acceptance(manifest_path)

    manifest["verifier"]["authoritySafetyProven"] = True
    manifest["verifier"]["browserTransportProven"] = True
    _write_json(manifest_path, manifest)
    with pytest.raises(subject.AuthorityPeerExchangeAcceptanceError, match="verifier claim disagrees"):
        subject.verify_authority_peer_exchange_acceptance(manifest_path)


def test_tampered_receipt_digest_fails_closed(tmp_path: Path) -> None:
    manifest_path, receipt_path, _manifest = _fixture_v3(tmp_path / "run")
    receipt_path.write_text(receipt_path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(subject.AuthorityPeerExchangeAcceptanceError, match="byte count|digest"):
        subject.verify_authority_peer_exchange_acceptance(manifest_path)


def test_forged_verifier_claim_fails_closed(tmp_path: Path) -> None:
    manifest_path, _receipt_path, manifest = _fixture_v3(tmp_path / "run")
    manifest["verifier"]["gameId"] = "other-game"
    _write_json(manifest_path, manifest)
    with pytest.raises(subject.AuthorityPeerExchangeAcceptanceError, match="verifier claim disagrees"):
        subject.verify_authority_peer_exchange_acceptance(manifest_path)


def test_dirty_or_non_main_source_claims_fail_closed(tmp_path: Path) -> None:
    manifest_path, _receipt_path, manifest = _fixture_v3(tmp_path / "run")
    manifest["target"]["dirty"] = True
    _write_json(manifest_path, manifest)
    with pytest.raises(subject.AuthorityPeerExchangeAcceptanceError, match="recorded clean"):
        subject.verify_authority_peer_exchange_acceptance(manifest_path)

    manifest["target"]["dirty"] = False
    manifest["testLab"]["branch"] = "feature"
    _write_json(manifest_path, manifest)
    with pytest.raises(subject.AuthorityPeerExchangeAcceptanceError, match="branch must be main"):
        subject.verify_authority_peer_exchange_acceptance(manifest_path)


def test_rebound_but_invalid_lifecycle_receipt_still_fails(tmp_path: Path) -> None:
    manifest_path, receipt_path, _manifest = _fixture_v3(tmp_path / "run")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["phases"][3]["roles"][0]["localPeerId"] = 7
    receipt["phases"][3]["roles"][0]["observedPeerIds"] = [8]
    receipt["phases"][3]["roles"][1]["localPeerId"] = 8
    receipt["phases"][3]["roles"][1]["observedPeerIds"] = [7]
    _write_json(receipt_path, receipt)
    _refresh_receipt_binding(manifest_path, receipt_path)
    with pytest.raises(subject.AuthorityPeerExchangeAcceptanceError, match="changed the reciprocal peer mapping"):
        subject.verify_authority_peer_exchange_acceptance(manifest_path)


def test_verifier_marker_role_count_must_match_retained_receipt(tmp_path: Path) -> None:
    manifest_path, _receipt_path, manifest = _fixture_v3(tmp_path / "run")
    manifest["verifier"]["marker"] = "EVAVO_AUTHORITY_PEER_EXCHANGE=PASS roles=3"
    _write_json(manifest_path, manifest)
    with pytest.raises(subject.AuthorityPeerExchangeAcceptanceError, match="marker role count"):
        subject.verify_authority_peer_exchange_acceptance(manifest_path)


def test_old_node_or_duplicate_emitter_marker_claim_fails_closed(tmp_path: Path) -> None:
    manifest_path, _receipt_path, manifest = _fixture_v3(tmp_path / "run")
    manifest["nodeVersion"] = "v18.20.0"
    _write_json(manifest_path, manifest)
    with pytest.raises(subject.AuthorityPeerExchangeAcceptanceError, match="Node.js version"):
        subject.verify_authority_peer_exchange_acceptance(manifest_path)

    manifest["nodeVersion"] = "v20.19.0"
    manifest["emitter"]["markerOccurrences"] = 2
    _write_json(manifest_path, manifest)
    with pytest.raises(subject.AuthorityPeerExchangeAcceptanceError, match="emitter marker evidence"):
        subject.verify_authority_peer_exchange_acceptance(manifest_path)
