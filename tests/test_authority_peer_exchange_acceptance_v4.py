from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from godot_game_test_lab import authority_peer_exchange_acceptance as subject


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
            {"id": "single", "roles": [{"id": "alpha", "sessionId": "persistent-galaxy", "localPeerId": 1, "observedPeerIds": []}]},
            {"id": "reciprocal", "roles": [
                {"id": "alpha", "sessionId": "persistent-galaxy", "localPeerId": 1, "observedPeerIds": [2]},
                {"id": "beta", "sessionId": "persistent-galaxy", "localPeerId": 2, "observedPeerIds": [1]},
            ]},
            {"id": "departure", "roles": [{"id": "alpha", "sessionId": "persistent-galaxy", "localPeerId": 1, "observedPeerIds": []}]},
            {"id": "reconnect", "roles": [
                {"id": "alpha", "sessionId": "persistent-galaxy", "localPeerId": 1, "observedPeerIds": [2]},
                {"id": "beta", "sessionId": "persistent-galaxy", "localPeerId": 2, "observedPeerIds": [1]},
            ]},
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


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _fixture(root: Path) -> tuple[Path, Path, dict[str, object]]:
    root.mkdir(parents=True)
    receipt_path = root / "authority-peer-exchange.json"
    _write_json(receipt_path, _receipt_v3())
    digest = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    manifest: dict[str, object] = {
        "schemaVersion": "4.0",
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
        "verifier": {
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
            "receiptSchemaVersion": 3,
            "authoritySafetyProven": True,
            "authorityLifecycleProven": True,
            "transportProven": False,
            "browserTransportProven": False,
            "staleSocketInboundRejectedProven": True,
        },
        "sourceUnchanged": True,
    }
    manifest_path = root / "acceptance.json"
    _write_json(manifest_path, manifest)
    return manifest_path, receipt_path, manifest


def test_v4_binds_receipt_v3_inbound_stale_socket_rejection(tmp_path: Path) -> None:
    manifest_path, _receipt_path, _manifest = _fixture(tmp_path / "run")
    result = subject.verify_authority_peer_exchange_acceptance(manifest_path)
    assert result["acceptanceSchemaVersion"] == 4
    assert result["receiptSchemaVersion"] == 3
    assert result["authorityLifecycleProven"] is True
    assert result["authoritySafetyProven"] is True
    assert result["staleSocketInboundRejectedProven"] is True
    assert result["transportProven"] is False
    assert result["browserTransportProven"] is False


def test_v4_rejects_receipt_v2_even_with_forged_inbound_claim(tmp_path: Path) -> None:
    manifest_path, receipt_path, manifest = _fixture(tmp_path / "run")
    receipt = _receipt_v3()
    receipt["schemaVersion"] = "2.0"
    del receipt["authoritySafety"]["staleSocketMessageRejected"]
    _write_json(receipt_path, receipt)
    manifest["receipt"]["sha256"] = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    manifest["receipt"]["bytes"] = receipt_path.stat().st_size
    manifest["verifier"]["receiptSchemaVersion"] = 2
    _write_json(manifest_path, manifest)
    with pytest.raises(
        subject.AuthorityPeerExchangeAcceptanceError,
        match="requires receipt v3 stale inbound-message rejection proof",
    ):
        subject.verify_authority_peer_exchange_acceptance(manifest_path)


def test_v4_rejects_forged_inbound_safety_verifier_claim(tmp_path: Path) -> None:
    manifest_path, _receipt_path, manifest = _fixture(tmp_path / "run")
    manifest["verifier"]["staleSocketInboundRejectedProven"] = False
    _write_json(manifest_path, manifest)
    with pytest.raises(subject.AuthorityPeerExchangeAcceptanceError, match="verifier claim disagrees"):
        subject.verify_authority_peer_exchange_acceptance(manifest_path)
