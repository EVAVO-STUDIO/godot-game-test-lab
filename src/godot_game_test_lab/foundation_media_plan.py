from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .asset_audit_contract import load_art_studio_audit
from .asset_audit_io import (
    AssetAuditError,
    default_evidence_root,
    default_lab_root,
    is_within,
    normalize_relative_path,
    portable_path_key,
    read_git_state,
    read_stable_regular_file,
    resolve_directory,
    resolve_regular_file,
    write_evidence_json,
)
from .strict_json import StrictJsonError, load_strict_json_object

REPORT_SCHEMA_VERSION = "1.0"
PLAN_SCHEMA_VERSION = "1.0"
PLAN_CONTRACT = "evavo_godot_media_production_plan_v1"
GAME_CONTRACT = "evavo_godot_media_production_contract_v1"
MAXIMUM_EVIDENCE_BYTES = 64 * 1024 * 1024
MAXIMUM_ITEMS = 100_000
PLAN_REQUIRED = frozenset(
    {
        "schemaVersion",
        "contract",
        "repository",
        "contractPath",
        "contractSha256",
        "auditRoot",
        "auditSha256",
        "selectedRoles",
        "summary",
        "workItems",
        "publicationAuthority",
        "deletionAuthority",
        "humanCreativeApprovalRequired",
    }
)
ITEM_REQUIRED = frozenset(
    {
        "sourcePath",
        "sourceSha256",
        "sourceBytes",
        "sourceExtension",
        "role",
        "roleAuthority",
        "runtimeRoot",
        "runtimeFormat",
        "alphaPolicy",
        "fitPolicy",
        "actions",
        "requiredStages",
        "blockers",
        "reviewRequired",
        "auditFindings",
    }
)
ITEM_OPTIONAL = frozenset({"canvas", "godotImport", "runtimeTargetPath"})


class FoundationMediaPlanError(AssetAuditError):
    """Raised when Foundation Kit media-plan authority cannot be established."""


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise FoundationMediaPlanError(f"{label} must be an object")
    return value


def _array(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise FoundationMediaPlanError(f"{label} must be an array")
    return value


def _strings(value: Any, label: str) -> list[str]:
    values = _array(value, label)
    if any(not isinstance(item, str) or not item for item in values):
        raise FoundationMediaPlanError(
            f"{label} must contain non-empty strings"
        )
    if len(values) != len(set(values)):
        raise FoundationMediaPlanError(f"{label} may not contain duplicates")
    return values


def _exact(
    value: dict[str, Any],
    label: str,
    required: frozenset[str],
    optional: frozenset[str] = frozenset(),
) -> None:
    keys = frozenset(value)
    missing = sorted(required - keys)
    extra = sorted(keys - required - optional)
    if missing or extra:
        raise FoundationMediaPlanError(
            f"{label} properties are invalid: missing={missing}, extra={extra}"
        )


def _load_strict(path: Path, label: str) -> tuple[dict[str, Any], str, Path]:
    resolved = resolve_regular_file(path, label)
    try:
        value, sha256 = load_strict_json_object(
            resolved,
            maximum_bytes=MAXIMUM_EVIDENCE_BYTES,
        )
    except (StrictJsonError, OSError, ValueError) as error:
        raise FoundationMediaPlanError(
            f"{label} failed strict JSON admission: {error}"
        ) from error
    return value, sha256, resolved


def _role_authority(
    contract: dict[str, Any],
) -> tuple[str, dict[str, dict[str, Any]], list[dict[str, Any]]]:
    repository = contract.get("repository")
    if (
        contract.get("schemaVersion") != "1.0"
        or contract.get("contract") != GAME_CONTRACT
        or not isinstance(repository, str)
        or not repository.startswith("EVAVO-STUDIO/")
        or contract.get("engine", {}).get("name") != "Godot"
        or contract.get("engine", {}).get("minimumVersion") != "4.6.2"
    ):
        raise FoundationMediaPlanError(
            "Foundation Kit media production contract identity is invalid"
        )
    batch = _object(contract.get("batchPolicy"), "contract.batchPolicy")
    if (
        batch.get("sourceFilesAreImmutable") is not True
        or batch.get("outputsAreUnapprovedUntilPromoted") is not True
        or batch.get("automaticDeletionAllowed") is not False
        or batch.get("partialBatchPublicationAllowed") is not False
    ):
        raise FoundationMediaPlanError(
            "Foundation Kit media contract batch boundary is invalid"
        )
    mcp = _object(contract.get("mcpExecution"), "contract.mcpExecution")
    if (
        mcp.get("rootRestrictionRequired") is not True
        or mcp.get("arbitraryShellAllowed") is not False
        or mcp.get("arbitraryGitArgumentsAllowed") is not False
        or mcp.get("forcePushAllowed") is not False
    ):
        raise FoundationMediaPlanError(
            "Foundation Kit media contract MCP boundary is invalid"
        )
    surfaces_source = _array(contract.get("surfaces"), "contract.surfaces")
    viewports: list[dict[str, Any]] = []
    surface_ids: set[str] = set()
    for index, source in enumerate(surfaces_source):
        surface = _object(source, f"contract.surfaces[{index}]")
        surface_id = surface.get("id")
        canvas = _object(
            surface.get("authoredCanvas"),
            f"contract.surfaces[{index}].authoredCanvas",
        )
        if (
            not isinstance(surface_id, str)
            or not surface_id
            or surface_id in surface_ids
            or not isinstance(canvas.get("width"), int)
            or not isinstance(canvas.get("height"), int)
        ):
            raise FoundationMediaPlanError(
                f"contract.surfaces[{index}] authority is invalid"
            )
        surface_ids.add(surface_id)
        viewports.append(
            {
                "surface": surface_id,
                "width": canvas["width"],
                "height": canvas["height"],
                "authority": "game-authored-surface",
            }
        )
    if tuple(surface_ids) == () or len(viewports) != 5:
        raise FoundationMediaPlanError(
            "Foundation Kit contract must retain five authored surfaces"
        )

    roles_source = _array(contract.get("roles"), "contract.roles")
    if not roles_source or len(roles_source) > 100:
        raise FoundationMediaPlanError(
            "Foundation Kit media roles are missing or unbounded"
        )
    roles: dict[str, dict[str, Any]] = {}
    folded: set[str] = set()
    for index, source in enumerate(roles_source):
        role = _object(source, f"contract.roles[{index}]")
        role_id = role.get("id")
        if not isinstance(role_id, str) or not role_id:
            raise FoundationMediaPlanError(
                f"contract.roles[{index}].id must be a non-empty string"
            )
        identity = portable_path_key(role_id)
        if identity in folded:
            raise FoundationMediaPlanError(
                f"duplicate Foundation Kit role identity: {role_id}"
            )
        folded.add(identity)
        normalized = dict(role)
        normalized["runtimeRoot"] = normalize_relative_path(
            role.get("runtimeRoot"),
            label=f"contract.roles[{index}].runtimeRoot",
        )
        normalized["requiredStages"] = _strings(
            role.get("requiredStages"),
            f"contract.roles[{index}].requiredStages",
        )
        roles[role_id] = normalized
    return repository, roles, viewports


def _role_fields(role: dict[str, Any]) -> dict[str, Any]:
    return {
        "runtimeRoot": role.get("runtimeRoot"),
        "runtimeFormat": role.get("runtimeFormat"),
        "canvas": role.get("canvas"),
        "alphaPolicy": role.get("alphaPolicy"),
        "fitPolicy": role.get("fitPolicy"),
        "godotImport": role.get("godotImport"),
        "requiredStages": role.get("requiredStages"),
    }


def _is_audio_role(role: dict[str, Any]) -> bool:
    return (
        role.get("canvas") is None
        and role.get("alphaPolicy") == "not-applicable"
    )


def _route(
    role_id: str,
    role: dict[str, Any],
    count: int,
    viewports: list[dict[str, Any]],
) -> dict[str, Any]:
    stages = [str(value) for value in role.get("requiredStages", [])]
    audio = _is_audio_role(role)
    return {
        "role": role_id,
        "items": count,
        "nativeViewports": [] if audio else [dict(item) for item in viewports],
        "requiresMotionCapture": bool(role.get("animation")),
        "requiresAlphaHostileMatteReview": role.get("alphaPolicy")
        in {"require-meaningful-alpha", "derive-alpha-from-luminance"},
        "requiresAudioAnalysis": audio,
        "requiresHumanListening": audio,
        "nativeAcceptanceStages": [
            stage for stage in stages if "native" in stage
        ],
        "allRequiredStages": stages,
    }


def _finding(
    code: str,
    severity: str,
    message: str,
    **details: Any,
) -> dict[str, Any]:
    return {"code": code, "severity": severity, "message": message, **details}


def validate_foundation_media_plan(
    project: Path,
    contract_path: Path,
    audit_path: Path,
    plan_path: Path,
    *,
    strict: bool = False,
) -> dict[str, Any]:
    project_root = resolve_directory(project, "Godot project")
    project_file = resolve_regular_file(project_root / "project.godot", "project.godot")
    if project_file.parent != project_root:
        raise FoundationMediaPlanError(
            "project.godot resolved outside the selected project"
        )
    before = read_git_state(project_root)
    contract, contract_sha, contract_source = _load_strict(
        contract_path, "Foundation Kit media production contract"
    )
    if not is_within(contract_source, project_root):
        raise FoundationMediaPlanError(
            "Foundation Kit media contract must remain inside the target project"
        )
    repository, roles, viewports = _role_authority(contract)
    audit_source = resolve_regular_file(audit_path, "Art Studio audit")
    audit, audit_sha = load_art_studio_audit(audit_source)
    plan, plan_sha, plan_source = _load_strict(
        plan_path, "Foundation Kit media production plan"
    )
    audit_by_path = {row.path: row for row in audit.art_files}
    findings: list[dict[str, Any]] = []

    try:
        _exact(plan, "plan", PLAN_REQUIRED)
    except FoundationMediaPlanError as error:
        findings.append(_finding("plan-properties-invalid", "error", str(error)))
    if (
        plan.get("schemaVersion") != PLAN_SCHEMA_VERSION
        or plan.get("contract") != PLAN_CONTRACT
        or plan.get("repository") != repository
    ):
        findings.append(
            _finding(
                "plan-contract-invalid",
                "error",
                "Foundation Kit media plan identity is invalid.",
            )
        )
    if audit.engine != "godot" or audit.truncated:
        findings.append(
            _finding(
                "plan-audit-authority-invalid",
                "error",
                "Bound Art Studio audit must be a complete Godot audit.",
            )
        )
    if plan.get("contractSha256") != contract_sha:
        findings.append(
            _finding(
                "plan-game-contract-identity-mismatch",
                "error",
                "Plan does not bind the supplied Foundation Kit contract bytes.",
            )
        )
    if plan.get("auditSha256") != audit_sha:
        findings.append(
            _finding(
                "plan-audit-identity-mismatch",
                "error",
                "Plan does not bind the supplied Art Studio audit bytes.",
            )
        )
    if (
        plan.get("publicationAuthority") is not False
        or plan.get("deletionAuthority") is not False
        or plan.get("humanCreativeApprovalRequired") is not True
    ):
        findings.append(
            _finding(
                "plan-authority-boundary-invalid",
                "error",
                "Plan must retain no mutation authority and require human approval.",
            )
        )

    try:
        selected_roles = _strings(plan.get("selectedRoles"), "plan.selectedRoles")
    except FoundationMediaPlanError as error:
        selected_roles = []
        findings.append(_finding("plan-selected-roles-invalid", "error", str(error)))
    unknown_roles = sorted(set(selected_roles) - set(roles))
    if unknown_roles:
        findings.append(
            _finding(
                "plan-selected-role-unknown",
                "error",
                "Plan selectedRoles contains roles absent from the contract.",
                roles=unknown_roles,
            )
        )

    work_items = plan.get("workItems")
    if not isinstance(work_items, list):
        findings.append(
            _finding("plan-work-items-missing", "error", "workItems must be an array.")
        )
        work_items = []
    if len(work_items) > MAXIMUM_ITEMS:
        findings.append(
            _finding(
                "plan-work-items-excessive",
                "error",
                f"Plan exceeds the bounded {MAXIMUM_ITEMS}-item limit.",
            )
        )
        work_items = work_items[:MAXIMUM_ITEMS]

    seen: dict[str, str] = {}
    order: list[str] = []
    role_counts: Counter[str] = Counter()
    blocker_counts: Counter[str] = Counter()
    blocked = 0
    review = 0
    validated = 0
    for index, source in enumerate(work_items):
        if not isinstance(source, dict):
            findings.append(
                _finding(
                    "plan-work-item-invalid",
                    "error",
                    f"workItems[{index}] must be an object.",
                )
            )
            continue
        try:
            _exact(source, f"workItems[{index}]", ITEM_REQUIRED, ITEM_OPTIONAL)
            relative = normalize_relative_path(
                source.get("sourcePath"),
                label=f"workItems[{index}].sourcePath",
            )
            _strings(source.get("actions"), f"workItems[{index}].actions")
            blockers = _strings(
                source.get("blockers"), f"workItems[{index}].blockers"
            )
            audit_findings = _strings(
                source.get("auditFindings"),
                f"workItems[{index}].auditFindings",
            )
        except FoundationMediaPlanError as error:
            findings.append(
                _finding(
                    "plan-work-item-structure-invalid",
                    "error",
                    str(error),
                    index=index,
                )
            )
            continue
        identity = portable_path_key(relative)
        if identity in seen:
            findings.append(
                _finding(
                    "plan-work-item-duplicate",
                    "error",
                    "Plan contains a duplicate or portable path collision.",
                    path=relative,
                )
            )
            continue
        seen[identity] = relative
        order.append(relative)
        row = audit_by_path.get(relative)
        if row is None:
            findings.append(
                _finding(
                    "plan-work-item-not-audited",
                    "error",
                    "Plan source is absent from the bound audit.",
                    path=relative,
                )
            )
            continue
        if source.get("sourceSha256") != row.sha256 or source.get("sourceBytes") != row.size_bytes:
            findings.append(
                _finding(
                    "plan-work-item-source-drift",
                    "error",
                    "Plan source identity differs from the bound audit.",
                    path=relative,
                )
            )
        if source.get("auditFindings") != list(row.findings):
            findings.append(
                _finding(
                    "plan-work-item-audit-findings-drift",
                    "error",
                    "Plan audit findings differ from the bound audit row.",
                    path=relative,
                )
            )
        role_id = source.get("role")
        role_key = "invalid"
        if isinstance(role_id, str) and role_id in roles:
            role_key = role_id
            expected = _role_fields(roles[role_id])
            for field, expected_value in expected.items():
                if source.get(field) != expected_value:
                    findings.append(
                        _finding(
                            "plan-work-item-role-drift",
                            "error",
                            "Plan role fields differ from the game contract.",
                            path=relative,
                            field=field,
                        )
                    )
            target = source.get("runtimeTargetPath")
            if target is not None:
                try:
                    normalized = normalize_relative_path(
                        target,
                        label=f"workItems[{index}].runtimeTargetPath",
                    )
                except AssetAuditError as error:
                    findings.append(
                        _finding("plan-runtime-target-invalid", "error", str(error))
                    )
                else:
                    root = str(expected["runtimeRoot"])
                    if not (normalized == root or normalized.startswith(f"{root}/")):
                        findings.append(
                            _finding(
                                "plan-runtime-target-root-mismatch",
                                "error",
                                "Runtime target is outside the role-owned root.",
                                path=relative,
                            )
                        )
        else:
            findings.append(
                _finding(
                    "plan-work-item-role-invalid",
                    "error",
                    "Plan role is absent from the game contract.",
                    path=relative,
                )
            )
        role_counts[role_key] += 1
        expected_review = bool(blockers or audit_findings)
        if source.get("reviewRequired") is not expected_review:
            findings.append(
                _finding(
                    "plan-work-item-review-state-invalid",
                    "error",
                    "Review state does not match blockers and audit findings.",
                    path=relative,
                )
            )
        if blockers:
            blocked += 1
            blocker_counts.update(blockers)
        if expected_review:
            review += 1
        validated += 1

    if order != sorted(order, key=str.casefold):
        findings.append(
            _finding(
                "plan-work-item-order-invalid",
                "error",
                "Plan work items must use deterministic case-folded path order.",
            )
        )
    expected_summary = {
        "workItems": len(work_items),
        "reviewRequired": review,
        "blocked": blocked,
        "roleCounts": dict(sorted(role_counts.items())),
        "blockerCounts": dict(sorted(blocker_counts.items())),
    }
    if plan.get("summary") != expected_summary:
        findings.append(
            _finding(
                "plan-summary-invalid",
                "error",
                "Plan summary does not match recomputed evidence.",
                expected=expected_summary,
            )
        )
    if strict and blocked:
        findings.append(
            _finding(
                "strict-plan-blocked-items",
                "error",
                "Strict acceptance prohibits blocked work items.",
                count=blocked,
            )
        )
    if strict and review:
        findings.append(
            _finding(
                "strict-plan-review-required",
                "error",
                "Strict acceptance prohibits unresolved review items.",
                count=review,
            )
        )
    if not strict and (blocked or review):
        findings.append(
            _finding(
                "planning-review-remains",
                "warning",
                "The valid plan still contains explicit repair or review work.",
                blocked=blocked,
                reviewRequired=review,
            )
        )

    after = read_git_state(project_root)
    if before.available and after.available and before.to_dict() != after.to_dict():
        findings.append(
            _finding(
                "target-source-state-changed",
                "error",
                "Target Git state changed during plan validation.",
            )
        )
    for label, path, expected_sha in (
        ("game contract", contract_source, contract_sha),
        ("Art Studio audit", audit_source, audit_sha),
        ("media plan", plan_source, plan_sha),
    ):
        if read_stable_regular_file(
            path, maximum_bytes=MAXIMUM_EVIDENCE_BYTES
        ).sha256 != expected_sha:
            findings.append(
                _finding(
                    "plan-evidence-changed",
                    "error",
                    f"The {label} bytes changed during validation.",
                )
            )

    errors = sum(item["severity"] == "error" for item in findings)
    warnings = sum(item["severity"] == "warning" for item in findings)
    routes = [
        _route(role_id, roles[role_id], count, viewports)
        for role_id, count in sorted(role_counts.items())
        if role_id in roles
    ]
    return {
        "schemaVersion": REPORT_SCHEMA_VERSION,
        "tool": "godot-game-test-lab",
        "check": "foundation-media-production-plan",
        "status": "passed" if errors == 0 else "failed",
        "project": str(project_root),
        "repository": repository,
        "contractPath": str(contract_source),
        "contractSha256": contract_sha,
        "auditPath": str(audit_source),
        "auditSha256": audit_sha,
        "planPath": str(plan_source),
        "planSha256": plan_sha,
        "sourceState": {"before": before.to_dict(), "after": after.to_dict()},
        "policy": {
            "strict": strict,
            "finalIdentityRecheck": True,
            "authoredSurfaceRoutes": True,
        },
        "summary": {
            "errors": errors,
            "warnings": warnings,
            "validatedItems": validated,
            "blockedItems": blocked,
            "reviewRequiredItems": review,
            "roleCounts": dict(sorted(role_counts.items())),
            "blockerCounts": dict(sorted(blocker_counts.items())),
        },
        "captureRoutes": routes,
        "findings": findings,
        "mutationPerformed": False,
        "publicationAuthority": False,
        "deletionAuthority": False,
        "truthBoundaries": [
            "A passing plan does not approve art, animation or audio.",
            "Strict evidence coherence does not prove Godot import or native rendering.",
            "Audio metrics do not replace human listening approval.",
            "Publication remains owned by Development Studio.",
        ],
    }


def _failed(error: Exception) -> dict[str, Any]:
    return {
        "schemaVersion": REPORT_SCHEMA_VERSION,
        "tool": "godot-game-test-lab",
        "check": "foundation-media-production-plan",
        "status": "failed",
        "summary": {"errors": 1, "warnings": 0},
        "findings": [
            {
                "code": "foundation-media-plan-command-error",
                "severity": "error",
                "message": str(error),
            }
        ],
        "mutationPerformed": False,
        "publicationAuthority": False,
        "deletionAuthority": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m godot_game_test_lab.foundation_media_plan",
        description=(
            "Bind a Foundation Kit media production plan to exact game contract "
            "and Art Studio audit evidence."
        ),
    )
    parser.add_argument("project", type=Path)
    parser.add_argument("contract", type=Path)
    parser.add_argument("audit", type=Path)
    parser.add_argument("plan", type=Path)
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--evidence-root", type=Path, default=default_evidence_root())
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        report = validate_foundation_media_plan(
            args.project,
            args.contract,
            args.audit,
            args.plan,
            strict=args.strict,
        )
        if args.output is not None:
            project_root = resolve_directory(args.project, "Godot project")
            state = read_git_state(project_root)
            protected = [project_root, default_lab_root()]
            if state.available and state.git_root is not None:
                protected.append(Path(state.git_root))
            write_evidence_json(
                report,
                output=args.output,
                evidence_root=args.evidence_root,
                protected_roots=tuple(dict.fromkeys(protected)),
                replace=False,
            )
    except (AssetAuditError, OSError, StrictJsonError, ValueError) as error:
        report = _failed(error)
    sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return 0 if report.get("status") == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
