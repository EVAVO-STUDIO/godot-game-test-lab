from __future__ import annotations

import json
from pathlib import Path

import pytest

from godot_game_test_lab import attended_multiplayer_common as common
from godot_game_test_lab import multiplayer_peer_exchange as subject


def _assertions(session: str, local_peer: int, observed: list[int], authority: int = 1):
    return [
        {
            "type": "metadata_equals",
            "path": "NetworkState",
            "key": "evavo_peer_session_id",
            "value": session,
        },
        {
            "type": "metadata_equals",
            "path": "NetworkState",
            "key": "evavo_local_peer_id",
            "value": local_peer,
        },
        {
            "type": "metadata_equals",
            "path": "NetworkState",
            "key": "evavo_observed_peer_ids",
            "value": observed,
        },
        {
            "type": "metadata_equals",
            "path": "NetworkState",
            "key": "evavo_authority_peer_id",
            "value": authority,
        },
    ]


def _harness(count: int = 4) -> dict[str, object]:
    return {
        "status": "passed",
        "assertions": [
            {"index": index, "type": "metadata_equals", "accepted": True}
            for index in range(count)
        ],
    }


def _fixture(root: Path, *, configured: bool = True) -> tuple[Path, Path]:
    artifacts = root / "artifacts"
    artifacts.mkdir(parents=True)
    if configured:
        host_assertions = _assertions("room-001", 1, [2])
        guest_assertions = _assertions("room-001", 2, [1])
    else:
        host_assertions = [{"type": "scene_loaded"}]
        guest_assertions = [{"type": "scene_loaded"}]

    profile = {
        "schemaVersion": "1.0",
        "roles": [
            {
                "id": "host",
                "personaId": "host-persona",
                "required": True,
                "startDelayMs": 0,
                "journey": {"id": "host", "assertions": host_assertions},
            },
            {
                "id": "guest",
                "personaId": "guest-persona",
                "required": True,
                "startDelayMs": 0,
                "journey": {"id": "guest", "assertions": guest_assertions},
            },
        ],
        "truthBoundary": "fixture",
    }
    (artifacts / "profile.normalized.json").write_text(
        json.dumps(profile, indent=2) + "\n", encoding="utf-8"
    )
    inventory = common.inventory_artifacts(artifacts)
    harness_count = 4 if configured else 1
    summary = {
        "schemaVersion": "1.0",
        "status": "passed",
        "roles": [
            {
                "id": "host",
                "required": True,
                "status": "passed",
                "harness": _harness(harness_count),
            },
            {
                "id": "guest",
                "required": True,
                "status": "passed",
                "harness": _harness(harness_count),
            },
        ],
        "artifacts": inventory,
    }
    summary_path = artifacts / "multiplayer-agent-summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return artifacts, summary_path


def test_proves_shared_session_and_reciprocal_peer_observation(tmp_path: Path) -> None:
    artifacts, summary_path = _fixture(tmp_path)
    result = subject.verify_peer_exchange(summary_path=summary_path, artifact_root=artifacts)
    assert result["configured"] is True
    assert result["proven"] is True
    assert result["requiredRoleCount"] == 2
    assert result["authorityObserved"] is True
    assert result["findings"] == []


def test_unconfigured_profile_is_not_misrepresented_as_peer_exchange(tmp_path: Path) -> None:
    artifacts, summary_path = _fixture(tmp_path, configured=False)
    result = subject.verify_peer_exchange(summary_path=summary_path, artifact_root=artifacts)
    assert result["configured"] is False
    assert result["proven"] is False
    assert result["roles"] == []


def test_missing_reciprocal_peer_observation_fails_closed(tmp_path: Path) -> None:
    artifacts, summary_path = _fixture(tmp_path)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    profile_path = artifacts / "profile.normalized.json"
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    profile["roles"][1]["journey"]["assertions"][2]["value"] = []
    profile_path.write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")
    summary["artifacts"] = common.inventory_artifacts(artifacts)
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    result = subject.verify_peer_exchange(summary_path=summary_path, artifact_root=artifacts)
    assert result["configured"] is True
    assert result["proven"] is False
    assert any("every other required peer" in finding for finding in result["findings"])


def test_mismatched_session_ids_fail_closed(tmp_path: Path) -> None:
    artifacts, summary_path = _fixture(tmp_path)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    profile_path = artifacts / "profile.normalized.json"
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    profile["roles"][1]["journey"]["assertions"][0]["value"] = "room-002"
    profile_path.write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")
    summary["artifacts"] = common.inventory_artifacts(artifacts)
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    result = subject.verify_peer_exchange(summary_path=summary_path, artifact_root=artifacts)
    assert result["proven"] is False
    assert any("shared multiplayer session" in finding for finding in result["findings"])


def test_failed_reserved_assertion_cannot_be_used_as_evidence(tmp_path: Path) -> None:
    artifacts, summary_path = _fixture(tmp_path)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["roles"][1]["harness"]["assertions"][2]["accepted"] = False
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    result = subject.verify_peer_exchange(summary_path=summary_path, artifact_root=artifacts)
    assert result["configured"] is True
    assert result["proven"] is False
    assert any("did not pass reserved multiplayer assertion" in finding for finding in result["findings"])


def test_tampered_normalized_profile_is_rejected_by_inventory(tmp_path: Path) -> None:
    artifacts, summary_path = _fixture(tmp_path)
    profile_path = artifacts / "profile.normalized.json"
    profile_path.write_text(profile_path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(
        subject.PeerExchangeEvidenceError,
        match="artifact inventory does not match retained bytes",
    ):
        subject.verify_peer_exchange(summary_path=summary_path, artifact_root=artifacts)
