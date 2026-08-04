from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import unicodedata
from collections.abc import Sequence
from pathlib import Path, PurePosixPath
from typing import Any

SCHEMA_VERSION = "1.0"
PLAN_CONTRACT = "brass_brine_media_production_plan_v1"
GAME_CONTRACT = "brass_brine_media_production_contract_v1"
MAXIMUM_JSON_BYTES = 128 * 1024 * 1024
MAXIMUM_ITEMS = 100_000
SHA256 = re.compile(r"^[0-9a-f]{64}$")
WINDOWS_RESERVED = re.compile(
    r"^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?$",
    re.IGNORECASE,
)
NATIVE_VIEWPORTS = (
    {"width": 1280, "height": 720, "authority": "native-gameplay-surface"},
    {"width": 1920, "height": 1080, "authority": "desktop-scale-review"},
    {"width": 1366, "height": 768, "authority": "compact-desktop-review"},
)


class MediaProductionPlanError(ValueError):
    """Raised when media-production evidence fails closed."""


def _is_within(candidate: Path, parent: Path) -> bool:
    try:
        candidate.relative_to(parent)
        return True
    except ValueError:
        return False


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _regular_file(path: Path, label: str) -> Path:
    requested = Path(os.path.abspath(os.fspath(path.expanduser())))
    if requested.is_symlink() or not requested.is_file():
        raise MediaProductionPlanError(
            f"{label} must be a regular non-symlink file: {requested}"
        )
    real = requested.resolve(strict=True)
    if os.path.normcase(str(real)) != os.path.normcase(str(requested)):
        raise MediaProductionPlanError(
            f"{label} may not traverse a symlink or path alias: {requested}"
        )
    if real.stat().st_size > MAXIMUM_JSON_BYTES:
        raise MediaProductionPlanError(
            f"{label} exceeds the bounded {MAXIMUM_JSON_BYTES}-byte limit"
        )
    return real


def _project_root(path: Path) -> Path:
    requested = Path(os.path.abspath(os.fspath(path.expanduser())))
    if requested.is_symlink() or not requested.is_dir():
        raise MediaProductionPlanError(
            "Project must be a real non-symlink directory"
        )
    root = requested.resolve(strict=True)
    if os.path.normcase(str(root)) != os.path.normcase(str(requested)):
        raise MediaProductionPlanError(
            "Project may not traverse a symlink or path alias"
        )
    project_file = root / "project.godot"
    if project_file.is_symlink() or not project_file.is_file():
        raise MediaProductionPlanError(
            "Project does not contain a regular project.godot"
        )
    return root


def _read_json(path: Path, label: str) -> tuple[dict[str, Any], str, Path]:
    real = _regular_file(path, label)
    raw = real.read_bytes()
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise MediaProductionPlanError(
            f"{label} is not valid UTF-8 JSON: {error}"
        ) from error
    if not isinstance(value, dict):
        raise MediaProductionPlanError(f"{label} must contain a JSON object")
    return value, hashlib.sha256(raw).hexdigest(), real


def _portable_relative(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise MediaProductionPlanError(f"{label} must be a string")
    text = unicodedata.normalize("NFC", value.strip().replace("\\", "/"))
    pure = PurePosixPath(text)
    if (
        not text
        or pure.is_absolute()
        or re.match(r"^[A-Za-z]:", text)
        or any(
            part in {"", ".", ".."}
            or part.endswith((".", " "))
            or WINDOWS_RESERVED.match(part)
            for part in pure.parts
        )
    ):
        raise MediaProductionPlanError(
            f"{label} is not a portable repository-relative path: {value!r}"
        )
    return PurePosixPath(*pure.parts).as_posix()


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise MediaProductionPlanError(f"{label} must be an object")
    return value


def _array(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise MediaProductionPlanError(f"{label} must be an array")
    return value


def _string_array(value: Any, label: str) -> list[str]:
    items = _array(value, label)
    if any(not isinstance(item, str) or not item for item in items):
        raise MediaProductionPlanError(f"{label} must contain non-empty strings")
    if len(items) != len(set(items)):
        raise MediaProductionPlanError(f"{label} may not contain duplicates")
    return items


def _contract_roles(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if (
        contract.get("schemaVersion") != SCHEMA_VERSION
        or contract.get("contract") != GAME_CONTRACT
        or contract.get("repository") != "EVAVO-STUDIO/Brass_Brine"
        or contract.get("engine", {}).get("name") != "Godot"
        or contract.get("engine", {}).get("minimumVersion") != "4.6.2"
    ):
        raise MediaProductionPlanError(
            "Media production contract identity is invalid"
        )
    rows = _array(contract.get("roles"), "contract.roles")
    if not rows or len(rows) > 100:
        raise MediaProductionPlanError(
            "Media production contract roles are missing or unbounded"
        )
    result: dict[str, dict[str, Any]] = {}
    for index, value in enumerate(rows):
        role = _object(value, f"contract.roles[{index}]")
        role_id = role.get("id")
        if (
            not isinstance(role_id, str)
            or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", role_id)
            or role_id in result
        ):
            raise MediaProductionPlanError(
                f"contract.roles[{index}].id is invalid or duplicated"
            )
        _portable_relative(
            role.get("runtimeRoot"),
            f"contract.roles[{index}].runtimeRoot",
        )
        _string_array(
            role.get("requiredStages"),
            f"contract.roles[{index}].requiredStages",
        )
        result[role_id] = role
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
    return result


def _audit_rows(audit: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if (
        audit.get("schemaVersion") != SCHEMA_VERSION
        or audit.get("analysisVersion") != "1.0"
        or audit.get("engine") != "godot"
        or audit.get("truncated") is not False
    ):
        raise MediaProductionPlanError(
            "Art Studio audit must be a complete supported Godot audit"
        )
    values = _array(audit.get("artFiles"), "audit.artFiles")
    if len(values) > MAXIMUM_ITEMS:
        raise MediaProductionPlanError(
            f"Audit exceeds the bounded {MAXIMUM_ITEMS}-item limit"
        )
    result: dict[str, dict[str, Any]] = {}
    for index, value in enumerate(values):
        row = _object(value, f"audit.artFiles[{index}]")
        relative = _portable_relative(
            row.get("path"),
            f"audit.artFiles[{index}].path",
        )
        if relative in result:
            raise MediaProductionPlanError(
                f"Audit contains duplicate path: {relative}"
            )
        digest = row.get("sha256")
        size = row.get("sizeBytes")
        if not isinstance(digest, str) or not SHA256.fullmatch(digest):
            raise MediaProductionPlanError(
                f"audit.artFiles[{index}].sha256 is invalid"
            )
        if (
            not isinstance(size, int)
            or isinstance(size, bool)
            or size < 0
        ):
            raise MediaProductionPlanError(
                f"audit.artFiles[{index}].sizeBytes is invalid"
            )
        result[relative] = row
    return result


def _expected_role_item(role: dict[str, Any]) -> dict[str, Any]:
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
    native_stages = [value for value in stages if "native" in value]
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
        "nativeAcceptanceStages": native_stages,
        "allRequiredStages": stages,
    }


def validate_media_production_plan(
    project: Path,
    contract_path: Path,
    audit_path: Path,
    plan_path: Path,
    *,
    strict: bool = False,
) -> dict[str, Any]:
    project_root = _project_root(project)
    contract, contract_sha, contract_real = _read_json(
        contract_path,
        "Media production contract",
    )
    if not _is_within(contract_real, project_root):
        raise MediaProductionPlanError(
            "Media production contract must remain inside the target project"
        )
    audit, audit_sha, audit_real = _read_json(
        audit_path,
        "Art Studio audit",
    )
    plan, plan_sha, plan_real = _read_json(
        plan_path,
        "Media production plan",
    )
    roles = _contract_roles(contract)
    audit_by_path = _audit_rows(audit)
    findings: list[dict[str, Any]] = []

    def error(code: str, message: str, **details: Any) -> None:
        findings.append(
            {
                "code": code,
                "severity": "error",
                "message": message,
                **details,
            }
        )

    def warning(code: str, message: str, **details: Any) -> None:
        findings.append(
            {
                "code": code,
                "severity": "warning",
                "message": message,
                **details,
            }
        )

    if (
        plan.get("schemaVersion") != SCHEMA_VERSION
        or plan.get("contract") != PLAN_CONTRACT
        or plan.get("repository") != "EVAVO-STUDIO/Brass_Brine"
    ):
        error(
            "plan-contract-invalid",
            "Media production plan identity is invalid.",
        )
    if plan.get("contractSha256") != contract_sha:
        error(
            "plan-game-contract-identity-mismatch",
            "Plan does not bind the supplied game contract bytes.",
            expected=contract_sha,
            observed=plan.get("contractSha256"),
        )
    if plan.get("auditSha256") != audit_sha:
        error(
            "plan-audit-identity-mismatch",
            "Plan does not bind the supplied Art Studio audit bytes.",
            expected=audit_sha,
            observed=plan.get("auditSha256"),
        )
    if plan.get("publicationAuthority") is not False:
        error(
            "plan-publication-authority-invalid",
            "Media plan must not claim publication authority.",
        )
    if plan.get("deletionAuthority") is not False:
        error(
            "plan-deletion-authority-invalid",
            "Media plan must not claim deletion authority.",
        )
    if plan.get("humanCreativeApprovalRequired") is not True:
        error(
            "plan-human-approval-boundary-invalid",
            "Media plan must retain human creative approval.",
        )

    values = plan.get("workItems")
    if not isinstance(values, list):
        error("plan-work-items-missing", "Media plan workItems must be an array.")
        values = []
    if len(values) > MAXIMUM_ITEMS:
        error(
            "plan-work-items-excessive",
            f"Media plan exceeds the bounded {MAXIMUM_ITEMS}-item limit.",
        )
        values = values[:MAXIMUM_ITEMS]

    seen: set[str] = set()
    role_counts: dict[str, int] = {}
    blocker_counts: dict[str, int] = {}
    blocked_items = 0
    review_items = 0
    validated_items = 0

    for index, value in enumerate(values):
        if not isinstance(value, dict):
            error(
                "plan-work-item-invalid",
                f"workItems[{index}] must be an object.",
            )
            continue
        try:
            relative = _portable_relative(
                value.get("sourcePath"),
                f"workItems[{index}].sourcePath",
            )
        except MediaProductionPlanError as issue:
            error("plan-work-item-path-invalid", str(issue), index=index)
            continue
        if relative in seen:
            error(
                "plan-work-item-duplicate",
                "Media plan contains a duplicate source path.",
                path=relative,
            )
            continue
        seen.add(relative)
        audit_row = audit_by_path.get(relative)
        if audit_row is None:
            error(
                "plan-work-item-not-audited",
                "Media plan references a source absent from the bound audit.",
                path=relative,
            )
            continue
        if (
            value.get("sourceSha256") != audit_row.get("sha256")
            or value.get("sourceBytes") != audit_row.get("sizeBytes")
        ):
            error(
                "plan-work-item-source-drift",
                "Media plan source identity differs from the bound audit.",
                path=relative,
            )
        role_id = value.get("role")
        if role_id is None:
            role_key = "unresolved"
        elif not isinstance(role_id, str) or role_id not in roles:
            error(
                "plan-work-item-role-invalid",
                "Media plan role is not present in the game contract.",
                path=relative,
                role=role_id,
            )
            role_key = "invalid"
        else:
            role_key = role_id
            role = roles[role_id]
            expected = _expected_role_item(role)
            for field, expected_value in expected.items():
                if value.get(field) != expected_value:
                    error(
                        "plan-work-item-role-drift",
                        "Media plan role contract differs from the game contract.",
                        path=relative,
                        field=field,
                    )
        role_counts[role_key] = role_counts.get(role_key, 0) + 1
        try:
            blockers = _string_array(
                value.get("blockers"),
                f"workItems[{index}].blockers",
            )
            audit_findings = _string_array(
                value.get("auditFindings"),
                f"workItems[{index}].auditFindings",
            )
        except MediaProductionPlanError as issue:
            error("plan-work-item-findings-invalid", str(issue), path=relative)
            continue
        review_required = value.get("reviewRequired")
        expected_review = bool(blockers or audit_findings)
        if review_required is not expected_review:
            error(
                "plan-work-item-review-state-invalid",
                "Media work-item review state does not match its evidence.",
                path=relative,
            )
        if blockers:
            blocked_items += 1
        if expected_review:
            review_items += 1
        for blocker in blockers:
            blocker_counts[blocker] = blocker_counts.get(blocker, 0) + 1
        validated_items += 1

    summary = plan.get("summary")
    expected_summary = {
        "workItems": len(values),
        "reviewRequired": review_items,
        "blocked": blocked_items,
        "roleCounts": dict(sorted(role_counts.items())),
        "blockerCounts": dict(sorted(blocker_counts.items())),
    }
    if not isinstance(summary, dict) or summary != expected_summary:
        error(
            "plan-summary-invalid",
            "Media plan summary does not match recomputed work-item evidence.",
            expected=expected_summary,
            observed=summary,
        )
    if strict and blocked_items > 0:
        error(
            "strict-plan-blocked-items",
            "Strict media acceptance prohibits work items with blockers.",
            count=blocked_items,
        )
    if strict and review_items > 0:
        error(
            "strict-plan-review-required",
            "Strict media acceptance prohibits unresolved review items.",
            count=review_items,
        )
    if not strict and (blocked_items > 0 or review_items > 0):
        warning(
            "planning-review-remains",
            "The plan is valid for production planning but still requires review or repair.",
            blocked=blocked_items,
            reviewRequired=review_items,
        )

    errors = sum(1 for item in findings if item["severity"] == "error")
    warnings = sum(1 for item in findings if item["severity"] == "warning")
    capture_routes = [
        _capture_route(role_id, roles[role_id], count)
        for role_id, count in sorted(role_counts.items())
        if role_id in roles
    ]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "tool": "godot-game-test-lab",
        "check": "media-production-plan",
        "status": "passed" if errors == 0 else "failed",
        "project": str(project_root),
        "contractPath": str(contract_real),
        "contractSha256": contract_sha,
        "auditPath": str(audit_real),
        "auditSha256": audit_sha,
        "planPath": str(plan_real),
        "planSha256": plan_sha,
        "policy": {"strict": strict},
        "summary": {
            "errors": errors,
            "warnings": warnings,
            "validatedItems": validated_items,
            "blockedItems": blocked_items,
            "reviewRequiredItems": review_items,
            "roleCounts": dict(sorted(role_counts.items())),
            "blockerCounts": dict(sorted(blocker_counts.items())),
        },
        "captureRoutes": capture_routes,
        "findings": findings,
        "mutationPerformed": False,
        "publicationAuthority": False,
        "deletionAuthority": False,
        "truthBoundaries": [
            "A passing planning report does not approve art or animation.",
            "Strict mode proves plan and evidence coherence, not native rendering quality.",
            "Native captures, audio listening and human creative approval remain separate.",
            "Publication remains owned by the signed Development Studio transaction.",
        ],
    }


def _write_json(path: Path, value: dict[str, Any]) -> None:
    target = Path(os.path.abspath(os.fspath(path.expanduser())))
    if target.exists() or target.is_symlink():
        raise MediaProductionPlanError(
            f"Output already exists; reports are create-only: {target}"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.tmp-{os.getpid()}")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, target)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m godot_game_test_lab.media_production_plan",
        description=(
            "Validate a Brass & Brine media production plan against exact game "
            "contract and Art Studio audit evidence."
        ),
    )
    parser.add_argument("project", type=Path)
    parser.add_argument("contract", type=Path)
    parser.add_argument("audit", type=Path)
    parser.add_argument("plan", type=Path)
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--output", type=Path)
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
        if args.output:
            _write_json(args.output, report)
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0 if report["status"] == "passed" else 2
    except (MediaProductionPlanError, OSError) as error:
        print(
            json.dumps({"status": "blocked", "error": str(error)}),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
