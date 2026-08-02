from __future__ import annotations

import json
from pathlib import Path

import godot_game_test_lab.engine_cli as engine_cli


def test_engine_status_fails_closed_when_no_managed_editor_exists(
    tmp_path: Path,
    capsys,
) -> None:
    exit_code = engine_cli.main(["status", "--root", str(tmp_path / "engines")])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert payload["installations"] == []


def test_engine_environment_formats_are_machine_readable(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    executable = tmp_path / "Godot_v4.6.3-stable_linux.x86_64"
    monkeypatch.setattr(
        engine_cli,
        "list_installations",
        lambda _root: [
            {
                "status": "ready",
                "version": "4.6.3",
                "flavor": "standard",
                "executable": str(executable),
            }
        ],
    )

    exit_code = engine_cli.main(["env", "--root", str(tmp_path), "--format", "json"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["GODOT_BIN"] == str(executable)
    assert payload["EVAVO_GODOT_HOME"] == str(tmp_path.resolve())
