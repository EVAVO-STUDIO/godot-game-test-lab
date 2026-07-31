from __future__ import annotations

from pathlib import Path

import pytest

from godot_game_test_lab.command_guard import (
    normalize_godot_scene_command,
    validate_scene_argument,
)


def make_project(root: Path) -> Path:
    root.mkdir()
    (root / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    (root / "scenes").mkdir()
    (root / "scenes" / "qa.tscn").write_text(
        '[gd_scene format=3]\n[node name="QA" type="Node"]\n',
        encoding="utf-8",
    )
    return root


def test_scene_option_becomes_final_positional_project_argument(tmp_path: Path) -> None:
    project = make_project(tmp_path / "game")
    command = [
        "godot",
        "--path",
        str(project),
        "--quit-after",
        "120",
        "--scene",
        "res://scenes/qa.tscn",
    ]

    normalized = normalize_godot_scene_command(command, project)

    assert "--scene" not in normalized
    assert normalized[-1] == "res://scenes/qa.tscn"


def test_scene_is_inserted_before_user_arguments(tmp_path: Path) -> None:
    project = make_project(tmp_path / "game")
    command = [
        "godot",
        "--path",
        str(project),
        "--scene=res://scenes/qa.tscn",
        "--",
        "--compiled-level=bunker_01",
    ]

    normalized = normalize_godot_scene_command(command, project)

    delimiter = normalized.index("--")
    assert normalized[delimiter - 1] == "res://scenes/qa.tscn"
    assert normalized[delimiter + 1] == "--compiled-level=bunker_01"


def test_unrelated_commands_are_unchanged(tmp_path: Path) -> None:
    commands = [
        ["python", "-m", "pytest"],
        ["other-tool", "--scene", "example"],
    ]
    for command in commands:
        assert normalize_godot_scene_command(command, tmp_path) == command


def test_scene_validation_rejects_escape_missing_and_non_scene(tmp_path: Path) -> None:
    project = make_project(tmp_path / "game")

    for value in (
        "../outside.tscn",
        "res://../outside.tscn",
        "res://scenes/missing.tscn",
        "res://project.godot",
    ):
        with pytest.raises(ValueError):
            validate_scene_argument(value, project)


def test_multiple_scene_selectors_fail_closed(tmp_path: Path) -> None:
    project = make_project(tmp_path / "game")
    with pytest.raises(ValueError, match="exactly one scene"):
        normalize_godot_scene_command(
            [
                "godot",
                "--path",
                str(project),
                "--scene",
                "res://scenes/qa.tscn",
                "--scene=res://scenes/qa.tscn",
            ],
            project,
        )
