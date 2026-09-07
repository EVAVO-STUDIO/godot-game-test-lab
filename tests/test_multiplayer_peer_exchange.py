from __future__ import annotations

import json
from pathlib import Path

import pytest

from godot_game_test_lab import attended_multiplayer_common as common
from godot_game_test_lab import multiplayer_peer_exchange as subject


_RESERVED_KEYS = [
    "evavo_peer_session_id",
    "evavo_local_peer_id",
    "evavo_observed_peer_ids",
    "evavo_authority_peer_id",
]


def _capture_assertions() -> list[dict[str, object]]:
    return [
        {"type": "metadata_capture", "path": "NetworkState", "key": key}
        for key in _RESERVED_KEYS
    ]


def _legacy_assertions(
    session: str, local_peer: int, observed: list[int], authority: int = 1
) -> list[dict[str, object]]:
    values: list[object] = [session, local_peer, observed, authority]
    return [
        {
            "type": "metadata_equals",
            "path": "NetworkState",
            "key": key,
            "value": value,
        }
        for key, value in zip(_RESERVED_KEYS, values, strict=True)
    ]


def _capture_harness(
    session: str, local_peer: int, observed: list[int], authority: int = 1
) -> dict[str, object]:
    values: list[object] = [session, local_peer, observed, authority]
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


def _legacy_harness(count: int = 4) -> dict[str, object]:
    return {
        "status": "passed",
        "assertions": [
            {"index": index, "type": "metadata_equals", "accepted": True}
            for index in range(count)
        ],
    }


def _fixture(
    root: Path, *, configured: bool = True, legacy: bool = False
) -> tuple[Path, Path]:
    artifacts = root / "artifacts"
    artifacts.mkdir(parents=True)
    if configured and legacy:
        host_assertions = _legacy_assertions("room-001", 1, [2])
        guest_assertions = _legacy_assertions("room-001", 2, [1])
    elif configured:
        host_assertions = _capture_assertions()
        guest_assertions = _capture_assertions()
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
    if configured and legacy:
        host_harness = _legacy_harness()
        guest_harness = _legacy_harness()
    elif configured:
        host_harness = _capture_harness("room-001", 1, [2])
        guest_harness = _capture_harness("room-001", 2, [1])
    else:
        host_harness = {
            "status": "passed",
            "assertions": [{"index": 0, "type": "scene_loaded", "accepted": True}],
        }
        guest_harness = {
            "status": "passed",
            "assertions": [{"index": 0, "type": "scene_loaded", "accepted": True}],
        }
    summary = {
        "schemaVersion": "1.0",
        "status": "passed",
        "roles": [
            {
                "id": "host",
                "required": True,
                "status": "passed",
                "harness": host_harness,
            },
            {
                "id": "guest",
                "required": True,
                "status": "passed",
                "harness": guest_harness,
            },
        ],
        "artifacts": inventory,
    }
    summary_path = artifacts / "multiplayer-agent-summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return artifacts, summary_path


def _rewrite_summary_inventory(artifacts: Path, summary_path: Path) -> dict[str, object]:
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["artifacts"] = common.inventory_artifacts(artifacts)
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def test_proves_shared_session_and_reciprocal_dynamic_peer_observation(tmp_path: Path) -> None:
    artifacts, summary_path = _fixture(tmp_path)
    result = subject.verify_peer_exchange(summary_path=summary_path, artifact_root=artifacts)
    assert result["configured"] is True
    assert result["proven"] is True
    assert result["requiredRoleCount"] == 2
    assert result["authorityObserved"] is True
    assert result["dynamicCaptureRoleCount"] == 2
    assert result["roles"][0]["dynamicRequiredMetadataCaptured"] is True
    assert result["findings"] == []


def test_legacy_fixed_value_metadata_equals_remains_supported(tmp_path: Path) -> None:
    artifacts, summary_path = _fixture(tmp_path, legacy=True)
    result = subject.verify_peer_exchange(summary_path=summary_path, artifact_root=artifacts)
    assert result["configured"] is True
    assert result["proven"] is True
    assert result["dynamicCaptureRoleCount"] == 0


def test_unconfigured_profile_is_not_misrepresented_as_peer_exchange(tmp_path: Path) -> None:
    artifacts, summary_path = _fixture(tmp_path, configured=False)
    result = subject.verify_peer_exchange(summary_path=summary_path, artifact_root=artifacts)
    assert result["configured"] is False
    assert result["proven"] is False
    assert result["dynamicCaptureRoleCount"] == 0
    assert result["roles"] == []


def test_missing_capture_actual_value_fails_closed(tmp_path: Path) -> None:
    artifacts, summary_path = _fixture(tmp_path)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["roles"][1]["harness"]["assertions"][2].pop("actual")
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    result = subject.verify_peer_exchange(summary_path=summary_path, artifact_root=artifacts)
    assert result["configured"] is True
    assert result["proven"] is False
    assert any("has no actual value" in finding for finding in result["findings"])


def test_missing_reciprocal_peer_observation_fails_closed(tmp_path: Path) -> None:
    artifacts, summary_path = _fixture(tmp_path)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["roles"][1]["harness"]["assertions"][2]["actual"] = []
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    result = subject.verify_peer_exchange(summary_path=summary_path, artifact_root=artifacts)
    assert result["configured"] is True
    assert result["proven"] is False
    assert any("every other required peer" in finding for finding in result["findings"])


def test_capture_uses_runtime_actual_not_profile_expected_value(tmp_path: Path) -> None:
    artifacts, summary_path = _fixture(tmp_path)
    profile_path = artifacts / "profile.normalized.json"
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    assert all(
        "value" not in assertion
        for role in profile["roles"]
        for assertion in role["journey"]["assertions"]
    )
    result = subject.verify_peer_exchange(summary_path=summary_path, artifact_root=artifacts)
    assert result["roles"][0]["localPeerId"] == 1
    assert result["roles"][1]["localPeerId"] == 2


def test_mismatched_runtime_session_ids_fail_closed(tmp_path: Path) -> None:
    artifacts, summary_path = _fixture(tmp_path)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["roles"][1]["harness"]["assertions"][0]["actual"] = "room-002"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    result = subject.verify_peer_exchange(summary_path=summary_path, artifact_root=artifacts)
    assert result["proven"] is False
    assert any("shared multiplayer session" in finding for finding in result["findings"])


def test_local_peer_cannot_appear_in_observed_peer_set(tmp_path: Path) -> None:
    artifacts, summary_path = _fixture(tmp_path)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["roles"][0]["harness"]["assertions"][2]["actual"] = [1, 2]
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    result = subject.verify_peer_exchange(summary_path=summary_path, artifact_root=artifacts)
    assert result["proven"] is False
    assert any("include its local peer id" in finding for finding in result["findings"])


def test_failed_reserved_capture_cannot_be_used_as_evidence(tmp_path: Path) -> None:
    artifacts, summary_path = _fixture(tmp_path)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["roles"][1]["harness"]["assertions"][2]["accepted"] = False
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    result = subject.verify_peer_exchange(summary_path=summary_path, artifact_root=artifacts)
    assert result["configured"] is True
    assert result["proven"] is False
    assert any("did not pass reserved multiplayer assertion" in finding for finding in result["findings"])


def test_foreign_shared_authority_peer_fails_closed(tmp_path: Path) -> None:
    artifacts, summary_path = _fixture(tmp_path)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["roles"][0]["harness"]["assertions"][3]["actual"] = 99
    summary["roles"][1]["harness"]["assertions"][3]["actual"] = 99
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    result = subject.verify_peer_exchange(summary_path=summary_path, artifact_root=artifacts)
    assert result["proven"] is False
    assert any("not a participating required peer" in finding for finding in result["findings"])


def test_tampered_normalized_profile_is_rejected_by_inventory(tmp_path: Path) -> None:
    artifacts, summary_path = _fixture(tmp_path)
    profile_path = artifacts / "profile.normalized.json"
    profile_path.write_text(profile_path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(
        subject.PeerExchangeEvidenceError,
        match="artifact inventory does not match retained bytes",
    ):
        subject.verify_peer_exchange(summary_path=summary_path, artifact_root=artifacts)
