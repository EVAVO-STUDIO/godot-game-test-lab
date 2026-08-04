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
PLAN_CONTRACT = "brass_brine_media_production_plan_v1"
GAME_CONTRACT = "brass_brine_media_production_contract_v1"
MAXIMUM_EVIDENCE_BYTES = 64 * 1024 * 1024
MAXIMUM_ITEMS = 100_000
NATIVE_VIEWPORTS = (
    {"width": 1280, "height": 720, "authority": "native-gameplay-surface"},
    {"width": 1920, "height": 1080, "authority": "desktop-scale-review"},
    {"width": 1366, "height": 768, "authority": "compact-desktop-review"},
)
PLAN_PROPERTIES = frozenset(
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
WORK_ITEM_REQUIRED = frozenset(
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
WORK_ITEM_OPTIONAL = frozenset({"canvas", "godotImport", "runtimeTargetPath"})


class MediaProductionPlanError(AssetAuditError):
    """Raised when media-production plan authority cannot be established."""


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise MediaProductionPlanError(f"{label} must be an object")
    return value


def _array(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise MediaProductionPlanError(f"{label} must be an array")
    return value


def _strings(value: Any, label: str) -> list[str]:
    items = _array(value, label)
    if any(not isinstance(item, str) or not item for item in items):
        raise MediaProductionPlanError(
            f"{label} must contain non-empty strings"
        )
    if len(items) != len(set(items)):
        raise MediaProductionPlanError(f"{label} may not contain duplicates")
    return items


def _exact_properties(
    value: dict[str, Any],
    label: str,
    *,
    required: frozenset[str],
    optional: frozenset[str] = frozenset(),
) -> None:
    observed = frozenset(value)
    missing = sorted(required - observed)
    extra = sorted(observed - required - optional)
    if missing or extra:
        raise MediaProductionPlanError(
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
        raise MediaProductionPlanError(
            f"{label} failed strict JSON admission: {error}"
        ) from error
    return value, sha256, resolved


def _contract_roles(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if (
        contract.get("schemaVersion") != "1.0"
        or contract.get("contract") != GAME_CONTRACT
        or contract.get("repository") != "EVAVO-STUDIO/Brass_Brine"
        or contract.get("engine", {}).get("name") != "Godot"
        or contract.get("engine", {}).get("minimumVersion") != "4.6.2"
    ):
        raise MediaProductionPlanError(
            "Media production contract identity is invalid"
        )
    roles_source = _array(contract.get("roles"), "contract.roles")
    if not roles_source or len(roles_source) > 100:
        raise MediaProductionPlanError(
            "Media production contract roles are missing or unbounded"
        )
    roles: dict[str, dict[str, Any]] = {}
    identities: set[str] = set()
    for index, source in enumerate(roles_source):
        role = _object(source, f"contract.roles[{index}]")
        role_id = role.get("id")
        if not isinstance(role_id, str) or not role_id:
            raise MediaProductionPlanError(
                f"contract.roles[{index}].id must be a non-empty string"
            )
        identity = portable_path_key(role_id)
        if identity in identities:
            raise MediaProductionPlanError(
                f"contract contains duplicate role identity: {role_id}"
            )
        identities.add(identity)
        runtime_root = normalize_relative_path(
            role.get("runtimeRoot"),
            label=f"contract.roles[{index}].runtimeRoot",
        )
        stages = _strings(
            role.get("requiredStages"),
            f"contract.roles[{index}].requiredStages",
        )
        normalized = dict(role)
        normalized["runtimeRoot"] = runtime_root
        normalized["requiredStages"] = stages
        roles[role_id] = normalized
    batch = _object(contract.get("batchPolicy"), "contract.batchPolicy")
    if (
        batch.get("sourceFilesAreImmutable") is not True
        or batch.get("outputsAreUnapprovedUntilPromoted") is not True
        or batch.get("automaticDeletionAllowed") is not False
        or batch.get("partialBatchPublicationAllowed") is not False
    ):
        raise MediaProductionPlanError(
            "Media production contract batch safety boundary is invalid"
        )
    mcp = _object(contract.get("mcpExecution"), "contract.mcpExecution")
    if (
        mcp.get("rootRestrictionRequired") is not True
        or mcp.get("arbitraryShellAllowed") is not False
        or mcp.get("arbitraryGitArgumentsAllowed") is not False
        or mcp.get("forcePushAllowed") is not False
    ):
        raise MediaProductionPlanError(
            "Media production contract MCP safety boundary is invalid"
        )
    return roles


def _expected_role_fields(role: dict[str, Any]) -> dict[str, Any]:
    return {
        "runtimeRoot": role.get("runtimeRoot"),
        "runtimeFormat": role.get("runtimeFormat"),
        "canvas": role.get("canvas"),
        "alphaPolicy": role.get("alphaPolicy"),
        "fitPolicy": role.get("fitPolicy"),
        "godotImport": role.get("godotImport"),
        "requiredStages": role.get("requiredStages"),
    }


def _capture_route(role_id: str, role: dict[str, Any], count: int) -> dict[str, Any]:
    stages = [str(value) for value in role.get("requiredStages", [])]
    return {
        "role": role_id,
        "items": count,
        "nativeViewports": []
        if role_id == "audio-asset"
        else [dict(value) for value in NATIVE_VIEWPORTS],
        "requiresMotionCapture": bool(role.get("animation")),
        "requiresAlphaHostileMatteReview": role.get("alphaPolicy")
        in {"require-meaningful-alpha", "derive-alpha-from-luminance"},
        "requiresAudioAnalysis": role_id == "audio-asset",
        "requiresHumanListening": role_id == "audio-asset",
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
    return {
        "code": code,
        "severity": severity,
        "message": message,
        **details,
    }


def validate_media_production_plan(
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
        raise MediaProductionPlanError(
            "project.godot resolved outside the selected project"
        )
    before = read_git_state(project_root)
    contract, contract_sha, contract_source = _load_strict(
        contract_path,
        "Media production contract",
    )
    if not is_within(contract_source, project_root):
        raise MediaProductionPlanError(
            "Media production contract must remain inside the target project"
        )
    audit_source = resolve_regular_file(audit_path, "Art Studio audit")
    audit, audit_sha = load_art_studio_audit(audit_source)
    plan, plan_sha, plan_source = _load_strict(
        plan_path,
        "Media production plan",
    )
    roles = _contract_roles(contract)
    audit_by_path = {row.path: row for row in audit.art_files}
    findings: list[dict[str, Any]] = []

    try:
        _exact_properties(
            plan,
            "plan",
            required=PLAN_PROPERTIES,
        )
    except MediaProductionPlanError as error:
        findings.append(
            _finding("plan-properties-invalid", "error", str(error))
        )
    if (
        plan.get("schemaVersion") != PLAN_SCHEMA_VERSION
        or plan.get("contract") != PLAN_CONTRACT
        or plan.get("repository") != "EVAVO-STUDIO/Brass_Brine"
    ):
        findings.append(
            _finding(
                "plan-contract-invalid",
                "error",
                "Media production plan identity is invalid.",
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
                "Plan does not bind the supplied game contract bytes.",
                expected=contract_sha,
                observed=plan.get("contractSha256"),
            )
        )
    if plan.get("auditSha256") != audit_sha:
        findings.append(
            _finding(
                "plan-audit-identity-mismatch",
                "error",
                "Plan does not bind the supplied Art Studio audit bytes.",
                expected=audit_sha,
                observed=plan.get("auditSha256"),
            )
        )
    if plan.get("publicationAuthority") is not False:
        findings.append(
            _finding(
                "plan-publication-authority-invalid",
                "error",
                "Media plan must not claim publication authority.",
            )
        )
    if plan.get("deletionAuthority") is not False:
        findings.append(
            _finding(
                "plan-deletion-authority-invalid",
                "error",
                "Media plan must not claim deletion authority.",
            )
        )
    if plan.get("humanCreativeApprovalRequired") is not True:
        findings.append(
            _finding(
                "plan-human-approval-boundary-invalid",
                "error",
                "Media plan must retain human creative approval.",
            )
        )

    selected_roles: list[str] = []
    try:
        selected_roles = _strings(
            plan.get("selectedRoles"),
            "plan.selectedRoles",
        )
    except MediaProductionPlanError as error:
        findings.append(
            _finding("plan-selected-roles-invalid", "error", str(error))
        )
    unknown_selected = sorted(set(selected_roles) - set(roles))
    if unknown_selected:
        findings.append(
            _finding(
                "plan-selected-role-unknown",
                "error",
                "Plan selectedRoles contains roles absent from the game contract.",
                roles=unknown_selected,
            )
        )

    work_items = plan.get("workItems")
    if not isinstance(work_items, list):
        findings.append(
            _finding(
                "plan-work-items-missing",
                "error",
                "Media plan workItems must be an array.",
            )
        )
        work_items = []
    if len(work_items) > MAXIMUM_ITEMS:
        findings.append(
            _finding(
                "plan-work-items-excessive",
                "error",
                f"Media plan exceeds the bounded {MAXIMUM_ITEMS}-item limit.",
            )
        )
        work_items = work_items[:MAXIMUM_ITEMS]

    seen: dict[str, str] = {}
    observed_order: list[str] = []
    role_counts: Counter[str] = Counter()
    blocker_counts: Counter[str] = Counter()
    blocked_items = 0
    review_items = 0
    validated_items = 0

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
            _exact_properties(
                source,
                f"workItems[{index}]",
                required=WORK_ITEM_REQUIRED,
                optional=WORK_ITEM_OPTIONAL,
            )
            relative = normalize_relative_path(
                source.get("sourcePath"),
                label=f"workItems[{index}].sourcePath",
            )
            actions = _strings(
                source.get("actions"),
                f"workItems[{index}].actions",
            )
            blockers = _strings(
                source.get("blockers"),
                f"workItems[{index}].blockers",
            )
            audit_findings = _strings(
                source.get("auditFindings"),
                f"workItems[{index}].auditFindings",
            )
            _ = actions
        except MediaProductionPlanError as error:
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
        previous = seen.get(identity)
        if previous is not None:
            findings.append(
                _finding(
                    "plan-work-item-duplicate",
                    "error",
                    "Media plan contains a duplicate or portable path collision.",
                    path=relative,
                    previous=previous,
                )
            )
            continue
        seen[identity] = relative
        observed_order.append(relative)
        audit_row = audit_by_path.get(relative)
        if audit_row is None:
            findings.append(
                _finding(
                    "plan-work-item-not-audited",
                    "error",
                    "Media plan references a source absent from the bound audit.",
                    path=relative,
                )
            )
            continue
        if (
            source.get("sourceSha256") != audit_row.sha256
            or source.get("sourceBytes") != audit_row.size_bytes
        ):
            findings.append(
                _finding(
                    "plan-work-item-source-drift",
                    "error",
                    "Media plan source identity differs from the bound audit.",
                    path=relative,
                )
            )
        if source.get("auditFindings") != list(audit_row.findings):
            findings.append(
                _finding(
                    "plan-work-item-audit-findings-drift",
                    "error",
                    "Media plan audit findings differ from the bound audit row.",
                    path=relative,
                )
            )
        role_id = source.get("role")
        role_key = "unresolved"
        if role_id is not None:
            if not isinstance(role_id, str) or role_id not in roles:
                findings.append(
                    _finding(
                        "plan-work-item-role-invalid",
                        "error",
                        "Media plan role is absent from the game contract.",
                        path=relative,
                        role=role_id,
                    )
                )
                role_key = "invalid"
            else:
                role_key = role_id
                expected = _expected_role_fields(roles[role_id])
                for field, expected_value in expected.items():
                    if source.get(field) != expected_value:
                        findings.append(
                            _finding(
                                "plan-work-item-role-drift",
                                "error",
                                "Media plan role contract differs from the game contract.",
                                path=relative,
                                field=field,
                            )
                        )
                target_path = source.get("runtimeTargetPath")
                if target_path is not None:
                    try:
                        normalized_target = normalize_relative_path(
                            target_path,
                            label=f"workItems[{index}].runtimeTargetPath",
                        )
                    except AssetAuditError as error:
                        findings.append(
                            _finding(
                                "plan-runtime-target-invalid",
                                "error",
                                str(error),
                                path=relative,
                            )
                        )
                    else:
                        root = str(expected["runtimeRoot"])
                        if not (
                            normalized_target == root
                            or normalized_target.startswith(f"{root}/")
                        ):
                            findings.append(
                                _finding(
                                    "plan-runtime-target-root-mismatch",
                                    "error",
                                    "Runtime target is outside the role-owned root.",
                                    path=relative,
                                    target=normalized_target,
                                    root=root,
                                )
                            )
        role_counts[role_key] += 1
        expected_review = bool(blockers or audit_findings)
        if source.get("reviewRequired") is not expected_review:
            findings.append(
                _finding(
                    "plan-work-item-review-state-invalid",
                    "error",
                    "Media work-item review state does not match its evidence.",
                    path=relative,
                )
            )
        if blockers:
            blocked_items += 1
            blocker_counts.update(blockers)
        if expected_review:
            review_items += 1
        validated_items += 1

    if observed_order != sorted(observed_order, key=str.casefold):
        findings.append(
            _finding(
                "plan-work-item-order-invalid",
                "error",
                "Media plan workItems must use deterministic case-folded path order.",
            )
        )

    expected_summary = {
        "workItems": len(work_items),
        "reviewRequired": review_items,
        "blocked": blocked_items,
        "roleCounts": dict(sorted(role_counts.items())),
        "blockerCounts": dict(sorted(blocker_counts.items())),
    }
    if plan.get("summary") != expected_summary:
        findings.append(
            _finding(
                "plan-summary-invalid",
                "error",
                "Media plan summary does not match recomputed work-item evidence.",
                expected=expected_summary,
                observed=plan.get("summary"),
            )
        )
    if strict and blocked_items:
        findings.append(
            _finding(
                "strict-plan-blocked-items",
                "error",
                "Strict media acceptance prohibits work items with blockers.",
                count=blocked_items,
            )
        )
    if strict and review_items:
        findings.append(
            _finding(
                "strict-plan-review-required",
                "error",
                "Strict media acceptance prohibits unresolved review items.",
                count=review_items,
            )
        )
    if not strict and (blocked_items or review_items):
        findings.append(
            _finding(
                "planning-review-remains",
                "warning",
                "The valid production plan still contains explicit repair or review work.",
                blocked=blocked_items,
                reviewRequired=review_items,
            )
        )

    after = read_git_state(project_root)
    if before.available and after.available and before.to_dict() != after.to_dict():
        findings.append(
            _finding(
                "target-source-state-changed",
                "error",
                "Target Git state changed while the media plan was validated.",
                before=before.to_dict(),
                after=after.to_dict(),
            )
        )
    for label, source_path, expected_sha in (
        ("game contract", contract_source, contract_sha),
        ("Art Studio audit", audit_source, audit_sha),
        ("media production plan", plan_source, plan_sha),
    ):
        final = read_stable_regular_file(
            source_path,
            maximum_bytes=MAXIMUM_EVIDENCE_BYTES,
        )
        if final.sha256 != expected_sha:
            findings.append(
                _finding(
                    "plan-evidence-changed",
                    "error",
                    f"The {label} bytes changed during validation.",
                )
            )

    error_count = sum(item["severity"] == "error" for item in findings)
    warning_count = sum(item["severity"] == "warning" for item in findings)
    routes = [
        _capture_route(role_id, roles[role_id], count)
        for role_id, count in sorted(role_counts.items())
        if role_id in roles
    ]
    return {
        "schemaVersion": REPORT_SCHEMA_VERSION,
        "tool": "godot-game-test-lab",
        "check": "media-production-plan",
        "status": "passed" if error_count == 0 else "failed",
        "project": str(project_root),
        "contractPath": str(contract_source),
        "contractSha256": contract_sha,
        "auditPath": str(audit_source),
        "auditSha256": audit_sha,
        "planPath": str(plan_source),
        "planSha256": plan_sha,
        "sourceState": {
            "before": before.to_dict(),
            "after": after.to_dict(),
        },
        "policy": {"strict": strict, "finalIdentityRecheck": True},
        "summary": {
            "errors": error_count,
            "warnings": warning_count,
            "validatedItems": validated_items,
            "blockedItems": blocked_items,
            "reviewRequiredItems": review_items,
            "roleCounts": dict(sorted(role_counts.items())),
            "blockerCounts": dict(sorted(blocker_counts.items())),
        },
        "captureRoutes": routes,
        "findings": findings,
        "mutationPerformed": False,
        "publicationAuthority": False,
        "deletionAuthority": False,
        "truthBoundaries": [
            "A passing planning report does not approve art or animation.",
            "Strict validation proves evidence coherence, not native rendering quality.",
            "Native captures, audio listening and human review remain separate gates.",
            "Publication remains owned by the signed Development Studio transaction.",
        ],
    }


def _failed_report(error: Exception) -> dict[str, Any]:
    return {
        "schemaVersion": REPORT_SCHEMA_VERSION,
        "tool": "godot-game-test-lab",
        "check": "media-production-plan",
        "status": "failed",
        "summary": {"errors": 1, "warnings": 0},
        "findings": [
            {
                "code": "media-production-plan-command-error",
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
        prog="python -m godot_game_test_lab.media_production_plan",
        description=(
            "Bind a Brass & Brine media production plan to stable game-contract "
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
        report = validate_media_production_plan(
            args.project,
            args.contract,
            args.audit,
            args.plan,
            strict=args.strict,
        )
        if args.output is not None:
            project_root = resolve_directory(args.project, "Godot project")
            git_state = read_git_state(project_root)
            protected = [project_root, default_lab_root()]
            if git_state.available and git_state.git_root is not None:
                protected.append(Path(git_state.git_root))
            write_evidence_json(
                report,
                output=args.output,
                evidence_root=args.evidence_root,
                protected_roots=tuple(dict.fromkeys(protected)),
                replace=False,
            )
    except (AssetAuditError, OSError, StrictJsonError, ValueError) as error:
        report = _failed_report(error)
    sys.stdout.write(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    )
    return 0 if report.get("status") == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
