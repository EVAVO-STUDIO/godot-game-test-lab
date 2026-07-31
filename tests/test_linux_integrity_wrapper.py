from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "run_agent_godot_qa_with_integrity.py"
)


def load_wrapper() -> ModuleType:
    spec = importlib.util.spec_from_file_location("integrity_wrapper", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_project(root: Path, *, broken_scene: bool = False) -> Path:
    root.mkdir(parents=True)
    scene = (
        '[gd_scene format=3]\n[node name="One" type="Node"]\n'
        '[node name="Two" type="Node"]\n'
        if broken_scene
        else '[gd_scene format=3]\n[node name="Main" type="Node"]\n'
    )
    (root / "main.tscn").write_text(scene, encoding="utf-8")
    (root / "project.godot").write_text(
        'config_version=5\n[application]\n'
        'config/name="Wrapper Fixture"\n'
        'run/main_scene="res://main.tscn"\n',
        encoding="utf-8",
    )
    return root


def write_canonical_runner(
    path: Path,
    artifacts: Path,
    *,
    exit_code: int = 0,
    marker: Path | None = None,
) -> None:
    marker_statement = (
        f"Path({str(marker)!r}).write_text('yes', encoding='utf-8')\n"
        if marker is not None
        else ""
    )
    path.write_text(
        "from __future__ import annotations\n"
        "import json\n"
        "from pathlib import Path\n"
        f"ROOT = Path({str(artifacts)!r})\n"
        "def main():\n"
        "    ROOT.mkdir(parents=True, exist_ok=True)\n"
        f"    {marker_statement.rstrip()}\n"
        "    for name in ('sandbox-report.json', 'agent-summary.json'):\n"
        "        (ROOT / name).write_text(json.dumps({\n"
        "            'schemaVersion': 'fixture',\n"
        "            'status': 'passed',\n"
        "            'findings': [],\n"
        "            'artifacts': [],\n"
        "            'checks': [],\n"
        "        }) + '\\n', encoding='utf-8')\n"
        f"    return {exit_code}\n",
        encoding="utf-8",
    )


def arguments(project: Path, artifacts: Path) -> list[str]:
    return [
        str(project),
        "--artifacts",
        str(artifacts),
        "--project-subpath",
        ".",
    ]


def test_valid_project_runs_canonical_runner_and_merges_integrity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    wrapper = load_wrapper()
    project = make_project(tmp_path / "game")
    artifacts = tmp_path / "artifacts"
    canonical = tmp_path / "canonical.py"
    write_canonical_runner(canonical, artifacts)
    monkeypatch.setattr(wrapper, "CANONICAL_RUNNER", canonical)

    result = wrapper.main(arguments(project, artifacts))

    assert result == 0
    summary = json.loads((artifacts / "agent-summary.json").read_text(encoding="utf-8"))
    sandbox = json.loads((artifacts / "sandbox-report.json").read_text(encoding="utf-8"))
    assert summary["status"] == "passed"
    assert summary["integrity"]["status"] == "passed"
    assert summary["checks"][0]["id"] == "static-project-integrity"
    assert sandbox["integrity"]["status"] == "passed"
    assert (artifacts / "integrity-report.json").is_file()


def test_static_errors_run_canonical_runner_but_fail_final_policy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    wrapper = load_wrapper()
    project = make_project(tmp_path / "game", broken_scene=True)
    artifacts = tmp_path / "artifacts"
    canonical = tmp_path / "canonical.py"
    marker = tmp_path / "canonical-ran"
    write_canonical_runner(canonical, artifacts, marker=marker)
    monkeypatch.setattr(wrapper, "CANONICAL_RUNNER", canonical)

    result = wrapper.main(arguments(project, artifacts))

    assert result == 2
    assert marker.is_file()
    summary = json.loads((artifacts / "agent-summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "failed"
    assert summary["integrity"]["executionAllowed"] is True
    assert summary["integrity"]["errors"] > 0


@pytest.mark.skipif(os.name == "nt", reason="Windows symlink creation requires privileges")
def test_execution_blocker_skips_canonical_runner_and_writes_blocked_summary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    wrapper = load_wrapper()
    project = make_project(tmp_path / "game")
    outside = tmp_path / "outside.gd"
    outside.write_text("extends Node\n", encoding="utf-8")
    (project / "escape.gd").symlink_to(outside)
    artifacts = tmp_path / "artifacts"
    canonical = tmp_path / "canonical.py"
    marker = tmp_path / "canonical-ran"
    write_canonical_runner(canonical, artifacts, marker=marker)
    monkeypatch.setattr(wrapper, "CANONICAL_RUNNER", canonical)

    result = wrapper.main(arguments(project, artifacts))

    assert result == 2
    assert not marker.exists()
    summary = json.loads((artifacts / "agent-summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "blocked"
    assert "filesystem.symlink_escape" in summary["integrity"]["executionBlockers"]


def test_canonical_failure_is_retained_in_summary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    wrapper = load_wrapper()
    project = make_project(tmp_path / "game")
    artifacts = tmp_path / "artifacts"
    canonical = tmp_path / "canonical.py"
    write_canonical_runner(canonical, artifacts, exit_code=7)
    monkeypatch.setattr(wrapper, "CANONICAL_RUNNER", canonical)

    result = wrapper.main(arguments(project, artifacts))

    assert result == 2
    summary = json.loads((artifacts / "agent-summary.json").read_text(encoding="utf-8"))
    assert summary["runnerExitCode"] == 7
    assert summary["status"] == "failed"


def test_invalid_warning_policy_fails_closed_with_machine_readable_gate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    wrapper = load_wrapper()
    project = make_project(tmp_path / "game")
    artifacts = tmp_path / "artifacts"
    canonical = tmp_path / "canonical.py"
    write_canonical_runner(canonical, artifacts)
    monkeypatch.setattr(wrapper, "CANONICAL_RUNNER", canonical)
    monkeypatch.setenv("EVAVO_INTEGRITY_WARNINGS_AS_ERRORS", "sometimes")

    result = wrapper.main(arguments(project, artifacts))

    assert result == 2
    gate = json.loads((artifacts / "integrity-gate.json").read_text(encoding="utf-8"))
    assert gate["status"] == "blocked"
    assert gate["executionBlockers"] == ["integrity.preflight_failed"]


def test_wrapper_runs_canonical_runner_then_merges_integrity(monkeypatch, tmp_path: Path) -> None:
    wrapper = load_wrapper()
    source = tmp_path / "source"
    source.mkdir()
    artifacts = tmp_path / "evidence"
    calls: list[object] = []

    class Canonical:
        @staticmethod
        def main() -> int:
            calls.append(("canonical", list(wrapper.sys.argv)))
            return 0

    monkeypatch.setattr(
        wrapper,
        "run_integrity_preflight",
        lambda *args, **kwargs: {"status": "passed"},
    )
    monkeypatch.setattr(wrapper, "_load_canonical_runner", lambda: Canonical())
    monkeypatch.setattr(
        wrapper,
        "merge_integrity_evidence",
        lambda *args, **kwargs: calls.append(("merge", kwargs["runner_exit_code"]))
        or {"status": "passed"},
    )

    result = wrapper.main(
        [
            str(source),
            "--working-root",
            str(tmp_path / "work"),
            "--artifacts",
            str(artifacts),
            "--project-subpath",
            ".",
        ]
    )

    assert result == 0
    assert calls[0][0] == "canonical"
    assert calls[1] == ("merge", 0)


def test_wrapper_does_not_start_canonical_runner_when_preflight_blocks(
    monkeypatch,
    tmp_path: Path,
) -> None:
    wrapper = load_wrapper()
    monkeypatch.setattr(
        wrapper,
        "run_integrity_preflight",
        lambda *args, **kwargs: {"status": "blocked"},
    )
    monkeypatch.setattr(
        wrapper,
        "_load_canonical_runner",
        lambda: (_ for _ in ()).throw(AssertionError("runner must not start")),
    )

    result = wrapper.main(
        [
            str(tmp_path / "source"),
            "--artifacts",
            str(tmp_path / "evidence"),
        ]
    )

    assert result == 2
