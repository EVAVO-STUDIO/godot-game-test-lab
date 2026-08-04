from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from godot_game_test_lab.asset_audit_io import AssetAuditError
from godot_game_test_lab.asset_audit_mcp import (
    AssetAuditMcpConfig,
    resolve_audit_path,
    resolve_target,
)


def _git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *arguments],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _repo(root: Path, projects: tuple[str, ...] = (".",)) -> str:
    root.mkdir()
    for relative in projects:
        project = root if relative == "." else root / relative
        project.mkdir(parents=True, exist_ok=True)
        (project / "project.godot").write_text("[application]\n", encoding="utf-8")
    _git(root, "init")
    _git(root, "config", "user.name", "Asset Audit MCP Test")
    _git(root, "config", "user.email", "asset-audit-mcp@example.invalid")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "fixture")
    return _git(root, "rev-parse", "HEAD")


def _config(tmp_path: Path, target_root: Path) -> AssetAuditMcpConfig:
    lab = tmp_path / "lab"
    lab.mkdir()
    evidence = tmp_path / "evidence"
    return AssetAuditMcpConfig.from_environment(
        lab_root=lab,
        allowed_target_roots=[target_root],
        evidence_root=evidence,
    )


def test_config_rejects_source_overlap(tmp_path: Path) -> None:
    target_root = tmp_path / "targets"
    target_root.mkdir()
    lab = tmp_path / "lab"
    lab.mkdir()
    with pytest.raises(AssetAuditError, match="disjoint"):
        AssetAuditMcpConfig.from_environment(
            lab_root=lab,
            allowed_target_roots=[target_root],
            evidence_root=target_root / "evidence",
        )
    assert not (target_root / "evidence").exists()


def test_resolve_target_is_exact_root_restricted_and_sha_bound(tmp_path: Path) -> None:
    targets = tmp_path / "targets"
    targets.mkdir()
    repository = targets / "game"
    sha = _repo(repository)
    config = _config(tmp_path, targets)
    record = resolve_target(
        str(repository),
        config=config,
        expected_target_sha=sha,
    )
    assert record.target_sha == sha
    assert record.project_subpath == "."
    with pytest.raises(AssetAuditError, match="SHA mismatch"):
        resolve_target(
            str(repository),
            config=config,
            expected_target_sha="0" * 40,
        )
    outside = tmp_path / "outside"
    _repo(outside)
    with pytest.raises(AssetAuditError, match="outside"):
        resolve_target(str(outside), config=config)


def test_multiple_projects_require_explicit_project_subpath(tmp_path: Path) -> None:
    targets = tmp_path / "targets"
    targets.mkdir()
    repository = targets / "games"
    _repo(repository, projects=("alpha", "beta"))
    config = _config(tmp_path, targets)
    with pytest.raises(AssetAuditError, match="multiple Godot projects"):
        resolve_target(str(repository), config=config)
    selected = resolve_target(
        str(repository),
        config=config,
        project_subpath="alpha",
    )
    assert selected.project_subpath == "alpha"


def test_audit_path_is_limited_to_target_or_evidence_root(tmp_path: Path) -> None:
    targets = tmp_path / "targets"
    targets.mkdir()
    repository = targets / "game"
    _repo(repository)
    config = _config(tmp_path, targets)
    record = resolve_target(str(repository), config=config)
    target_audit = repository / "audit.json"
    target_audit.write_text("{}", encoding="utf-8")
    assert resolve_audit_path(
        "audit.json",
        target=record,
        config=config,
    ) == target_audit.resolve()
    evidence_audit = config.evidence_root / "audit.json"
    evidence_audit.write_text("{}", encoding="utf-8")
    assert resolve_audit_path(
        str(evidence_audit),
        target=record,
        config=config,
    ) == evidence_audit.resolve()
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    with pytest.raises(AssetAuditError, match="inside"):
        resolve_audit_path(str(outside), target=record, config=config)


def test_allowed_root_may_contain_lab_but_selected_target_may_not_be_lab(
    tmp_path: Path,
) -> None:
    estate = tmp_path / "estate"
    estate.mkdir()
    lab = estate / "godot-game-test-lab"
    _repo(lab)
    target = estate / "game"
    _repo(target)
    config = AssetAuditMcpConfig.from_environment(
        lab_root=lab,
        allowed_target_roots=[estate],
        evidence_root=tmp_path / "evidence",
    )
    selected = resolve_target(str(target), config=config)
    assert selected.git_root == str(target.resolve())
    with pytest.raises(AssetAuditError, match="disjoint"):
        resolve_target(str(lab), config=config)
