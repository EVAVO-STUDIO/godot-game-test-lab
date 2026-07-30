from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str):
    path = ROOT / "scripts" / name
    module_name = name.replace(".py", "")
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_profile_reader_accepts_governed_retro_fps_journey(
    tmp_path: Path,
) -> None:
    module = load_script("read_linux_sandbox_profile.py")
    profile = tmp_path / "profile.json"
    profile.write_text(
        json.dumps(
            {
                "schemaVersion": "1.0",
                "projectSubpath": ".",
                "minimumGodotVersion": "4.6.2",
                "engineFlavor": "standard",
                "visual": {
                    "required": True,
                    "scene": "res://main.tscn",
                    "frames": 360,
                    "fps": 30,
                    "width": 1280,
                    "height": 720,
                    "renderingMethod": "gl_compatibility",
                    "userArguments": ["--compiled-level=bunker_01"],
                },
                "export": {
                    "required": True,
                    "preset": "Linux Desktop",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    value = module.read_profile(profile)

    assert value["visual"]["userArguments"] == [
        "--compiled-level=bunker_01"
    ]
    assert value["export"]["preset"] == "Linux Desktop"


def test_profile_reader_rejects_duplicate_keys(tmp_path: Path) -> None:
    module = load_script("read_linux_sandbox_profile.py")
    profile = tmp_path / "profile.json"
    profile.write_text(
        '{"schemaVersion":"1.0","schemaVersion":"1.0"}\n',
        encoding="utf-8",
    )

    with pytest.raises(module.ProfileError, match="Duplicate JSON key"):
        module.read_profile(profile)


def test_profile_reader_rejects_traversal_and_arguments(
    tmp_path: Path,
) -> None:
    module = load_script("read_linux_sandbox_profile.py")
    profile = tmp_path / "profile.json"
    profile.write_text(
        json.dumps(
            {
                "schemaVersion": "1.0",
                "projectSubpath": "../escape",
                "visual": {"userArguments": ["not-prefixed"]},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(module.ProfileError, match="projectSubpath"):
        module.read_profile(profile)


def test_profiled_runner_rejects_ambiguous_arguments_and_scene() -> None:
    module = load_script("run_profiled_linux_sandbox.py")

    with pytest.raises(module.JourneyError, match="JSON array"):
        module.parse_user_arguments('{"argument":"--bad"}')
    with pytest.raises(module.JourneyError, match="--prefixed"):
        module.parse_user_arguments('["compiled-level=bunker_01"]')
    with pytest.raises(module.JourneyError, match="canonical res://"):
        module.safe_scene("res://../outside.tscn")


def test_reusable_workflow_uses_caller_context_and_exact_shas() -> None:
    workflow_path = (
        ROOT / ".github/workflows/reusable-godot-linux-sandbox.yml"
    )
    workflow = workflow_path.read_text(encoding="utf-8")
    entrypoint = (
        ROOT / "scripts/linux-sandbox-entrypoint.sh"
    ).read_text(encoding="utf-8")
    runner = (
        ROOT / "scripts/run_profiled_linux_sandbox.py"
    ).read_text(encoding="utf-8")

    for marker in [
        "workflow_call:",
        "target_sha must equal the caller workflow SHA",
        "lfs: true",
        "repository: EVAVO-STUDIO/godot-game-test-lab",
        "persist-credentials: false",
        "--network none",
        "--read-only",
        "--cap-drop ALL",
        "--security-opt no-new-privileges",
        "--memory-swap 10g",
        "EVAVO_VISUAL_ARGUMENTS_JSON",
        "agent-summary.json",
    ]:
        assert marker in workflow

    assert "EVAVO_GODOT_LAB_READ_TOKEN" not in workflow
    assert "docker.sock" not in workflow
    assert "--privileged" not in workflow
    assert "run_profiled_linux_sandbox.py" in entrypoint
    assert "--display-driver" in runner
    assert "--write-movie" in runner
    assert "frame-%02d.png" in runner
    assert "contact-sheet.png" in runner
