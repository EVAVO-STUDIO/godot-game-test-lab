from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from asset_audit_fixtures import _audit, _project, _rgba, _write_audit

from godot_game_test_lab.asset_audit_contract import load_art_studio_audit
from godot_game_test_lab.media_production_plan import (
    MediaProductionPlanError,
    validate_media_production_plan,
)


def _write_json(path: Path, value: dict[str, object]) -> str:
    source = json.dumps(value, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _contract() -> dict[str, object]:
    return {
        "schemaVersion": "1.0",
        "contract": "brass_brine_media_production_contract_v1",
        "repository": "EVAVO-STUDIO/Brass_Brine",
        "engine": {"name": "Godot", "minimumVersion": "4.6.2"},
        "roles": [
            {
                "id": "ui-icon",
                "runtimeRoot": "assets/art/ui/icons",
                "runtimeFormat": "webp-lossless",
                "canvas": {
                    "policy": "exact",
                    "width": 256,
                    "height": 256,
                    "upscaleAllowed": False,
                    "cropAllowed": False,
                },
                "alphaPolicy": "require-meaningful-alpha",
                "fitPolicy": "contain_no_crop",
                "godotImport": {
                    "mipmaps": False,
                    "compression": "lossless",
                    "fixAlphaBorder": True,
                    "premultipliedAlpha": False,
                },
                "requiredStages": [
                    "semantic-icon-review",
                    "alpha-edge-and-hidden-rgb-review",
                    "godot-import",
                    "native-ui-review",
                ],
            }
        ],
        "batchPolicy": {
            "sourceFilesAreImmutable": True,
            "outputsAreUnapprovedUntilPromoted": True,
            "automaticDeletionAllowed": False,
            "partialBatchPublicationAllowed": False,
        },
        "mcpExecution": {
            "rootRestrictionRequired": True,
            "arbitraryShellAllowed": False,
            "arbitraryGitArgumentsAllowed": False,
            "forcePushAllowed": False,
        },
    }


def _plan(
    contract_sha: str,
    audit_sha: str,
    audit_row: object,
    *,
    blockers: list[str] | None = None,
) -> dict[str, object]:
    blocker_values = blockers or []
    review_required = bool(blocker_values or audit_row.findings)
    return {
        "schemaVersion": "1.0",
        "contract": "brass_brine_media_production_plan_v1",
        "repository": "EVAVO-STUDIO/Brass_Brine",
        "contractPath": (
            "data/identity/brass_brine_media_production_contract_2026_08_04.json"
        ),
        "contractSha256": contract_sha,
        "auditRoot": "C:/GitRepos/Brass_Brine",
        "auditSha256": audit_sha,
        "selectedRoles": ["ui-icon"],
        "summary": {
            "workItems": 1,
            "reviewRequired": 1 if review_required else 0,
            "blocked": 1 if blocker_values else 0,
            "roleCounts": {"ui-icon": 1},
            "blockerCounts": {
                blocker: blocker_values.count(blocker)
                for blocker in sorted(set(blocker_values))
            },
        },
        "workItems": [
            {
                "sourcePath": audit_row.path,
                "sourceSha256": audit_row.sha256,
                "sourceBytes": audit_row.size_bytes,
                "sourceExtension": audit_row.extension,
                "role": "ui-icon",
                "roleAuthority": "audit-role",
                "runtimeRoot": "assets/art/ui/icons",
                "runtimeFormat": "webp-lossless",
                "runtimeTargetPath": (
                    "assets/art/ui/icons/cargo_icon.webp"
                ),
                "canvas": {
                    "policy": "exact",
                    "width": 256,
                    "height": 256,
                    "upscaleAllowed": False,
                    "cropAllowed": False,
                },
                "alphaPolicy": "require-meaningful-alpha",
                "fitPolicy": "contain_no_crop",
                "godotImport": {
                    "mipmaps": False,
                    "compression": "lossless",
                    "fixAlphaBorder": True,
                    "premultipliedAlpha": False,
                },
                "actions": ["run-decoded-file-quality-gate"],
                "requiredStages": [
                    "semantic-icon-review",
                    "alpha-edge-and-hidden-rgb-review",
                    "godot-import",
                    "native-ui-review",
                ],
                "blockers": blocker_values,
                "reviewRequired": review_required,
                "auditFindings": list(audit_row.findings),
            }
        ],
        "publicationAuthority": False,
        "deletionAuthority": False,
        "humanCreativeApprovalRequired": True,
    }


def _fixture(tmp_path: Path, *, blockers: list[str] | None = None):
    project, audit_path = _project(tmp_path)
    contract_path = (
        project
        / "data"
        / "identity"
        / "brass_brine_media_production_contract_2026_08_04.json"
    )
    plan_path = tmp_path / "evidence" / "plan.json"
    contract_sha = _write_json(contract_path, _contract())
    audit, audit_sha = load_art_studio_audit(audit_path)
    audit_row = next(row for row in audit.art_files if row.role == "ui-icon")
    _write_json(
        plan_path,
        _plan(contract_sha, audit_sha, audit_row, blockers=blockers),
    )
    return project, contract_path, audit_path, plan_path


def test_exact_ready_plan_passes_strict_validation(tmp_path: Path) -> None:
    current = _fixture(tmp_path)
    report = validate_media_production_plan(*current, strict=True)
    assert report["status"] == "passed"
    assert report["summary"]["errors"] == 0
    assert report["summary"]["validatedItems"] == 1
    assert report["captureRoutes"][0]["role"] == "ui-icon"
    assert len(report["captureRoutes"][0]["nativeViewports"]) == 3
    assert report["mutationPerformed"] is False
    assert report["publicationAuthority"] is False


def test_review_blockers_pass_planning_but_fail_strict(tmp_path: Path) -> None:
    current = _fixture(tmp_path, blockers=["meaningful-alpha-required"])
    planning = validate_media_production_plan(*current, strict=False)
    strict = validate_media_production_plan(*current, strict=True)
    assert planning["status"] == "passed"
    assert planning["summary"]["warnings"] == 1
    assert strict["status"] == "failed"
    strict_codes = {item["code"] for item in strict["findings"]}
    assert "strict-plan-blocked-items" in strict_codes
    assert "strict-plan-review-required" in strict_codes


def test_plan_hash_and_source_drift_fail_closed(tmp_path: Path) -> None:
    project, contract_path, audit_path, plan_path = _fixture(tmp_path)
    icon = project / "assets/art/ui/icons/cargo_icon.png"
    icon.write_bytes(_rgba(2, 1, [0, 128]))
    _write_audit(audit_path, _audit(project))
    report = validate_media_production_plan(
        project,
        contract_path,
        audit_path,
        plan_path,
    )
    codes = {item["code"] for item in report["findings"]}
    assert report["status"] == "failed"
    assert "plan-audit-identity-mismatch" in codes
    assert "plan-work-item-source-drift" in codes


def test_contract_must_remain_inside_project(tmp_path: Path) -> None:
    project, _, audit_path, plan_path = _fixture(tmp_path)
    external_contract = tmp_path / "external-contract.json"
    _write_json(external_contract, _contract())
    with pytest.raises(MediaProductionPlanError, match="inside the target project"):
        validate_media_production_plan(
            project,
            external_contract,
            audit_path,
            plan_path,
        )
