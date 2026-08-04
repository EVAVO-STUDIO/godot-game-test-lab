from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from test_foundation_media_plan import _fixture

from godot_game_test_lab.asset_audit_io import AssetAuditError
from godot_game_test_lab.asset_audit_mcp_policy import (
    AssetAuditMcpConfig,
    resolve_target,
)
from godot_game_test_lab.foundation_media_mcp import (
    build_release_report_for_mcp,
)


def _git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *arguments],
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _clean_repo(root: Path) -> str:
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.name", "Foundation MCP Fixture")
    _git(root, "config", "user.email", "fixture@evavo.invalid")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "fixture")
    return _git(root, "rev-parse", "HEAD")


def _mcp_fixture(tmp_path: Path):
    targets = tmp_path / "targets"
    targets.mkdir()
    fixture_root = targets / "foundation"
    project, contract, audit_source, plan_source = _fixture(fixture_root)
    head = _clean_repo(project)

    lab_root = tmp_path / "lab"
    lab_root.mkdir()
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    audit = evidence_root / "art-audit.json"
    plan = evidence_root / "art-plan.json"
    shutil.copy2(audit_source, audit)
    shutil.copy2(plan_source, plan)

    config = AssetAuditMcpConfig.from_environment(
        lab_root=lab_root,
        allowed_target_roots=[targets],
        evidence_root=evidence_root,
    )
    target = resolve_target(
        str(project),
        config=config,
        expected_target_sha=head,
    )
    return project, contract, audit, plan, config, target, head


def test_mcp_release_helper_writes_exact_current_source_report(
    tmp_path: Path,
) -> None:
    project, contract, audit, plan, config, target, head = _mcp_fixture(
        tmp_path
    )
    output = config.evidence_root / "release-report.json"

    report = build_release_report_for_mcp(
        target=target,
        config=config,
        contract_path=contract,
        audit_path=audit,
        plan_path=plan,
        output=output,
    )

    assert report["status"] == "passed"
    assert report["targetSha"] == head
    assert report["targetClean"] is True
    assert report["exactHeadBound"] is True
    assert report["currentSourceBound"] is True
    assert report["releaseEvidenceEligible"] is True
    assert report["targetMutationPerformed"] is False
    assert report["publicationAuthority"] is False
    assert report["outputPath"] == str(output.resolve())
    written = json.loads(output.read_text(encoding="utf-8"))
    assert written["targetSha"] == head
    assert written["currentSourceAuthority"]["currentBytesRechecked"] is True
    assert _git(project, "status", "--porcelain=v1", "--untracked-files=all") == ""


def test_mcp_release_helper_is_create_only(tmp_path: Path) -> None:
    _, contract, audit, plan, config, target, _ = _mcp_fixture(tmp_path)
    output = config.evidence_root / "release-report.json"
    build_release_report_for_mcp(
        target=target,
        config=config,
        contract_path=contract,
        audit_path=audit,
        plan_path=plan,
        output=output,
    )

    with pytest.raises(AssetAuditError):
        build_release_report_for_mcp(
            target=target,
            config=config,
            contract_path=contract,
            audit_path=audit,
            plan_path=plan,
            output=output,
        )


def test_mcp_release_helper_rejects_target_write(tmp_path: Path) -> None:
    project, contract, audit, plan, config, target, _ = _mcp_fixture(tmp_path)

    with pytest.raises(AssetAuditError):
        build_release_report_for_mcp(
            target=target,
            config=config,
            contract_path=contract,
            audit_path=audit,
            plan_path=plan,
            output=project / "forbidden-release-report.json",
        )
    assert not (project / "forbidden-release-report.json").exists()
