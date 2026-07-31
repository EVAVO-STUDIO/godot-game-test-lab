from __future__ import annotations

import io
import os
import sys
from pathlib import Path

import pytest

from godot_game_test_lab.core import (
    _BoundedCollector,
    find_project_root,
    inspect_project,
    run_command,
)


def write_project(root: Path, name: str = "Fixture") -> Path:
    root.mkdir(parents=True)
    (root / "project.godot").write_text(
        'config_version=5\n[application]\n'
        f'config/name="{name}"\nrun/main_scene="res://main.tscn"\n',
        encoding="utf-8",
    )
    (root / "main.tscn").write_text(
        '[gd_scene format=3]\n[node name="Main" type="Node"]\n',
        encoding="utf-8",
    )
    return root


def test_find_project_root_ignores_generated_godot_directory(tmp_path: Path) -> None:
    project = write_project(tmp_path / "game")
    generated = project / ".godot" / "nested"
    generated.mkdir(parents=True)
    (generated / "project.godot").write_text("config_version=5\n", encoding="utf-8")

    assert find_project_root(tmp_path) == project


def test_find_project_root_requires_exact_project_when_ambiguous(tmp_path: Path) -> None:
    first = write_project(tmp_path / "first", "First")
    second = write_project(tmp_path / "second", "Second")

    with pytest.raises(ValueError, match="Multiple Godot projects"):
        find_project_root(tmp_path)

    assert find_project_root(first) == first
    assert find_project_root(second / "project.godot") == second


def test_inspection_includes_text_and_binary_scenes_but_ignores_generated_files(
    tmp_path: Path,
) -> None:
    project = write_project(tmp_path / "game")
    (project / "level.scn").write_bytes(b"GDPCfixture")
    generated = project / ".godot" / "generated"
    generated.mkdir(parents=True)
    (generated / "fake.csproj").write_text("<Project />\n", encoding="utf-8")

    inventory = inspect_project(project)

    assert inventory.scenes == ["level.scn", "main.tscn"]
    assert inventory.csharp_projects == []


def test_inspection_decodes_escaped_project_setting_without_corrupting_unicode(
    tmp_path: Path,
) -> None:
    project = write_project(tmp_path / "game")
    (project / "project.godot").write_text(
        'config_version=5\n[application]\n'
        'config/name="Caf\\u00e9 \\u6e2f"\n'
        'run/main_scene="res://main.tscn"\n',
        encoding="utf-8",
    )

    assert inspect_project(project).project_name == "Café 港"


def test_run_command_rejects_non_positive_timeout(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="timeout_seconds"):
        run_command([sys.executable, "--version"], tmp_path, 0)


def test_run_command_reports_timeout_and_returns_bounded_evidence(tmp_path: Path) -> None:
    result = run_command(
        [sys.executable, "-c", "import time; print('started', flush=True); time.sleep(30)"],
        tmp_path,
        1,
    )

    assert result.timed_out is True
    assert result.exit_code is None
    assert "started" in result.stdout


@pytest.mark.skipif(os.name == "nt", reason="POSIX-only process group assertion fixture")
def test_run_command_terminates_spawned_process_group(tmp_path: Path) -> None:
    marker = tmp_path / "child-finished"
    script = (
        "import subprocess, sys, time; "
        f"subprocess.Popen([sys.executable, '-c', \"import time, pathlib; "
        f"time.sleep(3); pathlib.Path(r'{marker}').write_text('alive')\"]); "
        "time.sleep(30)"
    )

    result = run_command([sys.executable, "-c", script], tmp_path, 1)
    assert result.timed_out is True

    import time

    time.sleep(4)
    assert not marker.exists()


def test_bounded_collector_preserves_head_and_tail_with_truncation_marker() -> None:
    collector = _BoundedCollector(io.BytesIO(b"0123456789abcdefghij"), maximum_bytes=12)
    collector.start()

    output = collector.finish()

    assert output.startswith("012345")
    assert output.endswith("efghij")
    assert "output truncated: 8 byte(s) omitted" in output
