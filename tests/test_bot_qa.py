from __future__ import annotations

import json
from pathlib import Path

import pytest

from godot_game_test_lab.bot_profile import normalize_bot_profile
from godot_game_test_lab.bot_runner import plan_candidates, state_fingerprint
from godot_game_test_lab.native_qa_common import NativeQaError
from godot_game_test_lab.profile_bootstrap import build_profile


def profile() -> dict:
    return {
        "schemaVersion": "1.0",
        "campaigns": [
            {
                "id": "menu-explorer",
                "mode": "mixed",
                "devices": ["mouse", "keyboard", "gamepad", "semantic"],
                "maxStates": 8,
                "maxRuns": 16,
                "maxDepth": 3,
                "maxFrames": 300,
                "width": 640,
                "height": 360,
                "blockedText": ["quit", "delete"],
            }
        ],
    }


def report() -> dict:
    return {
        "scene": "res://main.tscn",
        "ui": {
            "viewport": {"width": 640, "height": 360},
            "focusOwner": "/root/Main/Start",
            "mouseMode": 0,
            "controls": [
                {
                    "path": "/root/Main/Start",
                    "class": "Button",
                    "name": "Start",
                    "text": "Start Game",
                    "x": 100,
                    "y": 100,
                    "width": 200,
                    "height": 50,
                    "focusMode": 2,
                    "insideViewport": True,
                },
                {
                    "path": "/root/Main/Quit",
                    "class": "Button",
                    "name": "Quit",
                    "text": "Quit",
                    "x": 100,
                    "y": 200,
                    "width": 200,
                    "height": 50,
                    "focusMode": 2,
                    "insideViewport": True,
                },
            ],
        },
        "inputMap": {
            "actions": [
                {
                    "name": "ui_accept",
                    "events": [
                        {
                            "type": "InputEventKey",
                            "category": "keyboard",
                            "physicalKeycode": 4194309,
                        },
                        {
                            "type": "InputEventJoypadButton",
                            "category": "gamepad",
                            "buttonIndex": 0,
                        },
                    ],
                },
                {"name": "delete_save", "events": []},
            ]
        },
    }


def test_profile_normalizes_safe_defaults() -> None:
    campaign = normalize_bot_profile(profile())["campaigns"][0]
    assert campaign["required"] is True
    assert campaign["seed"] == 1871
    assert campaign["blockedText"] == ["quit", "delete"]
    assert campaign["actionDenylist"]
    assert campaign["renderingMethod"] == "forward_plus"


def test_profile_rejects_unknown_duplicate_and_unsafe_values() -> None:
    value = profile()
    value["campaigns"][0]["unknown"] = True
    with pytest.raises(NativeQaError, match="unsupported fields"):
        normalize_bot_profile(value)

    value = profile()
    value["campaigns"].append(dict(value["campaigns"][0]))
    with pytest.raises(NativeQaError, match="duplicated"):
        normalize_bot_profile(value)

    value = profile()
    value["campaigns"][0]["userArguments"] = ["--path=C:/escape"]
    with pytest.raises(NativeQaError, match="worker-owned"):
        normalize_bot_profile(value)


def test_profile_rejects_incompatible_renderer_and_unbounded_runs() -> None:
    value = profile()
    value["campaigns"][0].update(
        {"renderingMethod": "forward_plus", "renderingDriver": "opengl3"}
    )
    with pytest.raises(NativeQaError, match="require vulkan or d3d12"):
        normalize_bot_profile(value)

    value = profile()
    value["campaigns"][0].update({"maxStates": 20, "maxRuns": 10})
    with pytest.raises(NativeQaError, match="at least maxStates"):
        normalize_bot_profile(value)


def test_planner_emits_safe_mapped_device_candidates() -> None:
    campaign = normalize_bot_profile(profile())["campaigns"][0]
    candidates = plan_candidates(report(), campaign, state_index=0)
    labels = {(candidate["label"], candidate["device"]) for candidate in candidates}
    assert ("Start Game", "mouse") in labels
    assert ("ui_accept", "keyboard") in labels
    assert ("ui_accept", "gamepad") in labels
    assert ("ui_accept", "semantic") in labels
    assert all("Quit" not in candidate["label"] for candidate in candidates)
    assert all("delete_save" not in candidate["label"] for candidate in candidates)


def test_candidate_order_is_seeded_and_reproducible() -> None:
    campaign = normalize_bot_profile(profile())["campaigns"][0]
    first = plan_candidates(report(), campaign, state_index=2)
    second = plan_candidates(report(), campaign, state_index=2)
    assert [item["signature"] for item in first] == [item["signature"] for item in second]


def test_state_fingerprint_ignores_animation_pixels_but_tracks_ui_state(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    first.write_bytes(b"one")
    second.write_bytes(b"two")
    assert state_fingerprint(report(), first) == state_fingerprint(report(), second)

    changed = report()
    changed["ui"]["controls"][0]["text"] = "Continue"
    assert state_fingerprint(report(), first) != state_fingerprint(changed, first)


def test_bootstrap_generates_strict_profile_for_a_real_fixture(tmp_path: Path) -> None:
    project = tmp_path / "game"
    project.mkdir()
    (project / "project.godot").write_text(
        'config_version=5\n[application]\nconfig/name="Fixture"\n'
        'run/main_scene="res://main.tscn"\n[rendering]\n'
        'renderer/rendering_method="gl_compatibility"\n'
        'mapping=Object(InputEventKey)\njoy=Object(InputEventJoypadButton)\n'
        'mouse=Object(InputEventMouseButton)\n',
        encoding="utf-8",
    )
    (project / "main.tscn").write_text(
        '[gd_scene format=3]\n[node name="Main" type="Node"]\n',
        encoding="utf-8",
    )
    (project / "Fixture.csproj").write_text("<Project />\n", encoding="utf-8")

    generated, discovery = build_profile(project)

    assert generated["campaigns"][0]["renderingMethod"] == "gl_compatibility"
    assert generated["campaigns"][0]["renderingDriver"] == "opengl3"
    assert generated["campaigns"][0]["devices"] == [
        "mouse",
        "keyboard",
        "gamepad",
        "semantic",
    ]
    assert discovery["csharpProjects"] == ["Fixture.csproj"]


def test_schema_and_example_are_standard_json() -> None:
    root = Path(__file__).resolve().parents[1]
    schema = json.loads((root / "schemas" / "bot-qa-profile.schema.json").read_text())
    example = json.loads((root / "examples" / "bot-qa.profile.json").read_text())
    assert schema["properties"]["schemaVersion"]["const"] == "1.0"
    assert normalize_bot_profile(example)["campaigns"]


def test_shared_godot_harness_exposes_bot_planning_and_performance_fields() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "scripts" / "godot_input_journey.gd").read_text(encoding="utf-8")
    for token in (
        "MAX_PERFORMANCE_SAMPLES",
        "Performance.TIME_FPS",
        "Performance.RENDER_TOTAL_DRAW_CALLS_IN_FRAME",
        'record["physicalKeycode"]',
        'record["buttonIndex"]',
        'record["axisValue"]',
        '"text": _control_text(control)',
        '_result["performance"]',
    ):
        assert token in source, token
