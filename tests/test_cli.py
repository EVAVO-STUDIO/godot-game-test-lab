from __future__ import annotations

import json
from pathlib import Path

from godot_game_test_lab.cli import main


def test_inspect_command_outputs_json(tmp_path: Path, capsys) -> None:
    project = tmp_path / "game"
    project.mkdir()
    (project / "project.godot").write_text(
        '[application]\nconfig/name="CLI Fixture"\nrun/main_scene="res://main.tscn"\n'
    )
    (project / "main.tscn").write_text(
        '[gd_scene format=3]\n[node name="Main" type="Node"]\n'
    )

    exit_code = main(["inspect", str(project)])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["project_name"] == "CLI Fixture"
