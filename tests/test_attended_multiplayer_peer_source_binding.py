from __future__ import annotations

import json
from pathlib import Path

import pytest

from godot_game_test_lab import attended_multiplayer as attended
from godot_game_test_lab import attended_multiplayer_receipt as receipt_subject


def _source_receipt() -> dict[str, object]:
    roles = [
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
    ]
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
            {"id": "reciprocal", "roles": roles},
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
            {"id": "reconnect", "roles": roles},
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
        "truthBoundary": "Server authority source fixture; browser transport is not certified.",
    }


def _peer_exchange() -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "configured": True,
        "proven": True,
        "requiredRoleCount": 2,
        "authorityObserved": False,
        "dynamicCaptureRoleCount": 2,
        "roles": [
            {
                "id": "alpha",
                "sessionId": "persistent-galaxy",
                "localPeerId": 1,
                "observedPeerIds": [2],
                "authorityPeerId": None,
                "dynamicRequiredMetadataCaptured": True,
                "reservedAssertionsAccepted": True,
            },
            {
                "id": "beta",
                "sessionId": "persistent-galaxy",
                "localPeerId": 2,
                "observedPeerIds": [1],
                "authorityPeerId": None,
                "dynamicRequiredMetadataCaptured": True,
                "reservedAssertionsAccepted": True,
            },
        ],
        "findings": [],
        "truthBoundary": "generic peer evidence",
    }


def test_attended_source_verification_binds_authority_receipt_to_generic_roles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    source = artifacts / "authority-peer-exchange-lifecycle.json"
    source.write_text(json.dumps(_source_receipt()), encoding="utf-8")
    monkeypatch.setattr(attended, "_verify_multiplayer_summary_sources", lambda **_kwargs: {})
    monkeypatch.setattr(attended, "verify_peer_exchange", lambda **_kwargs: _peer_exchange())

    evidence = attended.verify_multiplayer_summary_sources(
        summary_path=artifacts / "multiplayer-agent-summary.json",
        artifact_root=artifacts,
    )
    assert evidence["peerExchange"]["proven"] is True
    assert "independently revalidated" in evidence["peerExchange"]["truthBoundary"]


def test_attended_source_verification_rejects_summary_role_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    source = artifacts / "authority-peer-exchange-lifecycle.json"
    source.write_text(json.dumps(_source_receipt()), encoding="utf-8")
    peer = _peer_exchange()
    peer["roles"][1]["observedPeerIds"] = []
    monkeypatch.setattr(attended, "_verify_multiplayer_summary_sources", lambda **_kwargs: {})
    monkeypatch.setattr(attended, "verify_peer_exchange", lambda **_kwargs: peer)

    with pytest.raises(
        attended.AttendedMultiplayerError,
        match="AUTHORITY_PEER_EXCHANGE_ROLE_EVIDENCE_MISMATCH",
    ):
        attended.verify_multiplayer_summary_sources(
            summary_path=artifacts / "multiplayer-agent-summary.json",
            artifact_root=artifacts,
        )


def test_receipt_v2_accepts_dynamic_capture_observability_without_schema_drift() -> None:
    stable = receipt_subject._verified_peer_exchange({"peerExchange": _peer_exchange()})
    assert "dynamicCaptureRoleCount" not in stable
    assert stable["configured"] is True
    assert stable["proven"] is True


def test_receipt_rejects_impossible_dynamic_capture_count() -> None:
    peer = _peer_exchange()
    peer["dynamicCaptureRoleCount"] = 3
    with pytest.raises(Exception, match="DYNAMIC_CAPTURE_COUNT_INVALID"):
        receipt_subject._verified_peer_exchange({"peerExchange": peer})
