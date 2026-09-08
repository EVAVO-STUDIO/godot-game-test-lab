from __future__ import annotations

import json
from pathlib import Path

import pytest

from godot_game_test_lab import attended_multiplayer_common as common
from godot_game_test_lab import authority_peer_exchange_crosscheck as subject


def _authority_receipt() -> dict[str, object]:
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
        "truthBoundary": "server authority lifecycle only",
    }


def _capture_assertions() -> list[dict[str, object]]:
    return [
        {
            "type": "metadata_capture",
            "path": "/root/PeerExchangeEvidence",
            "key": key,
        }
        for key in (
            "evavo_peer_session_id",
            "evavo_local_peer_id",
            "evavo_observed_peer_ids",
        )
    ]


def _harness(session: str, local_peer: int, observed: list[int]) -> dict[str, object]:
    values: list[object] = [session, local_peer, observed]
    return {
        "status": "passed",
        "assertions": [
            {
                "index": index,
                "type": "metadata_capture",
                "accepted": True,
                "actual": value,
            }
            for index, value in enumerate(values)
        ],
    }


def _fixture(root: Path) -> Path:
    artifacts = root / "artifacts"
    artifacts.mkdir(parents=True)
    receipt_path = artifacts / "authority-peer-exchange-lifecycle.json"
    receipt_path.write_text(json.dumps(_authority_receipt(), indent=2) + "\n", encoding="utf-8")
    profile = {
        "schemaVersion": "1.0",
        "roles": [
            {
                "id": "alpha",
                "personaId": "authority-alpha",
                "required": True,
                "startDelayMs": 0,
                "journey": {"id": "alpha", "assertions": _capture_assertions()},
            },
            {
                "id": "beta",
                "personaId": "authority-beta",
                "required": True,
                "startDelayMs": 0,
                "journey": {"id": "beta", "assertions": _capture_assertions()},
            },
        ],
        "truthBoundary": "fixture",
    }
    (artifacts / "profile.normalized.json").write_text(
        json.dumps(profile, indent=2) + "\n", encoding="utf-8"
    )
    inventory = common.inventory_artifacts(artifacts)
    summary = {
        "schemaVersion": "1.0",
        "status": "passed",
        "roles": [
            {
                "id": "alpha",
                "required": True,
                "status": "passed",
                "harness": _harness("persistent-galaxy", 1, [2]),
            },
            {
                "id": "beta",
                "required": True,
                "status": "passed",
                "harness": _harness("persistent-galaxy", 2, [1]),
            },
        ],
        "artifacts": inventory,
    }
    (artifacts / "multiplayer-agent-summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    return artifacts


def test_crosscheck_proves_both_semantic_views_agree(tmp_path: Path) -> None:
    result = subject.verify_authority_peer_exchange_crosscheck(_fixture(tmp_path))
    assert result["proven"] is True
    assert result["authorityLifecycleProven"] is True
    assert result["authoritySafetyProven"] is True
    assert result["staleSocketInboundRejectedProven"] is True
    assert result["authorityReceiptSchemaVersion"] == 3
    assert result["standardPeerExchangeProven"] is True
    assert result["dynamicCaptureRoleCount"] == 2
    assert result["semanticViewsAgree"] is True
    assert result["transportProven"] is False
    assert result["browserTransportProven"] is False
    assert result["requiredRoleCount"] == 2


def test_crosscheck_rejects_peer_mapping_disagreement(tmp_path: Path) -> None:
    artifacts = _fixture(tmp_path)
    summary_path = artifacts / "multiplayer-agent-summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["roles"][0]["harness"]["assertions"][1]["actual"] = 2
    summary["roles"][0]["harness"]["assertions"][2]["actual"] = [1]
    summary["roles"][1]["harness"]["assertions"][1]["actual"] = 1
    summary["roles"][1]["harness"]["assertions"][2]["actual"] = [2]
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(subject.AuthorityPeerExchangeCrosscheckError, match="local peer id disagrees"):
        subject.verify_authority_peer_exchange_crosscheck(artifacts)


def test_crosscheck_requires_dynamic_capture_for_all_roles(tmp_path: Path) -> None:
    artifacts = _fixture(tmp_path)
    profile_path = artifacts / "profile.normalized.json"
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    for assertion, value in zip(
        profile["roles"][1]["journey"]["assertions"],
        ["persistent-galaxy", 2, [1]],
        strict=True,
    ):
        assertion["type"] = "metadata_equals"
        assertion["value"] = value
    profile_path.write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")
    summary_path = artifacts / "multiplayer-agent-summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["artifacts"] = common.inventory_artifacts(artifacts)
    for record in summary["roles"][1]["harness"]["assertions"]:
        record["type"] = "metadata_equals"
        record.pop("actual", None)
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(subject.AuthorityPeerExchangeCrosscheckError, match="dynamic metadata capture"):
        subject.verify_authority_peer_exchange_crosscheck(artifacts)


def test_crosscheck_rejects_downgraded_v2_authority_receipt(tmp_path: Path) -> None:
    artifacts = _fixture(tmp_path)
    receipt_path = artifacts / "authority-peer-exchange-lifecycle.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["schemaVersion"] = "2.0"
    receipt["authoritySafety"].pop("staleSocketMessageRejected")
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    summary_path = artifacts / "multiplayer-agent-summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["artifacts"] = common.inventory_artifacts(artifacts)
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(subject.AuthorityPeerExchangeCrosscheckError, match="requires a v3 lifecycle receipt"):
        subject.verify_authority_peer_exchange_crosscheck(artifacts)


def test_crosscheck_detects_tampered_authority_receipt_through_bundle_inventory(tmp_path: Path) -> None:
    artifacts = _fixture(tmp_path)
    receipt = artifacts / "authority-peer-exchange-lifecycle.json"
    receipt.write_text(receipt.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(Exception, match="artifact inventory does not match retained bytes"):
        subject.verify_authority_peer_exchange_crosscheck(artifacts)
