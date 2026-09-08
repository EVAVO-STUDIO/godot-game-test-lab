from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from godot_game_test_lab import attended_multiplayer_common as common
from godot_game_test_lab import authority_peer_exchange_crosscheck_acceptance as subject


SHA_A = "a" * 40
SHA_B = "b" * 40


def _receipt() -> dict[str, object]:
    def role(role_id: str, local: int, observed: list[int]) -> dict[str, object]:
        return {
            "id": role_id,
            "sessionId": "persistent-galaxy",
            "localPeerId": local,
            "observedPeerIds": observed,
        }

    return {
        "schemaVersion": "2.0",
        "kind": "evavo-authority-peer-exchange-lifecycle",
        "gameId": "galactic-cycle-online",
        "authority": "GalacticCycleRoom",
        "protocol": "galactic-cycle.v1",
        "sessionId": "persistent-galaxy",
        "departedRoleId": "beta",
        "phases": [
            {"id": "single", "roles": [role("alpha", 1, [])]},
            {"id": "reciprocal", "roles": [role("alpha", 1, [2]), role("beta", 2, [1])]},
            {"id": "departure", "roles": [role("alpha", 1, [])]},
            {"id": "reconnect", "roles": [role("alpha", 1, [2]), role("beta", 2, [1])]},
        ],
        "privacy": {
            "rawPlayerIdsTransmitted": False,
            "runtimeSessionIdsTransmitted": False,
            "credentialsTransmitted": False,
        },
        "authoritySafety": {
            "supersededSocketRetired": True,
            "staleSocketSendRejected": True,
        },
        "truthBoundary": "server authority lifecycle only",
    }


def _assertions() -> list[dict[str, object]]:
    return [
        {"type": "metadata_capture", "path": "/root/PeerExchangeEvidence", "key": key}
        for key in (
            "evavo_peer_session_id",
            "evavo_local_peer_id",
            "evavo_observed_peer_ids",
        )
    ]


def _harness(local_peer: int, observed: list[int]) -> dict[str, object]:
    values: list[object] = ["persistent-galaxy", local_peer, observed]
    return {
        "status": "passed",
        "assertions": [
            {"index": index, "type": "metadata_capture", "accepted": True, "actual": value}
            for index, value in enumerate(values)
        ],
    }


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(root: Path) -> Path:
    run_root = root / "run"
    bundle = run_root / "bundle"
    bundle.mkdir(parents=True)
    receipt_path = bundle / "authority-peer-exchange-lifecycle.json"
    receipt_path.write_text(json.dumps(_receipt(), indent=2) + "\n", encoding="utf-8")
    profile = {
        "schemaVersion": "1.0",
        "roles": [
            {
                "id": role_id,
                "personaId": f"authority-{role_id}",
                "required": True,
                "startDelayMs": 0,
                "journey": {"id": role_id, "assertions": _assertions()},
            }
            for role_id in ("alpha", "beta")
        ],
        "truthBoundary": "fixture",
    }
    profile_path = bundle / "profile.normalized.json"
    profile_path.write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")
    summary = {
        "schemaVersion": "1.0",
        "status": "passed",
        "roles": [
            {"id": "alpha", "required": True, "status": "passed", "harness": _harness(1, [2])},
            {"id": "beta", "required": True, "status": "passed", "harness": _harness(2, [1])},
        ],
        "artifacts": common.inventory_artifacts(bundle),
    }
    summary_path = bundle / "multiplayer-agent-summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    from godot_game_test_lab.authority_peer_exchange_crosscheck import (
        verify_authority_peer_exchange_crosscheck,
    )

    verified = verify_authority_peer_exchange_crosscheck(bundle)
    manifest = {
        "schemaVersion": "1.0",
        "kind": "evavo-authority-peer-exchange-semantic-crosscheck",
        "status": "passed",
        "runId": "crosscheck-fixture-001",
        "testLab": {"sha": SHA_A, "branch": "main", "dirty": False},
        "target": {"sha": SHA_B, "branch": "main", "dirty": False},
        "nodeVersion": "v20.18.0",
        "emitter": {
            "relativePath": "authority/scripts/emit_test_lab_peer_exchange_bundle.mjs",
            "marker": f"EVAVO_AUTHORITY_TEST_LAB_PEER_EXCHANGE_BUNDLE=PASS required_roles=2 output={bundle.resolve()}",
            "markerOccurrences": 1,
            "requiredRoleCount": 2,
        },
        "verifier": {
            "marker": "EVAVO_AUTHORITY_PEER_EXCHANGE_CROSSCHECK=PASS roles=2",
            "markerOccurrences": 1,
            "requiredRoleCount": 2,
            "dynamicCaptureRoleCount": 2,
            "semanticViewsAgree": True,
            "authorityLifecycleProven": True,
            "authoritySafetyProven": True,
            "standardPeerExchangeProven": True,
            "transportProven": False,
            "browserTransportProven": False,
        },
        "evidence": {
            "authorityReceiptSha256": _sha(receipt_path),
            "profileSha256": _sha(profile_path),
            "summarySha256": _sha(summary_path),
        },
        "sourceUnchanged": True,
        "truthBoundary": verified["truthBoundary"],
    }
    manifest_path = run_root / "acceptance.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def test_crosscheck_acceptance_reopens_and_proves_retained_bundle(tmp_path: Path) -> None:
    result = subject.verify_authority_peer_exchange_crosscheck_acceptance(_fixture(tmp_path))
    assert result["proven"] is True
    assert result["evidenceBound"] is True
    assert result["sourceBound"] is True
    assert result["requiredRoleCount"] == 2
    assert result["dynamicCaptureRoleCount"] == 2
    assert result["transportProven"] is False
    assert result["browserTransportProven"] is False


def test_crosscheck_acceptance_rejects_tampered_bundle_bytes(tmp_path: Path) -> None:
    manifest = _fixture(tmp_path)
    profile = manifest.parent / "bundle" / "profile.normalized.json"
    profile.write_text(profile.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(subject.AuthorityPeerExchangeCrosscheckAcceptanceError, match="digest disagrees"):
        subject.verify_authority_peer_exchange_crosscheck_acceptance(manifest)


def test_crosscheck_acceptance_rejects_transport_escalation(tmp_path: Path) -> None:
    manifest = _fixture(tmp_path)
    raw = json.loads(manifest.read_text(encoding="utf-8"))
    raw["verifier"]["transportProven"] = True
    manifest.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(subject.AuthorityPeerExchangeCrosscheckAcceptanceError, match="transportProven"):
        subject.verify_authority_peer_exchange_crosscheck_acceptance(manifest)


def test_crosscheck_acceptance_rejects_marker_output_substitution(tmp_path: Path) -> None:
    manifest = _fixture(tmp_path)
    raw = json.loads(manifest.read_text(encoding="utf-8"))
    raw["emitter"]["marker"] = (
        "EVAVO_AUTHORITY_TEST_LAB_PEER_EXCHANGE_BUNDLE=PASS required_roles=2 output="
        + str(tmp_path.resolve())
    )
    manifest.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(subject.AuthorityPeerExchangeCrosscheckAcceptanceError, match="retained bundle"):
        subject.verify_authority_peer_exchange_crosscheck_acceptance(manifest)


def test_crosscheck_acceptance_requires_unchanged_source_claim(tmp_path: Path) -> None:
    manifest = _fixture(tmp_path)
    raw = json.loads(manifest.read_text(encoding="utf-8"))
    raw["sourceUnchanged"] = False
    manifest.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(subject.AuthorityPeerExchangeCrosscheckAcceptanceError, match="unchanged source"):
        subject.verify_authority_peer_exchange_crosscheck_acceptance(manifest)
