from __future__ import annotations

import hashlib
import json
from pathlib import Path

from asset_audit_fixtures import _audit, _project, _rgba, _write_audit

from godot_game_test_lab.asset_audit_contract import load_art_studio_audit
from godot_game_test_lab.foundation_media_plan import validate_foundation_media_plan


def _write_json(path: Path, value: dict[str, object]) -> str:
    source = json.dumps(value, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _contract() -> dict[str, object]:
    surfaces = [
        {"id": "hub", "authoredCanvas": {"width": 640, "height": 480}},
        {"id": "godz", "authoredCanvas": {"width": 640, "height": 400}},
        {"id": "jonez", "authoredCanvas": {"width": 640, "height": 400}},
        {"id": "skyfury", "authoredCanvas": {"width": 640, "height": 400}},
        {"id": "pizza", "authoredCanvas": {"width": 640, "height": 400}},
    ]
    return {
        "schemaVersion": "1.0",
        "contract": "evavo_godot_media_production_contract_v1",
        "repository": "EVAVO-STUDIO/GodotGameFoundationKit",
        "engine": {"name": "Godot", "minimumVersion": "4.6.2"},
        "surfaces": surfaces,
        "roles": [
            {
                "id": "shell-desktop-icon",
                "runtimeRoot": (
                    "examples/playable_foundation_hub/assets/final/icons"
                ),
                "runtimeFormat": "png-lossless",
                "canvas": {
                    "policy": "exact",
                    "width": 32,
                    "height": 32,
                    "upscaleAllowed": False,
                    "cropAllowed": False,
                },
                "alphaPolicy": "require-meaningful-alpha",
                "fitPolicy": "contain_no_crop",
                "godotImport": {
                    "mipmaps": False,
                    "compression": "lossless",
                    "filter": "nearest",
                    "fixAlphaBorder": True,
                    "premultipliedAlpha": False,
                },
                "requiredStages": [
                    "small-size-readability-review",
                    "godot-import",
                    "native-shell-review",
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
    audit_root: Path,
    *,
    blockers: list[str] | None = None,
) -> dict[str, object]:
    blocker_values = blockers or []
    review_required = bool(blocker_values or audit_row.findings)
    runtime_root = "examples/playable_foundation_hub/assets/final/icons"
    canvas = {
        "policy": "exact",
        "width": 32,
        "height": 32,
        "upscaleAllowed": False,
        "cropAllowed": False,
    }
    import_policy = {
        "mipmaps": False,
        "compression": "lossless",
        "filter": "nearest",
        "fixAlphaBorder": True,
        "premultipliedAlpha": False,
    }
    stages = [
        "small-size-readability-review",
        "godot-import",
        "native-shell-review",
    ]
    return {
        "schemaVersion": "1.0",
        "contract": "evavo_godot_media_production_plan_v1",
        "repository": "EVAVO-STUDIO/GodotGameFoundationKit",
        "contractPath": (
            "examples/playable_foundation_hub/data/"
            "foundation_kit_media_production_contract_v1.json"
        ),
        "contractSha256": contract_sha,
        "auditRoot": str(audit_root.resolve()),
        "auditSha256": audit_sha,
        "selectedRoles": ["shell-desktop-icon"],
        "summary": {
            "workItems": 1,
            "reviewRequired": 1 if review_required else 0,
            "blocked": 1 if blocker_values else 0,
            "roleCounts": {"shell-desktop-icon": 1},
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
                "role": "shell-desktop-icon",
                "roleAuthority": "path-and-audit-role",
                "runtimeRoot": runtime_root,
                "runtimeFormat": "png-lossless",
                "runtimeTargetPath": f"{runtime_root}/cargo_icon.png",
                "canvas": canvas,
                "alphaPolicy": "require-meaningful-alpha",
                "fitPolicy": "contain_no_crop",
                "godotImport": import_policy,
                "actions": ["master-lossless-nearest-icon"],
                "requiredStages": stages,
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
    icon = project / "assets" / "art" / "ui" / "icons" / "cargo_icon.png"
    icon.write_bytes(_rgba(32, 32, [255] * 1023 + [0]))
    _write_audit(audit_path, _audit(project))
    contract_path = (
        project
        / "examples"
        / "playable_foundation_hub"
        / "data"
        / "foundation_kit_media_production_contract_v1.json"
    )
    plan_path = tmp_path / "evidence" / "foundation-plan.json"
    contract_sha = _write_json(contract_path, _contract())
    audit, audit_sha = load_art_studio_audit(audit_path)
    audit_row = next(row for row in audit.art_files if row.role == "ui-icon")
    _write_json(
        plan_path,
        _plan(
            contract_sha,
            audit_sha,
            audit_row,
            project,
            blockers=blockers,
        ),
    )
    return project, contract_path, audit_path, plan_path


def test_foundation_contract_passes_strict_validation(tmp_path: Path) -> None:
    report = validate_foundation_media_plan(*_fixture(tmp_path), strict=True)
    assert report["status"] == "passed"
    assert report["repository"] == "EVAVO-STUDIO/GodotGameFoundationKit"
    assert report["summary"]["validatedItems"] == 1
    route = report["captureRoutes"][0]
    assert route["role"] == "shell-desktop-icon"
    assert len(route["nativeViewports"]) == 5
    assert route["requiresAudioAnalysis"] is False
    assert report["mutationPerformed"] is False
    assert report["publicationAuthority"] is False


def test_foundation_plan_retains_review_boundary(tmp_path: Path) -> None:
    current = _fixture(tmp_path, blockers=["meaningful-alpha-required"])
    planning = validate_foundation_media_plan(*current, strict=False)
    strict = validate_foundation_media_plan(*current, strict=True)
    assert planning["status"] == "passed"
    assert planning["summary"]["warnings"] == 1
    assert strict["status"] == "failed"
    codes = {item["code"] for item in strict["findings"]}
    assert "strict-plan-blocked-items" in codes
    assert "strict-plan-review-required" in codes


def test_foundation_plan_repository_mismatch_fails(tmp_path: Path) -> None:
    project, contract_path, audit_path, plan_path = _fixture(tmp_path)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["repository"] = "EVAVO-STUDIO/WrongRepo"
    _write_json(plan_path, plan)
    report = validate_foundation_media_plan(
        project,
        contract_path,
        audit_path,
        plan_path,
    )
    assert report["status"] == "failed"
    assert "plan-contract-invalid" in {
        item["code"] for item in report["findings"]
    }
