from __future__ import annotations

from pathlib import Path

from godot_game_test_lab import pipeline
from godot_game_test_lab.core import CommandResult, inspect_project


def make_project(root: Path, *, csharp: bool = False) -> Path:
    root.mkdir()
    (root / "main.tscn").write_text('[gd_scene format=3]\n[node name="Main" type="Node"]\n')
    (root / "project.godot").write_text(
        '[application]\nconfig/name="Fixture"\nrun/main_scene="res://main.tscn"\n'
    )
    if csharp:
        (root / "Fixture.csproj").write_text('<Project Sdk="Godot.NET.Sdk/4.6.2" />\n')
    return root


def success(command: list[str]) -> CommandResult:
    stdout = "4.6.2.stable.mono.official" if "--version" in command else ""
    return CommandResult(command, 0, 0.01, stdout, "")


def test_inspection_detects_project_and_csharp(tmp_path: Path) -> None:
    project = make_project(tmp_path / "game", csharp=True)
    inventory = inspect_project(project)
    assert inventory.project_name == "Fixture"
    assert inventory.configured_main_scene == "res://main.tscn"
    assert inventory.csharp_projects == ["Fixture.csproj"]


def test_pipeline_runs_dotnet_import_and_boot(monkeypatch, tmp_path: Path) -> None:
    project = make_project(tmp_path / "game", csharp=True)
    monkeypatch.setattr(
        pipeline, "discover_godot_binary", lambda *args, **kwargs: Path("godot-mono")
    )
    monkeypatch.setattr(pipeline, "discover_dotnet", lambda *args, **kwargs: Path("dotnet"))
    monkeypatch.setattr(
        pipeline, "run_command", lambda command, cwd, timeout: success(list(command))
    )

    report = pipeline.validate_project_pipeline(project)

    assert report.status == "passed"
    assert report.workload == "godot-csharp"
    assert any(
        command.command[1] == "build"
        for command in report.commands
        if len(command.command) > 1
    )
    assert any("--editor" in command.command for command in report.commands)
    assert any("--quit-after" in command.command for command in report.commands)


def test_report_bundle_retains_command_logs(monkeypatch, tmp_path: Path) -> None:
    project = make_project(tmp_path / "game")
    monkeypatch.setattr(
        pipeline, "discover_godot_binary", lambda *args, **kwargs: Path("godot")
    )
    monkeypatch.setattr(
        pipeline, "run_command", lambda command, cwd, timeout: success(list(command))
    )
    report = pipeline.validate_project_pipeline(project)

    created = pipeline.write_report_bundle(report, tmp_path / "evidence")

    assert (tmp_path / "evidence" / "report.json").is_file()
    assert any(path.name.endswith(".stdout.log") for path in created)
    assert report.artifacts
