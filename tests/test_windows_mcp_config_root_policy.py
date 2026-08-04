from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "Write-GodotLabMcpConfig.ps1"
PWSH = shutil.which("pwsh")

pytestmark = pytest.mark.skipif(PWSH is None, reason="pwsh is unavailable")


def _quote(value: Path | str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _run_writer(
    *,
    lab: Path,
    roots: list[Path],
    evidence: Path,
    engine: Path,
    output: Path | None,
    allow_noninteractive: bool = False,
    no_auto_provision: bool = False,
) -> subprocess.CompletedProcess[str]:
    root_list = ", ".join(_quote(root) for root in roots)
    arguments = [
        f"-LabRoot {_quote(lab)}",
        f"-PythonExecutable {_quote(Path(sys.executable))}",
        f"-AllowedTargetRoots @({root_list})",
        f"-EvidenceRoot {_quote(evidence)}",
        f"-EngineRoot {_quote(engine)}",
    ]
    if output is not None:
        arguments.append(f"-OutputPath {_quote(output)}")
    if allow_noninteractive:
        arguments.append("-AllowNonInteractive")
    if no_auto_provision:
        arguments.append("-NoAutoProvision")
    command = (
        "$ErrorActionPreference = 'Stop'; "
        f"& {_quote(SCRIPT)} "
        + " ".join(arguments)
    )
    return subprocess.run(
        [
            str(PWSH),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            command,
        ],
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )


def _fixture_roots(tmp_path: Path) -> tuple[Path, Path, Path]:
    lab = tmp_path / "lab"
    target_a = tmp_path / "targets-a"
    target_b = tmp_path / "targets-b"
    for path in (lab, target_a, target_b):
        path.mkdir()
    return lab, target_a, target_b


def test_writer_rejects_evidence_overlap_before_directory_creation(
    tmp_path: Path,
) -> None:
    lab, target, _ = _fixture_roots(tmp_path)
    evidence = target / "evidence"
    engine = tmp_path / "engines"
    output = evidence / "mcp" / "godot-lab-mcp.json"

    result = _run_writer(
        lab=lab,
        roots=[target],
        evidence=evidence,
        engine=engine,
        output=output,
    )

    assert result.returncode != 0
    assert "EvidenceRoot must remain disjoint" in (result.stderr + result.stdout)
    assert not evidence.exists()
    assert not engine.exists()


def test_writer_rejects_engine_overlap_before_directory_creation(
    tmp_path: Path,
) -> None:
    lab, target, _ = _fixture_roots(tmp_path)
    evidence = tmp_path / "evidence"
    engine = lab / "engines"
    output = evidence / "mcp" / "godot-lab-mcp.json"

    result = _run_writer(
        lab=lab,
        roots=[target],
        evidence=evidence,
        engine=engine,
        output=output,
    )

    assert result.returncode != 0
    assert "EngineRoot must remain disjoint" in (result.stderr + result.stdout)
    assert not evidence.exists()
    assert not engine.exists()


def test_writer_rejects_output_escape_before_directory_creation(
    tmp_path: Path,
) -> None:
    lab, target, _ = _fixture_roots(tmp_path)
    evidence = tmp_path / "evidence"
    engine = tmp_path / "engines"
    output = tmp_path / "outside" / "godot-lab-mcp.json"

    result = _run_writer(
        lab=lab,
        roots=[target],
        evidence=evidence,
        engine=engine,
        output=output,
    )

    assert result.returncode != 0
    assert "OutputPath must remain strictly beneath EvidenceRoot" in (
        result.stderr + result.stdout
    )
    assert not evidence.exists()
    assert not engine.exists()
    assert not output.parent.exists()


def test_writer_preserves_all_roots_and_only_replaces_generated_snippets(
    tmp_path: Path,
) -> None:
    lab, target_a, target_b = _fixture_roots(tmp_path)
    evidence = tmp_path / "evidence"
    engine = tmp_path / "engines"
    output = evidence / "mcp" / "godot-lab-mcp.json"

    first = _run_writer(
        lab=lab,
        roots=[target_a, target_b],
        evidence=evidence,
        engine=engine,
        output=output,
        allow_noninteractive=True,
        no_auto_provision=True,
    )
    assert first.returncode == 0, first.stderr or first.stdout

    payload = json.loads(output.read_text(encoding="utf-8"))
    server = payload["mcpServers"]["evavo-godot-game-test-lab"]
    args = server["args"]
    assert server["command"] == str(Path(sys.executable).resolve())
    assert args.count("--allowed-root") == 2
    allowed = [
        args[index + 1]
        for index, value in enumerate(args)
        if value == "--allowed-root"
    ]
    assert allowed == [str(target_a.resolve()), str(target_b.resolve())]
    assert "--allow-noninteractive" in args
    assert "--no-auto-provision" in args
    assert args[args.index("--evidence-root") + 1] == str(evidence.resolve())
    assert args[args.index("--engine-root") + 1] == str(engine.resolve())

    second = _run_writer(
        lab=lab,
        roots=[target_a, target_b],
        evidence=evidence,
        engine=engine,
        output=output,
        allow_noninteractive=True,
        no_auto_provision=True,
    )
    assert second.returncode == 0, second.stderr or second.stdout

    custom = {"mcpServers": payload["mcpServers"], "unrelated": {"keep": True}}
    output.write_text(json.dumps(custom, indent=2) + "\n", encoding="utf-8")
    before = output.read_bytes()
    rejected = _run_writer(
        lab=lab,
        roots=[target_a, target_b],
        evidence=evidence,
        engine=engine,
        output=output,
        allow_noninteractive=True,
        no_auto_provision=True,
    )
    assert rejected.returncode != 0
    assert "Refusing to overwrite it" in (rejected.stderr + rejected.stdout)
    assert output.read_bytes() == before
