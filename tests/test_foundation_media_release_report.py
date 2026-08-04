from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest
from asset_audit_fixtures import _audit, _rgba, _write_audit
from test_foundation_media_plan import _fixture, _plan, _write_json

from godot_game_test_lab.asset_audit_contract import load_art_studio_audit
from godot_game_test_lab.foundation_media_release_report import (
    FoundationMediaReleaseReportError,
    build_foundation_media_release_report,
)


def _run_git(project: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=project,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode != 0:
        raise AssertionError(
            f"git {' '.join(args)} failed: {completed.stdout}\n{completed.stderr}"
        )
    return completed.stdout.strip()


def _initialize_clean_main(project: Path) -> str:
    _run_git(project, "init", "-b", "main")
    _run_git(project, "config", "user.name", "EVAVO Test Fixture")
    _run_git(project, "config", "user.email", "fixture@evavo.invalid")
    _run_git(project, "add", "-A")
    _run_git(project, "commit", "-m", "fixture")
    return _run_git(project, "rev-parse", "HEAD")


def _codes(report: dict[str, object]) -> set[str]:
    return {
        str(item["code"])
        for item in report["findings"]  # type: ignore[index]
    }


def test_release_report_binds_clean_exact_head(tmp_path: Path) -> None:
    project, contract, audit, plan = _fixture(tmp_path)
    head = _initialize_clean_main(project)

    report = build_foundation_media_release_report(
        project,
        contract,
        audit,
        plan,
        strict=True,
    )

    assert report["status"] == "passed"
    assert report["targetSha"] == head
    assert report["targetClean"] is True
    assert report["exactHeadBound"] is True
    assert report["currentSourceBound"] is True
    assert report["releaseEvidenceEligible"] is True
    assert report["targetMutationPerformed"] is False
    assert report["publicationAuthority"] is False
    assert report["summary"]["currentSourceValidatedItems"] == 1
    assert report["summary"]["currentSourceProbedPngItems"] == 1
    assert report["currentSourceAuthority"]["currentBytesRechecked"] is True
    assert report["currentSourceAuthority"]["currentPngEvidenceRechecked"] is True


def test_release_report_rejects_dirty_worktree(tmp_path: Path) -> None:
    project, contract, audit, plan = _fixture(tmp_path)
    _initialize_clean_main(project)
    (project / "untracked-review-note.txt").write_text(
        "not release evidence\n",
        encoding="utf-8",
    )

    with pytest.raises(
        FoundationMediaReleaseReportError,
        match="clean target worktree",
    ):
        build_foundation_media_release_report(
            project,
            contract,
            audit,
            plan,
            strict=True,
        )


def test_release_report_preserves_plan_failure_and_head_identity(
    tmp_path: Path,
) -> None:
    project, contract, audit, plan = _fixture(
        tmp_path,
        blockers=["meaningful-alpha-required"],
    )
    head = _initialize_clean_main(project)

    report = build_foundation_media_release_report(
        project,
        contract,
        audit,
        plan,
        strict=True,
    )

    assert report["status"] == "failed"
    assert report["targetSha"] == head
    assert report["targetClean"] is True
    assert report["currentSourceBound"] is True
    assert report["releaseEvidenceEligible"] is False
    assert "strict-plan-blocked-items" in _codes(report)


def test_release_report_rejects_clean_head_with_stale_audit_bytes(
    tmp_path: Path,
) -> None:
    project, contract, audit, plan = _fixture(tmp_path)
    _initialize_clean_main(project)
    icon = project / "assets" / "art" / "ui" / "icons" / "cargo_icon.png"
    payload = bytearray(icon.read_bytes())
    payload[-1] ^= 1
    icon.write_bytes(payload)
    _run_git(project, "add", "-A")
    _run_git(project, "commit", "-m", "change current media bytes")

    report = build_foundation_media_release_report(
        project,
        contract,
        audit,
        plan,
        strict=True,
    )

    assert report["status"] == "failed"
    assert report["targetClean"] is True
    assert report["currentSourceBound"] is False
    assert report["releaseEvidenceEligible"] is False
    assert "current-source-identity-mismatch" in _codes(report)


def test_release_report_rejects_split_audit_root_authority(
    tmp_path: Path,
) -> None:
    project, contract, audit_path, plan_path = _fixture(tmp_path)
    other_root = tmp_path / "other-game"
    other_root.mkdir()
    audit_value = json.loads(audit_path.read_text(encoding="utf-8"))
    audit_value["root"] = str(other_root.resolve())
    audit_sha = _write_json(audit_path, audit_value)
    plan_value = json.loads(plan_path.read_text(encoding="utf-8"))
    plan_value["auditRoot"] = str(other_root.resolve())
    plan_value["auditSha256"] = audit_sha
    _write_json(plan_path, plan_value)
    _initialize_clean_main(project)

    report = build_foundation_media_release_report(
        project,
        contract,
        audit_path,
        plan_path,
        strict=True,
    )

    assert report["status"] == "failed"
    assert report["currentSourceBound"] is False
    codes = _codes(report)
    assert "current-audit-root-mismatch" in codes
    assert "current-plan-audit-root-mismatch" in codes


def test_release_report_rejects_omitted_current_canvas_blocker(
    tmp_path: Path,
) -> None:
    project, contract_path, audit_path, plan_path = _fixture(tmp_path)
    icon = project / "assets" / "art" / "ui" / "icons" / "cargo_icon.png"
    icon.write_bytes(_rgba(2, 1, [255, 0]))
    _write_audit(audit_path, _audit(project))
    audit, audit_sha = load_art_studio_audit(audit_path)
    audit_row = next(row for row in audit.art_files if row.role == "ui-icon")
    contract_sha = hashlib.sha256(contract_path.read_bytes()).hexdigest()
    _write_json(
        plan_path,
        _plan(
            contract_sha,
            audit_sha,
            audit_row,
            project,
            blockers=[],
        ),
    )
    _initialize_clean_main(project)

    report = build_foundation_media_release_report(
        project,
        contract_path,
        audit_path,
        plan_path,
        strict=True,
    )

    assert report["status"] == "failed"
    assert report["currentSourceBound"] is False
    assert report["releaseEvidenceEligible"] is False
    assert "current-source-required-blocker-missing" in _codes(report)
    assert report["currentSourceAuthority"]["requiredBlockers"] == {
        "assets/art/ui/icons/cargo_icon.png": ["exact-canvas-mismatch"]
    }
