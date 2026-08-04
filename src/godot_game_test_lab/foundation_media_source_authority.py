from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from .asset_audit_contract import load_art_studio_audit
from .asset_audit_io import (
    AssetAuditError,
    normalize_relative_path,
    portable_path_key,
    read_stable_regular_file,
    resolve_directory,
    resolve_project_file,
    resolve_regular_file,
)
from .asset_audit_png import probe_image_bytes
from .strict_json import StrictJsonError, load_strict_json_object

MAXIMUM_EVIDENCE_BYTES = 64 * 1024 * 1024
MAXIMUM_IMAGE_PROBE_BYTES = 64 * 1024 * 1024
MAXIMUM_ITEMS = 100_000
HEX_64 = re.compile(r"^[0-9a-f]{64}$")


class FoundationMediaSourceAuthorityError(AssetAuditError):
    """Raised when current target bytes cannot be bound to planning evidence."""


def _finding(
    code: str,
    message: str,
    **details: Any,
) -> dict[str, Any]:
    return {
        "code": code,
        "severity": "error",
        "message": message,
        **details,
    }


def _load_json(path: Path, label: str) -> tuple[dict[str, Any], Path]:
    source = resolve_regular_file(path, label)
    try:
        value, _ = load_strict_json_object(
            source,
            maximum_bytes=MAXIMUM_EVIDENCE_BYTES,
        )
    except (StrictJsonError, OSError, ValueError) as error:
        raise FoundationMediaSourceAuthorityError(
            f"{label} failed strict JSON admission: {error}"
        ) from error
    return value, source


def _exact_root(value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise FoundationMediaSourceAuthorityError(
            f"{label} must be a non-empty absolute directory path"
        )
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        raise FoundationMediaSourceAuthorityError(
            f"{label} must be an absolute directory path"
        )
    return resolve_directory(candidate, label)


def _contract_roles(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    source = contract.get("roles")
    if not isinstance(source, list) or not source or len(source) > 100:
        raise FoundationMediaSourceAuthorityError(
            "Foundation Kit contract roles are missing or unbounded"
        )
    roles: dict[str, dict[str, Any]] = {}
    for index, value in enumerate(source):
        if not isinstance(value, dict):
            raise FoundationMediaSourceAuthorityError(
                f"contract.roles[{index}] must be an object"
            )
        role_id = value.get("id")
        if not isinstance(role_id, str) or not role_id or role_id in roles:
            raise FoundationMediaSourceAuthorityError(
                f"contract.roles[{index}].id is invalid or duplicated"
            )
        roles[role_id] = value
    return roles


def _derived_image_blockers(
    role: dict[str, Any],
    actual_image: Any | None,
) -> set[str]:
    blockers: set[str] = set()
    canvas = role.get("canvas")
    alpha_policy = role.get("alphaPolicy")
    if canvas is not None and actual_image is None:
        blockers.add("image-evidence-required")
        return blockers
    if actual_image is None:
        return blockers
    if alpha_policy == "require-meaningful-alpha":
        if actual_image.alpha_usage != "meaningful":
            blockers.add("meaningful-alpha-required")
    elif alpha_policy == "preserve-authored-opaque":
        if actual_image.alpha_usage == "fully-transparent":
            blockers.add("opaque-art-cannot-be-fully-transparent")
    if isinstance(canvas, dict) and canvas.get("policy") == "exact":
        width = canvas.get("width")
        height = canvas.get("height")
        if actual_image.width != width or actual_image.height != height:
            blockers.add("exact-canvas-mismatch")
    return blockers


def validate_current_foundation_media_sources(
    project: Path,
    contract_path: Path,
    audit_path: Path,
    plan_path: Path,
) -> dict[str, Any]:
    project_root = resolve_directory(project, "Godot project")
    contract, _ = _load_json(
        contract_path,
        "Foundation Kit media production contract",
    )
    roles = _contract_roles(contract)
    audit_source = resolve_regular_file(audit_path, "Art Studio audit")
    audit, _ = load_art_studio_audit(audit_source)
    plan, _ = _load_json(plan_path, "Foundation Kit media production plan")

    findings: list[dict[str, Any]] = []
    try:
        audit_root = _exact_root(audit.root, "Art Studio audit root")
    except FoundationMediaSourceAuthorityError as error:
        findings.append(_finding("current-audit-root-invalid", str(error)))
        audit_root = None
    if audit_root is not None and audit_root != project_root:
        findings.append(
            _finding(
                "current-audit-root-mismatch",
                "Art Studio audit root does not match the current target project.",
                expected=str(project_root),
                observed=str(audit_root),
            )
        )

    try:
        plan_audit_root = _exact_root(
            plan.get("auditRoot"),
            "Foundation Kit plan auditRoot",
        )
    except FoundationMediaSourceAuthorityError as error:
        findings.append(_finding("current-plan-audit-root-invalid", str(error)))
        plan_audit_root = None
    if plan_audit_root is not None and plan_audit_root != project_root:
        findings.append(
            _finding(
                "current-plan-audit-root-mismatch",
                "Foundation Kit plan auditRoot does not match the current target project.",
                expected=str(project_root),
                observed=str(plan_audit_root),
            )
        )
    if (
        audit_root is not None
        and plan_audit_root is not None
        and audit_root != plan_audit_root
    ):
        findings.append(
            _finding(
                "current-plan-audit-authority-split",
                "Plan and audit name different target roots.",
                auditRoot=str(audit_root),
                planAuditRoot=str(plan_audit_root),
            )
        )

    audit_by_path = {row.path: row for row in audit.art_files}
    work_items = plan.get("workItems")
    if not isinstance(work_items, list):
        return {
            "findings": [
                *findings,
                _finding(
                    "current-source-work-items-invalid",
                    "Foundation Kit plan workItems must be an array.",
                ),
            ],
            "validatedItems": 0,
            "probedPngItems": 0,
            "requiredBlockers": {},
        }
    if len(work_items) > MAXIMUM_ITEMS:
        findings.append(
            _finding(
                "current-source-work-items-excessive",
                f"Foundation Kit plan exceeds {MAXIMUM_ITEMS} work items.",
            )
        )
        work_items = work_items[:MAXIMUM_ITEMS]

    validated = 0
    probed_png = 0
    required_blockers: dict[str, list[str]] = {}
    target_members: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)

    for index, value in enumerate(work_items):
        if not isinstance(value, dict):
            findings.append(
                _finding(
                    "current-source-work-item-invalid",
                    f"workItems[{index}] must be an object.",
                    index=index,
                )
            )
            continue
        try:
            relative = normalize_relative_path(
                value.get("sourcePath"),
                label=f"workItems[{index}].sourcePath",
            )
        except AssetAuditError as error:
            findings.append(
                _finding(
                    "current-source-path-invalid",
                    str(error),
                    index=index,
                )
            )
            continue
        row = audit_by_path.get(relative)
        if row is None:
            findings.append(
                _finding(
                    "current-source-not-audited",
                    "Current source path is absent from the bound Art Studio audit.",
                    path=relative,
                )
            )
            continue
        expected_sha = value.get("sourceSha256")
        expected_bytes = value.get("sourceBytes")
        if (
            not isinstance(expected_sha, str)
            or HEX_64.fullmatch(expected_sha) is None
            or isinstance(expected_bytes, bool)
            or not isinstance(expected_bytes, int)
            or expected_bytes < 1
        ):
            findings.append(
                _finding(
                    "current-source-plan-identity-invalid",
                    "Plan source SHA-256 or byte length is invalid.",
                    path=relative,
                )
            )
            continue
        try:
            current_path = resolve_project_file(project_root, relative)
            retain_payload = (
                current_path.suffix.lower() == ".png"
                and expected_bytes <= MAXIMUM_IMAGE_PROBE_BYTES
            )
            stable = read_stable_regular_file(
                current_path,
                maximum_bytes=expected_bytes,
                retain_payload=retain_payload,
            )
        except AssetAuditError as error:
            findings.append(
                _finding(
                    "current-source-unreadable-or-oversized",
                    str(error),
                    path=relative,
                )
            )
            continue
        if (
            stable.sha256 != expected_sha
            or stable.size_bytes != expected_bytes
            or stable.sha256 != row.sha256
            or stable.size_bytes != row.size_bytes
        ):
            findings.append(
                _finding(
                    "current-source-identity-mismatch",
                    "Current target bytes do not match both the plan and Art Studio audit.",
                    path=relative,
                    currentSha256=stable.sha256,
                    currentBytes=stable.size_bytes,
                    planSha256=expected_sha,
                    planBytes=expected_bytes,
                    auditSha256=row.sha256,
                    auditBytes=row.size_bytes,
                )
            )
        extension = current_path.suffix.lower()
        if (
            value.get("sourceExtension") != extension
            or row.extension != extension
        ):
            findings.append(
                _finding(
                    "current-source-extension-mismatch",
                    "Current source extension differs from plan or audit evidence.",
                    path=relative,
                    currentExtension=extension,
                    planExtension=value.get("sourceExtension"),
                    auditExtension=row.extension,
                )
            )

        actual_image = row.image
        if extension == ".png":
            if stable.payload is None:
                findings.append(
                    _finding(
                        "current-source-png-probe-unavailable",
                        "PNG exceeds the bounded independent probe limit.",
                        path=relative,
                        bytes=stable.size_bytes,
                    )
                )
            else:
                actual_image = probe_image_bytes(stable.payload, extension)
                probed_png += 1
                if not actual_image.valid or not actual_image.probe_complete:
                    findings.append(
                        _finding(
                            "current-source-png-invalid",
                            "Current PNG failed the independent structural or alpha probe.",
                            path=relative,
                            warnings=list(actual_image.warnings),
                        )
                    )
        if extension == ".png" and actual_image is not None:
            if row.image is None:
                findings.append(
                    _finding(
                        "current-source-image-audit-missing",
                        "Current PNG has no corresponding audit image evidence.",
                        path=relative,
                    )
                )
            elif (
                row.image.width != actual_image.width
                or row.image.height != actual_image.height
                or row.image.bit_depth != actual_image.bit_depth
                or row.image.colour_model != actual_image.colour_model
                or row.image.has_alpha_channel != actual_image.has_alpha_channel
                or row.image.alpha_usage != actual_image.alpha_usage
                or row.image.probe_complete != actual_image.probe_complete
                or tuple(row.image.warnings) != tuple(actual_image.warnings)
            ):
                findings.append(
                    _finding(
                        "current-source-image-evidence-mismatch",
                        "Independent current PNG evidence differs from the Art Studio audit.",
                        path=relative,
                    )
                )

        role_id = value.get("role")
        role = roles.get(role_id) if isinstance(role_id, str) else None
        if role is None:
            findings.append(
                _finding(
                    "current-source-role-invalid",
                    "Current work item role is absent from the Foundation Kit contract.",
                    path=relative,
                )
            )
        else:
            derived = _derived_image_blockers(role, actual_image)
            declared = value.get("blockers")
            declared_set = {
                item
                for item in declared
                if isinstance(item, str) and item
            } if isinstance(declared, list) else set()
            missing = sorted(derived - declared_set)
            if missing:
                required_blockers[relative] = missing
                findings.append(
                    _finding(
                        "current-source-required-blocker-missing",
                        "Plan omitted blockers independently required by current target bytes.",
                        path=relative,
                        blockers=missing,
                    )
                )

        target = value.get("runtimeTargetPath")
        if isinstance(target, str) and target:
            try:
                normalized_target = normalize_relative_path(
                    target,
                    label=f"workItems[{index}].runtimeTargetPath",
                )
            except AssetAuditError:
                pass
            else:
                target_members[portable_path_key(normalized_target)].append(
                    (relative, value)
                )
        validated += 1

    for members in target_members.values():
        if len(members) < 2:
            continue
        for relative, value in members:
            blockers = value.get("blockers")
            declared = set(blockers) if isinstance(blockers, list) else set()
            if "runtime-target-collision" not in declared:
                required_blockers.setdefault(relative, []).append(
                    "runtime-target-collision"
                )
                findings.append(
                    _finding(
                        "current-source-target-collision-blocker-missing",
                        "Every colliding runtime-target member must be blocked.",
                        path=relative,
                    )
                )

    return {
        "findings": findings,
        "validatedItems": validated,
        "probedPngItems": probed_png,
        "requiredBlockers": {
            path: sorted(set(blockers))
            for path, blockers in sorted(required_blockers.items())
        },
    }
