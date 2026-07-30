from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str):
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.replace(".py", ""), path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_profile_v2_accepts_keyboard_mouse_and_gamepad_journeys(
    tmp_path: Path,
) -> None:
    module = load_script("read_linux_sandbox_profile.py")
    profile = tmp_path / "profile.json"
    profile.write_text(
        json.dumps(
            {
                "schemaVersion": "2.0",
                "minimumGodotVersion": "4.6.2",
                "visual": {
                    "required": True,
                    "scene": "res://main.tscn",
                    "frames": 180,
                    "fps": 30,
                    "width": 960,
                    "height": 540,
                    "renderingMethod": "gl_compatibility",
                    "userArguments": [],
                },
                "export": {"required": False, "preset": ""},
                "journeys": [
                    {
                        "id": "keyboard-menu",
                        "device": "keyboard_mouse",
                        "requiredActions": [
                            {"name": "ui_accept", "devices": ["keyboard"]}
                        ],
                        "steps": [
                            {
                                "type": "key_tap",
                                "physicalKeycode": 4194309,
                                "holdFrames": 2,
                            },
                            {"type": "checkpoint", "id": "accepted"},
                        ],
                        "assertions": [{"type": "scene_loaded"}],
                    },
                    {
                        "id": "gamepad-menu",
                        "device": "gamepad",
                        "requiredActions": [
                            {"name": "ui_accept", "devices": ["gamepad"]}
                        ],
                        "steps": [
                            {"type": "joy_button_tap", "buttonIndex": 0},
                            {"type": "checkpoint", "id": "accepted"},
                        ],
                    },
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    value = module.read_profile(profile)

    assert value["schemaVersion"] == "2.0"
    assert [journey["id"] for journey in value["journeys"]] == [
        "keyboard-menu",
        "gamepad-menu",
    ]
    assert value["journeys"][1]["requiredActions"][0]["devices"] == [
        "gamepad"
    ]


def test_profile_v1_rejects_interactive_journeys(tmp_path: Path) -> None:
    module = load_script("read_linux_sandbox_profile.py")
    profile = tmp_path / "profile.json"
    profile.write_text(
        json.dumps(
            {
                "schemaVersion": "1.0",
                "journeys": [{"id": "forbidden", "steps": []}],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(module.ProfileError, match="schemaVersion 2.0"):
        module.read_profile(profile)


def test_profile_rejects_unbounded_or_unsafe_journey_steps(
    tmp_path: Path,
) -> None:
    module = load_script("read_linux_sandbox_profile.py")
    profile = tmp_path / "profile.json"
    profile.write_text(
        json.dumps(
            {
                "schemaVersion": "2.0",
                "journeys": [
                    {
                        "id": "unsafe",
                        "steps": [
                            {
                                "type": "checkpoint",
                                "id": "../escape",
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(module.ProfileError, match="safe lowercase identifier"):
        module.read_profile(profile)


def test_agent_runner_and_godot_harness_preserve_truth_boundaries() -> None:
    runner = (ROOT / "scripts/run_agent_godot_qa.py").read_text(encoding="utf-8")
    harness = (ROOT / "scripts/godot_input_journey.gd").read_text(encoding="utf-8")

    for marker in [
        "syntheticKeyboardMouseInput",
        "syntheticGamepadEvents",
        '"physicalUsbGamepad": False',
        "visual-ux-review.json",
        "blackdetect",
        "freezedetect",
        "Input.parse_input_event",
        "InputEventJoypadButton",
        "InputEventMouseButton",
        "InputEventKey",
        "requiredActions",
        "overlappingInteractivePairs",
        "outOfBoundsInteractive",
    ]:
        assert marker in runner or marker in harness

    assert "--privileged" not in runner
    assert "/dev/uinput" not in runner
