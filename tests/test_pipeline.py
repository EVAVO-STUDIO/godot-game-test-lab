from __future__ import annotations

from pathlib import Path

from godot_game_test_lab import pipeline
from godot_game_test_lab.core import CommandResult, inspect_project


def make_project(root: Path, *, csharp: bool = False, broken_scene: bool = False) -> Path:
    root.mkdir()
    scene = (
        '[gd_scene format=3]\n[node name="One" type="Node"]\n'
        '[node name="Two" type="Node"]\n'
        if broken_scene
        else '[gd_scene format=3]\n[node name="Main" type="Node"]\n'
    )
    (root / "main.tscn").write_text(scene, encoding="utf-8")
    (root / "project.godot").write_text(
        'config_version=5\n[application]\n'
        'config/name="Fixture"\n'
        'run/main_scene="res://main.tscn"\n',
        encoding="utf-8",
    )
    if csharp:
        (root / "Fixture.csproj").write_text(
            '<Project Sdk="Godot.NET.Sdk/4.6.2" />\n', encoding="utf-8"
        )
    return root


def success(command: list[str]) -> CommandResult:
    if "--version" in command:
        stdout = "4.6.2.stable.mono.official"
    elif "--help" in command:
        stdout = "--headless --import --path --recovery-mode"
    else:
        stdout = ""
    return CommandResult(command, 0, 0.01, stdout, "")


def test_inspection_detects_project_and_csharp(tmp_path: Path) -> None:
    project = make_project(tmp_path / "game", csharp=True)
    inventory = inspect_project(project)
    assert inventory.project_name == "Fixture"
    assert inventory.configured_main_scene == "res://main.tscn"
    assert inventory.csharp_projects == ["Fixture.csproj"]


def test_pipeline_runs_audit_dotnet_authoritative_import_and_boot(
    monkeypatch, tmp_path: Path
) -> None:
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
    assert report.schema_version == "2.1"
    assert report.workload == "godot-csharp"
    assert report.integrity is not None
    assert report.integrity.status == "passed"
    assert any(
        command.command[1] == "build"
        for command in report.commands
        if len(command.command) > 1
    )
    assert any("--import" in command.command for command in report.commands)
    assert not any("--editor" in command.command for command in report.commands)
    assert any("--quit-after" in command.command for command in report.commands)


def test_pipeline_preserves_static_integrity_failure(monkeypatch, tmp_path: Path) -> None:
    project = make_project(tmp_path / "game", broken_scene=True)
    monkeypatch.setattr(
        pipeline, "discover_godot_binary", lambda *args, **kwargs: Path("godot")
    )
    monkeypatch.setattr(
        pipeline, "run_command", lambda command, cwd, timeout: success(list(command))
    )

    report = pipeline.validate_project_pipeline(project)

    assert report.status == "failed"
    assert report.integrity is not None
    assert report.integrity.errors > 0
    assert any("Static integrity audit" in finding for finding in report.findings)


def test_failed_import_runs_recovery_diagnostic(monkeypatch, tmp_path: Path) -> None:
    project = make_project(tmp_path / "game")
    monkeypatch.setattr(
        pipeline, "discover_godot_binary", lambda *args, **kwargs: Path("godot")
    )

    def execute(command, cwd, timeout):
        values = list(command)
        if "--version" in values:
            return success(values)
        if "--recovery-mode" in values:
            return success(values)
        if "--import" in values:
            return CommandResult(values, 1, 0.01, "", "ERROR: plugin startup failed")
        return success(values)

    monkeypatch.setattr(pipeline, "run_command", execute)

    report = pipeline.validate_project_pipeline(project)

    assert report.status == "failed"
    assert any("--recovery-mode" in command.command for command in report.commands)
    assert any("editor plugin" in diagnostic for diagnostic in report.diagnostics)
    assert not any("--quit-after" in command.command for command in report.commands)


def test_report_bundle_retains_integrity_command_and_engine_logs(
    monkeypatch, tmp_path: Path
) -> None:
    project = make_project(tmp_path / "game")
    log_directory = tmp_path / "evidence" / "engine"
    monkeypatch.setattr(
        pipeline, "discover_godot_binary", lambda *args, **kwargs: Path("godot")
    )

    def execute(command, cwd, timeout):
        values = list(command)
        if "--log-file" in values:
            log_path = Path(values[values.index("--log-file") + 1])
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text("engine log\n", encoding="utf-8")
        return success(values)

    monkeypatch.setattr(pipeline, "run_command", execute)
    report = pipeline.validate_project_pipeline(project, log_directory=log_directory)

    created = pipeline.write_report_bundle(report, tmp_path / "evidence")

    assert (tmp_path / "evidence" / "report.json").is_file()
    assert (tmp_path / "evidence" / "integrity-report.json").is_file()
    assert any(path.name.endswith(".stdout.log") for path in created)
    assert any(path.endswith("godot-import.log") for path in report.artifacts)


def test_pipeline_blocks_binary_without_required_editor_capabilities(
    monkeypatch, tmp_path: Path
) -> None:
    project = make_project(tmp_path / "game")
    monkeypatch.setattr(
        pipeline, "discover_godot_binary", lambda *args, **kwargs: Path("godot")
    )

    def execute(command, cwd, timeout):
        values = list(command)
        if "--version" in values:
            return CommandResult(values, 0, 0.01, "4.6.2.stable.official", "")
        if "--help" in values:
            return CommandResult(values, 0, 0.01, "--path --headless", "")
        raise AssertionError(f"unexpected execution: {values}")

    monkeypatch.setattr(pipeline, "run_command", execute)

    report = pipeline.validate_project_pipeline(project)

    assert report.status == "blocked"
    assert any("missing required editor capabilities" in value for value in report.findings)
    assert not any("--import" in command.command for command in report.commands)


def test_pipeline_rejects_later_major_by_default(monkeypatch, tmp_path: Path) -> None:
    project = make_project(tmp_path / "game")
    monkeypatch.setattr(
        pipeline, "discover_godot_binary", lambda *args, **kwargs: Path("godot")
    )

    def execute(command, cwd, timeout):
        values = list(command)
        if "--version" in values:
            return CommandResult(values, 0, 0.01, "5.0.0.stable.official", "")
        if "--help" in values:
            return CommandResult(
                values,
                0,
                0.01,
                "--headless --import --path --recovery-mode",
                "",
            )
        raise AssertionError(f"unexpected execution: {values}")

    monkeypatch.setattr(pipeline, "run_command", execute)

    report = pipeline.validate_project_pipeline(project)

    assert report.status == "blocked"
    assert any("within the same major" in value for value in report.findings)


def test_pipeline_can_explicitly_allow_later_major(monkeypatch, tmp_path: Path) -> None:
    project = make_project(tmp_path / "game")
    monkeypatch.setattr(
        pipeline, "discover_godot_binary", lambda *args, **kwargs: Path("godot")
    )

    def execute(command, cwd, timeout):
        values = list(command)
        if "--version" in values:
            return CommandResult(values, 0, 0.01, "5.0.0.stable.official", "")
        if "--help" in values:
            return CommandResult(
                values,
                0,
                0.01,
                "--headless --import --path --recovery-mode",
                "",
            )
        return success(values)

    monkeypatch.setattr(pipeline, "run_command", execute)

    report = pipeline.validate_project_pipeline(project, allow_major_upgrade=True)

    assert report.status == "passed"
    assert any("--import" in command.command for command in report.commands)


def test_failed_csharp_build_prevents_import(monkeypatch, tmp_path: Path) -> None:
    project = make_project(tmp_path / "game", csharp=True)
    monkeypatch.setattr(
        pipeline, "discover_godot_binary", lambda *args, **kwargs: Path("godot-mono")
    )
    monkeypatch.setattr(pipeline, "discover_dotnet", lambda *args, **kwargs: Path("dotnet"))

    def execute(command, cwd, timeout):
        values = list(command)
        if values[0] == "dotnet" and "build" in values:
            return CommandResult(values, 1, 0.01, "", "Build FAILED")
        return success(values)

    monkeypatch.setattr(pipeline, "run_command", execute)

    report = pipeline.validate_project_pipeline(project)

    assert report.status == "failed"
    assert any("C# build" in value for value in report.diagnostics)
    assert not any("--import" in command.command for command in report.commands)


def test_static_safety_blocker_withholds_engine_execution(monkeypatch, tmp_path: Path) -> None:
    project = make_project(tmp_path / "game")
    (project / "main.tscn").write_text(
        '[gd_scene format=3]\n'
        '[ext_resource type="Script" path="../../outside.gd" id="1"]\n'
        '[node name="Main" type="Node"]\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        pipeline, "discover_godot_binary", lambda *args, **kwargs: Path("godot")
    )
    monkeypatch.setattr(
        pipeline, "run_command", lambda command, cwd, timeout: success(list(command))
    )

    report = pipeline.validate_project_pipeline(project)

    assert report.status == "failed"
    assert any("withheld" in value for value in report.diagnostics)
    assert not any("--import" in command.command for command in report.commands)


def test_recovery_failure_is_preserved_as_a_command_failure(
    monkeypatch, tmp_path: Path
) -> None:
    project = make_project(tmp_path / "game")
    monkeypatch.setattr(
        pipeline, "discover_godot_binary", lambda *args, **kwargs: Path("godot")
    )

    def execute(command, cwd, timeout):
        values = list(command)
        if "--version" in values or "--help" in values:
            return success(values)
        if "--import" in values:
            return CommandResult(values, 1, 0.01, "", "ERROR: parse failed")
        return success(values)

    monkeypatch.setattr(pipeline, "run_command", execute)

    report = pipeline.validate_project_pipeline(project)

    assert report.status == "failed"
    assert any("recovery-mode import exited" in value for value in report.findings)
    assert any("also failed" in value for value in report.diagnostics)


def test_discovery_prefers_highest_managed_godot_version(monkeypatch, tmp_path: Path) -> None:
    tool_root = tmp_path / "tools"
    tool_root.mkdir()
    older = tool_root / "Godot_v4.6.2-stable_linux.x86_64"
    newer = tool_root / "Godot_v4.6.3-stable_linux.x86_64"
    unrelated = tool_root / "godot-lab"
    for path in (older, newer, unrelated):
        path.write_text("#!/bin/sh\n", encoding="utf-8")
        path.chmod(0o755)
    monkeypatch.setenv("PATH", str(tool_root))
    monkeypatch.delenv("GODOT_BIN", raising=False)
    monkeypatch.delenv("GODOT_MONO_BIN", raising=False)
    monkeypatch.setattr(pipeline, "_which", lambda _name: None)

    assert pipeline.discover_godot_binary() == newer.resolve()


def test_doctor_rejects_standard_editor_as_mono(monkeypatch, tmp_path: Path) -> None:
    standard = tmp_path / "Godot_v4.6.3-stable_win64_console.exe"
    standard.write_text("fixture", encoding="utf-8")
    monkeypatch.setattr(
        pipeline,
        "discover_godot_binary",
        lambda *args, **kwargs: standard,
    )
    monkeypatch.setattr(pipeline, "discover_dotnet", lambda *args, **kwargs: None)
    monkeypatch.setattr(pipeline, "_which", lambda _name: None)

    def fake_run(command, cwd, timeout):
        output = (
            "Godot Engine v4.6.3.stable.official"
            if "--version" in command
            else "--headless --import --path --recovery-mode --write-movie"
        )
        return CommandResult(list(command), 0, 0.01, output, "")

    monkeypatch.setattr(pipeline, "run_command", fake_run)

    payload = pipeline.doctor_payload(godot_executable=standard)

    assert payload["godot"]["editorCompatible"] is True
    assert payload["godotMono"]["editorCompatible"] is False
    assert payload["godotMono"]["flavorCompatible"] is False
