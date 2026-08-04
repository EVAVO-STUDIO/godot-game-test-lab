from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_asset_audit_source_and_policy_are_permanently_governed() -> None:
    required = (
        "src/godot_game_test_lab/asset_audit.py",
        "src/godot_game_test_lab/asset_audit_checks.py",
        "src/godot_game_test_lab/asset_audit_contract.py",
        "src/godot_game_test_lab/asset_audit_contract_groups.py",
        "src/godot_game_test_lab/asset_audit_contract_scalar.py",
        "src/godot_game_test_lab/asset_audit_io.py",
        "src/godot_game_test_lab/asset_audit_model.py",
        "src/godot_game_test_lab/asset_audit_validation.py",
        "src/godot_game_test_lab/asset_audit_png.py",
        "src/godot_game_test_lab/asset_audit_mcp.py",
        "src/godot_game_test_lab/asset_audit_mcp_policy.py",
        "src/godot_game_test_lab/media_production_plan.py",
        "tests/asset_audit_fixtures.py",
        "tests/test_asset_audit.py",
        "tests/test_asset_audit_authority.py",
        "tests/test_asset_audit_png.py",
        "tests/test_asset_audit_mcp.py",
        "tests/test_media_production_plan.py",
        "docs/ART_STUDIO_ASSET_AUDIT.md",
        "docs/MEDIA_PRODUCTION_PLAN_GATE.md",
    )
    for relative in required:
        assert (ROOT / relative).is_file(), relative

    source = (
        ROOT / "src/godot_game_test_lab/asset_audit_validation.py"
    ).read_text(encoding="utf-8")
    contract = (ROOT / "src/godot_game_test_lab/asset_audit_contract.py").read_text(
        encoding="utf-8"
    )
    io_source = (ROOT / "src/godot_game_test_lab/asset_audit_io.py").read_text(
        encoding="utf-8"
    )
    png = (ROOT / "src/godot_game_test_lab/asset_audit_png.py").read_text(
        encoding="utf-8"
    )
    mcp = (ROOT / "src/godot_game_test_lab/asset_audit_mcp.py").read_text(
        encoding="utf-8"
    )
    mcp_policy = (
        ROOT / "src/godot_game_test_lab/asset_audit_mcp_policy.py"
    ).read_text(encoding="utf-8")
    media_plan = (
        ROOT / "src/godot_game_test_lab/media_production_plan.py"
    ).read_text(encoding="utf-8")
    for token in (
        "load_art_studio_audit",
        "finalIdentityRecheck",
        "expected_target_sha",
        "require_clean_target",
        "allow_unverified_alpha",
        "asset-changed-after-admission",
    ):
        assert token in source
    for token in (
        "load_strict_json_object",
        "_exact_properties",
        "duplicateGroups",
        "cleanupCandidates",
        "auditSummary",
    ):
        assert token in contract
    for token in (
        "read_stable_regular_file",
        "portable_path_key",
        "write_evidence_json",
        "Existing output is not a prior Godot Lab asset-audit report",
    ):
        assert token in io_source
    for token in (
        "PNG chunk CRC mismatch",
        "PNG IDAT chunks must remain consecutive",
        "PNG scanline data does not match the declared canvas",
    ):
        assert token in png
    for token in (
        "AssetAuditMcpConfig",
        "writesTargetRepository",
        "performsGitMutation",
        "godot_validate_art_audit",
        "godot_validate_media_production_plan",
        "allow_evidence_root=False",
    ):
        assert token in mcp
    for token in (
        "Target Git root must remain disjoint from the Lab",
        "Target contains multiple Godot projects",
        "Art Studio audit must remain inside",
    ):
        assert token in mcp_policy
    for token in (
        "load_art_studio_audit",
        "load_strict_json_object",
        "read_stable_regular_file",
        "brass_brine_media_production_plan_v1",
        "plan-game-contract-identity-mismatch",
        "plan-audit-identity-mismatch",
        "plan-work-item-source-drift",
        "strict-plan-blocked-items",
        "strict-plan-review-required",
        '"publicationAuthority": False',
        '"deletionAuthority": False',
    ):
        assert token in media_plan
    for prohibited in (
        "from .agent_bridge import",
        "BridgeConfig",
        "engine_root",
        "git push",
        "subprocess.run([\"rm\"",
    ):
        assert prohibited not in mcp
        assert prohibited not in mcp_policy
        assert prohibited not in media_plan


def test_asset_audit_has_no_ruff_exemption() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    per_file = pyproject.get("tool", {}).get("ruff", {}).get("lint", {}).get(
        "per-file-ignores",
        {},
    )
    assert not any(
        "asset_audit" in path or "media_production_plan" in path
        for path in per_file
    )


def test_asset_audit_mcp_self_test_uses_root_restricted_configuration(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pytest.importorskip("mcp")
    from godot_game_test_lab.asset_audit_mcp import main

    estate = tmp_path / "estate"
    lab = estate / "godot-game-test-lab"
    target = estate / "game"
    evidence = tmp_path / "evidence"
    lab.mkdir(parents=True)
    target.mkdir()
    code = main(
        [
            "--lab-root",
            str(lab),
            "--allowed-root",
            str(estate),
            "--evidence-root",
            str(evidence),
            "--self-test",
        ]
    )
    assert code == 0
    output = capsys.readouterr().out
    assert '"status": "passed"' in output
    assert '"writesTargetRepository": false' in output
    assert '"performsGitMutation": false' in output
