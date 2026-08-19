from __future__ import annotations

import pytest

from godot_game_test_lab.multiplayer_profile import normalize_multiplayer_profile
from godot_game_test_lab.native_qa_common import NativeQaError


def _journey() -> dict[str, object]:
    return {
        "maxFrames": 300,
        "fps": 30,
        "steps": [{"type": "wait", "frames": 30}],
        "assertions": [{"type": "scene_loaded"}],
        "userArguments": ["--multiplayer-role=client"],
    }


def test_normalizes_two_roles_through_native_journey_contract() -> None:
    profile = normalize_multiplayer_profile(
        {
            "schemaVersion": "1.0",
            "roles": [
                {
                    "id": "host",
                    "personaId": "experienced-host",
                    "startDelayMs": 0,
                    "journey": {
                        **_journey(),
                        "userArguments": ["--multiplayer-role=host"],
                    },
                },
                {
                    "id": "guest",
                    "personaId": "first-time-guest",
                    "startDelayMs": 750,
                    "journey": _journey(),
                },
            ],
        }
    )

    assert [role["id"] for role in profile["roles"]] == ["host", "guest"]
    assert profile["roles"][1]["journey"]["id"] == "guest"
    assert profile["roles"][1]["journey"]["required"] is True
    assert profile["roles"][1]["startDelayMs"] == 750
    assert "human judgement" in profile["truthBoundary"]


def test_rejects_single_role_and_duplicate_role_ids() -> None:
    with pytest.raises(NativeQaError, match="2 to 8 roles"):
        normalize_multiplayer_profile(
            {"schemaVersion": "1.0", "roles": [{"id": "only", "journey": _journey()}]}
        )

    with pytest.raises(NativeQaError, match="duplicated"):
        normalize_multiplayer_profile(
            {
                "schemaVersion": "1.0",
                "roles": [
                    {"id": "same", "journey": _journey()},
                    {"id": "same", "journey": _journey()},
                ],
            }
        )


def test_reuses_native_worker_owned_argument_guard() -> None:
    with pytest.raises(NativeQaError, match="worker-owned Godot option"):
        normalize_multiplayer_profile(
            {
                "schemaVersion": "1.0",
                "roles": [
                    {
                        "id": "host",
                        "journey": {**_journey(), "userArguments": ["--headless"]},
                    },
                    {"id": "guest", "journey": _journey()},
                ],
            }
        )


def test_rejects_unknown_fields_and_mismatched_nested_id() -> None:
    with pytest.raises(NativeQaError, match="unsupported fields"):
        normalize_multiplayer_profile(
            {
                "schemaVersion": "1.0",
                "roles": [
                    {"id": "host", "journey": _journey(), "unsafe": True},
                    {"id": "guest", "journey": _journey()},
                ],
            }
        )

    with pytest.raises(NativeQaError, match="must match"):
        normalize_multiplayer_profile(
            {
                "schemaVersion": "1.0",
                "roles": [
                    {"id": "host", "journey": {**_journey(), "id": "other"}},
                    {"id": "guest", "journey": _journey()},
                ],
            }
        )
