from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from godot_game_test_lab.core import run_command


def _fake_godot(path: Path) -> Path:
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


@pytest.mark.skipif(os.name == "nt", reason="Linux command-guard regression uses a fake POSIX Godot executable.")
def test_global_guard_allows_project_cache_probe_and_rejects_external_script(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "project.godot").write_text('[application]\nconfig/name="GuardFixture"\n', encoding="utf-8")
    cache = project / ".godot" / "evavo-test-lab"
    cache.mkdir(parents=True)
    in_project_script = cache / "probe.gd"
    in_project_script.write_text("extends SceneTree\n", encoding="utf-8")
    godot = _fake_godot(tmp_path / "godot")

    allowed = run_command(
        [
            str(godot),
            "--headless",
            "--path",
            str(project),
            "--script",
            str(in_project_script),
        ],
        project,
        5,
    )
    assert allowed.exit_code == 0
    assert allowed.timed_out is False

    outside_script = tmp_path / "outside-probe.gd"
    outside_script.write_text("extends SceneTree\n", encoding="utf-8")
    with pytest.raises((PermissionError, ValueError, RuntimeError)):
        run_command(
            [
                str(godot),
                "--headless",
                "--path",
                str(project),
                "--script",
                str(outside_script),
            ],
            project,
            5,
        )
