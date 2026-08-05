from __future__ import annotations

import importlib.util
import json
import stat
import subprocess
from pathlib import Path

import pytest

MODULE_PATH = (
    Path(__file__).parents[1]
    / "src"
    / "godot_game_test_lab"
    / "resilient_import.py"
)
SPEC = importlib.util.spec_from_file_location("resilient_import", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
ResilientImportError = MODULE.ResilientImportError
run_resilient_import = MODULE.run_resilient_import


def _git(path: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(path), *args],
        check=True,
        text=True,
        capture_output=True,
    )
    return result.stdout.strip()


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    (project / "project.godot").write_text("[application]\nconfig/name=\"Fixture\"\n")
    _git(project, "init", "-b", "main")
    _git(project, "config", "user.name", "EVAVO Test")
    _git(project, "config", "user.email", "test@example.invalid")
    _git(project, "add", "project.godot")
    _git(project, "commit", "-m", "fixture")
    return project


def _engine(tmp_path: Path) -> Path:
    engine = tmp_path / "fake-godot.py"
    engine.write_text(
        """#!/usr/bin/env python3
import json, os, pathlib, sys
if '--version' in sys.argv:
    print('4.6.2.stable.official.fixture')
    raise SystemExit(0)
project = pathlib.Path(sys.argv[sys.argv.index('--path') + 1])
log = pathlib.Path(os.environ['FAKE_GODOT_LOG'])
with log.open('a', encoding='utf-8') as handle:
    handle.write(json.dumps(sys.argv[1:]) + '\\n')
if os.environ.get('FAKE_GODOT_MUTATE') == '1':
    (project / 'project.godot').write_text('mutated')
print('import complete')
""",
        encoding="utf-8",
    )
    engine.chmod(engine.stat().st_mode | stat.S_IXUSR)
    return engine


def test_runs_forward_plus_and_compatibility_with_exact_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path)
    engine = _engine(tmp_path)
    log = tmp_path / "engine-args.jsonl"
    monkeypatch.setenv("FAKE_GODOT_LOG", str(log))
    receipt = run_resilient_import(
        project=project,
        godot=engine,
        artifacts=tmp_path / "evidence",
        expected_version="4.6.2",
        renderers=["forward_plus", "compatibility"],
        timeout_seconds=30,
        maximum_output_bytes=1024 * 1024,
    )
    assert receipt["status"] == "passed"
    assert receipt["source"]["head"] == _git(project, "rev-parse", "HEAD")
    assert [item["renderer"] for item in receipt["passes"]] == [
        "forward_plus",
        "compatibility",
    ]
    commands = [json.loads(line) for line in log.read_text().splitlines()]
    assert ["--rendering-method", "forward_plus"] in [
        command[command.index("--rendering-method") : command.index("--rendering-method") + 2]
        for command in commands
    ]
    assert any("gl_compatibility" in command and "opengl3" in command for command in commands)
    assert Path(receipt["evidenceRoot"], "summary.json").is_file()


def test_rejects_evidence_inside_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = _project(tmp_path)
    engine = _engine(tmp_path)
    monkeypatch.setenv("FAKE_GODOT_LOG", str(tmp_path / "log"))
    with pytest.raises(ResilientImportError, match="outside target source"):
        run_resilient_import(
            project=project,
            godot=engine,
            artifacts=project / "evidence",
            expected_version="4.6.2",
            renderers=["forward_plus"],
            timeout_seconds=30,
            maximum_output_bytes=1024 * 1024,
        )


def test_detects_tracked_source_mutation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = _project(tmp_path)
    engine = _engine(tmp_path)
    monkeypatch.setenv("FAKE_GODOT_LOG", str(tmp_path / "log"))
    monkeypatch.setenv("FAKE_GODOT_MUTATE", "1")
    with pytest.raises(ResilientImportError, match="changed tracked target source"):
        run_resilient_import(
            project=project,
            godot=engine,
            artifacts=tmp_path / "evidence",
            expected_version="4.6.2",
            renderers=["forward_plus"],
            timeout_seconds=30,
            maximum_output_bytes=1024 * 1024,
        )


def test_rejects_engine_version_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = _project(tmp_path)
    engine = _engine(tmp_path)
    monkeypatch.setenv("FAKE_GODOT_LOG", str(tmp_path / "log"))
    with pytest.raises(ResilientImportError, match="version mismatch"):
        run_resilient_import(
            project=project,
            godot=engine,
            artifacts=tmp_path / "evidence",
            expected_version="4.7.1",
            renderers=["compatibility"],
            timeout_seconds=30,
            maximum_output_bytes=1024 * 1024,
        )


def _dotnet(tmp_path: Path) -> Path:
    executable = tmp_path / "fake-dotnet.py"
    executable.write_text(
        """#!/usr/bin/env python3
import json, os, pathlib, sys
log = pathlib.Path(os.environ['FAKE_DOTNET_LOG'])
log.write_text(json.dumps(sys.argv[1:]) + '\\n', encoding='utf-8')
print('dotnet build complete')
""",
        encoding="utf-8",
    )
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    return executable


def _add_cs_project(project: Path, *, locked: bool) -> None:
    (project / "Fixture.csproj").write_text(
        '<Project Sdk="Godot.NET.Sdk/4.6.2"><PropertyGroup /></Project>\n',
        encoding="utf-8",
    )
    if locked:
        (project / "packages.lock.json").write_text(
            '{"version":1,"dependencies":{}}\n', encoding="utf-8"
        )
    _git(project, "add", "Fixture.csproj")
    if locked:
        _git(project, "add", "packages.lock.json")
    _git(project, "commit", "-m", "add C# fixture")


@pytest.mark.parametrize("locked", [False, True])
def test_dotnet_build_uses_locked_mode_only_for_owned_lockfile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    locked: bool,
) -> None:
    project = _project(tmp_path)
    _add_cs_project(project, locked=locked)
    engine = _engine(tmp_path)
    dotnet = _dotnet(tmp_path)
    monkeypatch.setenv("FAKE_GODOT_LOG", str(tmp_path / "godot-log"))
    monkeypatch.setenv("FAKE_DOTNET_LOG", str(tmp_path / "dotnet-log"))
    receipt = run_resilient_import(
        project=project,
        godot=engine,
        artifacts=tmp_path / "evidence",
        expected_version="4.6.2",
        renderers=["forward_plus"],
        timeout_seconds=30,
        maximum_output_bytes=1024 * 1024,
        dotnet=dotnet,
    )
    build = receipt["dotnetBuild"]
    assert build["lockMode"] is locked
    assert ("--locked-mode" in build["command"]) is locked


def test_rejects_symlinked_engine_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path)
    engine = _engine(tmp_path)
    engine_link = tmp_path / "godot-link"
    engine_link.symlink_to(engine)
    monkeypatch.setenv("FAKE_GODOT_LOG", str(tmp_path / "log"))
    with pytest.raises(ResilientImportError, match="may not be a symlink"):
        run_resilient_import(
            project=project,
            godot=engine_link,
            artifacts=tmp_path / "evidence",
            expected_version="4.6.2",
            renderers=["forward_plus"],
            timeout_seconds=30,
            maximum_output_bytes=1024 * 1024,
        )
