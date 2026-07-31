from __future__ import annotations

import json
from pathlib import Path

from godot_game_test_lab.linux_integrity import (
    merge_integrity_evidence,
    run_integrity_preflight,
)


def make_project(root: Path, *, scene: str | None = None) -> Path:
    root.mkdir(parents=True)
    (root / "project.godot").write_text(
        'config_version=5\n\n[application]\nconfig/name="Fixture"\n'
        'run/main_scene="res://main.tscn"\n',
        encoding="utf-8",
    )
    (root / "main.tscn").write_text(
        scene or '[gd_scene format=3]\n\n[node name="Main" type="Node"]\n',
        encoding="utf-8",
    )
    return root


def read_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_preflight_passes_valid_external_project(tmp_path: Path) -> None:
    source = make_project(tmp_path / "source" / "game")
    artifacts = tmp_path / "evidence"

    gate = run_integrity_preflight(
        source.parent,
        project_subpath="game",
        artifacts_root=artifacts,
    )

    assert gate["status"] == "passed"
    assert gate["executionAllowed"] is True
    assert (artifacts / "integrity-report.json").is_file()
    assert read_json(artifacts / "integrity-gate.json")["status"] == "passed"


def test_nonblocking_scene_corruption_runs_authoritative_lane_but_fails_policy(
    tmp_path: Path,
) -> None:
    source = make_project(
        tmp_path / "source",
        scene=(
            '[gd_scene load_steps=2 format=3]\n'
            '[ext_resource type="Texture2D" path="res://missing.png" id="1"]\n\n'
            '[node name="Main" type="Node"]\n'
            'metadata/texture = ExtResource("1")\n'
        ),
    )
    artifacts = tmp_path / "evidence"

    gate = run_integrity_preflight(
        source,
        project_subpath=".",
        artifacts_root=artifacts,
    )

    assert gate["status"] == "failed"
    assert gate["executionAllowed"] is True
    assert gate["executionBlockers"] == []
    assert any("resource.external_path_missing" in item for item in gate["summaryFindings"])


def test_path_escape_blocks_canonical_runner_and_writes_summary(tmp_path: Path) -> None:
    source = make_project(tmp_path / "source")
    (source / "project.godot").write_text(
        'config_version=5\n\n[application]\nrun/main_scene="res://../outside.tscn"\n',
        encoding="utf-8",
    )
    artifacts = tmp_path / "evidence"

    gate = run_integrity_preflight(
        source,
        project_subpath=".",
        artifacts_root=artifacts,
    )

    assert gate["status"] == "blocked"
    assert gate["executionAllowed"] is False
    assert "project.main_scene_escape" in gate["executionBlockers"]
    summary = read_json(artifacts / "agent-summary.json")
    assert summary["status"] == "blocked"
    assert summary["checks"][0]["id"] == "static-project-integrity"


def test_warnings_can_be_promoted_without_blocking_engine_execution(tmp_path: Path) -> None:
    source = make_project(tmp_path / "source")
    (source / "tool.gd").write_text("@tool\nextends Node\n", encoding="utf-8")

    gate = run_integrity_preflight(
        source,
        project_subpath=".",
        artifacts_root=tmp_path / "evidence",
        warnings_as_errors=True,
    )

    assert gate["status"] == "failed"
    assert gate["executionAllowed"] is True
    assert gate["warnings"] >= 1


def test_merge_makes_static_failure_authoritative_in_agent_and_sandbox_summary(
    tmp_path: Path,
) -> None:
    source = make_project(
        tmp_path / "source",
        scene=(
            '[gd_scene load_steps=2 format=3]\n'
            '[ext_resource type="Texture2D" path="res://missing.png" id="1"]\n\n'
            '[node name="Main" type="Node"]\n'
        ),
    )
    artifacts = tmp_path / "evidence"
    gate = run_integrity_preflight(
        source,
        project_subpath=".",
        artifacts_root=artifacts,
    )
    assert gate["status"] == "failed"
    (artifacts / "agent-summary.json").write_text(
        json.dumps(
            {
                "schemaVersion": "1.0",
                "status": "passed",
                "checks": [{"id": "base-linux-validation", "status": "passed"}],
                "findings": [],
            }
        ),
        encoding="utf-8",
    )
    (artifacts / "sandbox-report.json").write_text(
        json.dumps({"status": "passed", "findings": [], "artifacts": []}),
        encoding="utf-8",
    )

    summary = merge_integrity_evidence(artifacts, runner_exit_code=0)
    summary_again = merge_integrity_evidence(artifacts, runner_exit_code=0)

    assert summary["status"] == "failed"
    assert summary_again["status"] == "failed"
    assert [check["id"] for check in summary_again["checks"]].count(
        "static-project-integrity"
    ) == 1
    assert any(
        record["path"] == "integrity-report.json"
        for record in summary_again["artifacts"]
    )
    sandbox = read_json(artifacts / "sandbox-report.json")
    assert sandbox["status"] == "failed"
    assert "integrity-report.json" in sandbox["artifacts"]


def test_merge_preserves_pass_when_audit_and_runner_pass(tmp_path: Path) -> None:
    source = make_project(tmp_path / "source")
    artifacts = tmp_path / "evidence"
    gate = run_integrity_preflight(
        source,
        project_subpath=".",
        artifacts_root=artifacts,
    )
    assert gate["status"] == "passed"
    (artifacts / "agent-summary.json").write_text(
        json.dumps({"schemaVersion": "1.0", "status": "passed", "checks": [], "findings": []}),
        encoding="utf-8",
    )

    summary = merge_integrity_evidence(artifacts, runner_exit_code=0)

    assert summary["status"] == "passed"
    assert summary["checks"][0]["status"] == "passed"
    assert summary["findings"] == []
