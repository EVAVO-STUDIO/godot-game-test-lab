from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from test_foundation_media_plan import _fixture

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
    assert report["releaseEvidenceEligible"] is True
    assert report["targetMutationPerformed"] is False
    assert report["publicationAuthority"] is False


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
    assert report["releaseEvidenceEligible"] is False
    assert "strict-plan-blocked-items" in {
        item["code"] for item in report["findings"]
    }
