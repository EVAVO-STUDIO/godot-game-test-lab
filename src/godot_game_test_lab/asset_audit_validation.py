from __future__ import annotations

from pathlib import Path
from typing import Any

from .asset_audit_checks import (
    FindingCollector,
    ObservedAsset,
    _compare_image_evidence,
    _duplicate_cleanup_contract,
    _independent_animation_dimensions,
    _state_unchanged,
)
from .asset_audit_contract import (
    ART_EXTENSIONS,
    IGNORED_DIRECTORIES,
    AuditDocument,
    load_art_studio_audit,
)
from .asset_audit_io import (
    AssetAuditError,
    GitState,
    inventory_art_files,
    read_git_state,
    read_stable_regular_file,
    resolve_directory,
    resolve_project_file,
    resolve_regular_file,
)
from .asset_audit_png import ImageProbe, probe_image_bytes

REPORT_SCHEMA_VERSION = "1.1"
DEFAULT_MAXIMUM_ASSET_BYTES = 8 * 1024 * 1024 * 1024
DEFAULT_MAXIMUM_TOTAL_ASSET_BYTES = 64 * 1024 * 1024 * 1024
DEFAULT_MAXIMUM_IMAGE_PROBE_BYTES = 512 * 1024 * 1024
DEFAULT_MAXIMUM_FINDINGS = 20_000


def _report(
    *,
    project: Path,
    audit_path: Path,
    audit_sha256: str | None,
    audit: AuditDocument | None,
    findings: FindingCollector,
    before: GitState,
    after: GitState,
    inventory_before: dict[str, Path] | None,
    inventory_after: dict[str, Path] | None,
    observed: dict[str, ObservedAsset],
    policy: dict[str, Any],
) -> dict[str, Any]:
    unchanged = _state_unchanged(before, after)
    if not unchanged:
        findings.add(
            "target-source-state-changed",
            "error",
            "Target Git state changed while the asset audit was validated.",
            evidence={"before": before.to_dict(), "after": after.to_dict()},
        )
    if inventory_before is not None and inventory_after is not None:
        if tuple(inventory_before) != tuple(inventory_after):
            findings.add(
                "project-inventory-changed",
                "error",
                "The project asset inventory changed during validation.",
                evidence={
                    "beforeCount": len(inventory_before),
                    "afterCount": len(inventory_after),
                },
            )

    current_count = len(inventory_after or inventory_before or {})
    audited_count = len(audit.art_files) if audit is not None else 0
    summary = {
        "auditedRows": audited_count,
        "observedAssets": len(observed),
        "currentArtFiles": current_count,
        "identityFailures": findings.code_counts["asset-identity-mismatch"],
        "alphaFailures": sum(
            findings.code_counts[code]
            for code in {
                "alpha-evidence-missing",
                "audit-alpha-disagrees",
                "fully-transparent-image",
                "meaningful-alpha-not-proven",
                "invalid-image-payload",
            }
        ),
        "errors": findings.error_count,
        "warnings": findings.warning_count,
        "retainedFindings": len(findings.items),
        "omittedFindings": findings.omitted_count,
    }
    return {
        "schemaVersion": REPORT_SCHEMA_VERSION,
        "tool": "godot-game-test-lab",
        "check": "art-studio-asset-audit",
        "status": "passed" if findings.error_count == 0 else "failed",
        "project": str(project),
        "auditPath": str(audit_path),
        "auditSha256": audit_sha256,
        "auditAuthority": (
            {
                "schemaVersion": audit.schema_version,
                "analysisVersion": audit.analysis_version,
                "engine": audit.engine,
                "projectName": audit.project_name,
                "filesScanned": audit.files_scanned,
                "truncated": audit.truncated,
            }
            if audit is not None
            else None
        ),
        "sourceState": {
            "before": before.to_dict(),
            "after": after.to_dict(),
            "unchanged": unchanged,
        },
        "policy": policy,
        "summary": summary,
        "findingsTruncated": findings.omitted_count > 0,
        "findings": findings.payload(),
        "truthBoundaries": [
            (
                "This gate proves current file identity against one exact Art Studio "
                "audit; it does not approve artistic quality."
            ),
            "Static reference analysis cannot prove dynamic runtime ownership or deletion safety.",
            (
                "Unsupported or compressed alpha requires decoded runtime evidence "
                "unless explicitly allowed."
            ),
            (
                "A passing source gate does not replace Godot import, runtime "
                "rendering, retained captures or human review."
            ),
            "This gate never edits, deletes, commits, pushes or publishes target source.",
        ],
    }


def validate_asset_audit(
    project: Path,
    audit_path: Path,
    *,
    allow_unrecorded_assets: bool = False,
    allow_missing_references: bool = False,
    allow_animation_gaps: bool = False,
    allow_unverified_alpha: bool = False,
    expected_target_sha: str | None = None,
    require_clean_target: bool = False,
    require_audit_root_match: bool = False,
    maximum_asset_bytes: int = DEFAULT_MAXIMUM_ASSET_BYTES,
    maximum_total_asset_bytes: int = DEFAULT_MAXIMUM_TOTAL_ASSET_BYTES,
    maximum_image_probe_bytes: int = DEFAULT_MAXIMUM_IMAGE_PROBE_BYTES,
    maximum_findings: int = DEFAULT_MAXIMUM_FINDINGS,
) -> dict[str, Any]:
    findings = FindingCollector(maximum_findings)
    project_root = resolve_directory(project, "Godot project")
    project_file = resolve_regular_file(project_root / "project.godot", "project.godot")
    if project_file.parent != project_root:
        raise AssetAuditError("project.godot resolved outside the selected project")
    audit_source = resolve_regular_file(audit_path, "Art Studio audit")
    before = read_git_state(project_root)

    policy = {
        "allowUnrecordedAssets": allow_unrecorded_assets,
        "allowMissingReferences": allow_missing_references,
        "allowAnimationGaps": allow_animation_gaps,
        "allowUnverifiedAlpha": allow_unverified_alpha,
        "expectedTargetSha": expected_target_sha,
        "requireCleanTarget": require_clean_target,
        "requireAuditRootMatch": require_audit_root_match,
        "maximumAssetBytes": maximum_asset_bytes,
        "maximumTotalAssetBytes": maximum_total_asset_bytes,
        "maximumImageProbeBytes": maximum_image_probe_bytes,
        "maximumFindings": maximum_findings,
        "finalIdentityRecheck": True,
    }

    if expected_target_sha is not None:
        normalized_sha = expected_target_sha.strip().lower()
        if len(normalized_sha) != 40 or any(
            character not in "0123456789abcdef"
            for character in normalized_sha
        ):
            raise AssetAuditError("expected_target_sha must be a lowercase 40-character digest")
        policy["expectedTargetSha"] = normalized_sha
        if not before.available or before.target_sha != normalized_sha:
            findings.add(
                "target-sha-mismatch",
                "error",
                "The target repository does not match the expected commit SHA.",
                evidence={
                    "expected": normalized_sha,
                    "observed": before.target_sha,
                    "gitError": before.error,
                },
            )
    if require_clean_target and (not before.available or before.dirty is not False):
        findings.add(
            "target-not-clean",
            "error",
            "Authoritative asset-audit validation requires a clean Git checkout.",
            evidence=before.to_dict(),
        )

    audit: AuditDocument | None = None
    audit_sha256: str | None = None
    inventory_before: dict[str, Path] | None = None
    inventory_after: dict[str, Path] | None = None
    observed: dict[str, ObservedAsset] = {}
    try:
        audit, audit_sha256 = load_art_studio_audit(audit_source)
        if audit.engine != "godot":
            findings.add(
                "audit-engine-mismatch",
                "error",
                "Art Studio audit is not for a Godot project.",
                evidence={"engine": audit.engine},
            )
        if audit.truncated:
            findings.add(
                "art-studio-audit-truncated",
                "error",
                "Art Studio audit was truncated and cannot establish complete inventory authority.",
            )
        if audit.audit_summary.blocking_findings:
            findings.add(
                "art-studio-blocking-findings",
                "error",
                "Art Studio audit still contains blocking findings.",
                evidence={"count": audit.audit_summary.blocking_findings},
            )
        if require_audit_root_match:
            try:
                audited_root = resolve_directory(Path(audit.root), "Art Studio audit root")
            except AssetAuditError as error:
                findings.add(
                    "audit-root-unavailable",
                    "error",
                    "Art Studio audit root cannot be resolved on this machine.",
                    evidence={"error": str(error), "auditRoot": audit.root},
                )
            else:
                if audited_root != project_root:
                    findings.add(
                        "audit-root-mismatch",
                        "error",
                        "Art Studio audit root does not match the selected project.",
                        evidence={
                            "auditRoot": str(audited_root),
                            "projectRoot": str(project_root),
                        },
                    )

        inventory_before = inventory_art_files(
            project_root,
            extensions=ART_EXTENSIONS,
            ignored_directories=IGNORED_DIRECTORIES,
            maximum_files=max(100_000, len(audit.art_files) + 1),
        )
        audited_paths = {row.path for row in audit.art_files}
        current_paths = set(inventory_before)
        unrecorded = sorted(current_paths - audited_paths)
        absent = sorted(audited_paths - current_paths)
        if unrecorded:
            findings.add(
                "unrecorded-art-files",
                "warning" if allow_unrecorded_assets else "error",
                "Current project contains art or resource files absent from the audit.",
                evidence={"count": len(unrecorded), "sample": unrecorded[:100]},
            )
        if absent:
            findings.add(
                "audited-files-absent",
                "error",
                "Audit contains files absent from the current project inventory.",
                evidence={"count": len(absent), "sample": absent[:100]},
            )

        declared_total = sum(row.size_bytes for row in audit.art_files)
        if declared_total > maximum_total_asset_bytes:
            raise AssetAuditError(
                "Audit declares more bytes than the bounded maximum_total_asset_bytes policy"
            )

        actual_total = 0
        for row in audit.art_files:
            try:
                target = resolve_project_file(project_root, row.path)
                retain_payload = (
                    row.category == "image"
                    and row.size_bytes <= maximum_image_probe_bytes
                )
                stable = read_stable_regular_file(
                    target,
                    maximum_bytes=(
                        min(maximum_asset_bytes, maximum_image_probe_bytes)
                        if retain_payload
                        else maximum_asset_bytes
                    ),
                    retain_payload=retain_payload,
                )
            except AssetAuditError as error:
                findings.add(
                    "asset-read-failed",
                    "error",
                    str(error),
                    path=row.path,
                )
                continue
            actual_total += stable.size_bytes
            if actual_total > maximum_total_asset_bytes:
                raise AssetAuditError(
                    "Current assets exceed the bounded maximum_total_asset_bytes policy"
                )
            if stable.size_bytes != row.size_bytes or stable.sha256 != row.sha256:
                findings.add(
                    "asset-identity-mismatch",
                    "error",
                    "Current bytes do not match the audited asset identity.",
                    path=row.path,
                    evidence={
                        "expectedBytes": row.size_bytes,
                        "actualBytes": stable.size_bytes,
                        "expectedSha256": row.sha256,
                        "actualSha256": stable.sha256,
                    },
                )
                continue
            probe = None
            if row.category == "image":
                if stable.size_bytes > maximum_image_probe_bytes:
                    probe = ImageProbe(
                        format=row.extension.removeprefix(".") or "unknown",
                        width=None,
                        height=None,
                        bit_depth=None,
                        colour_model=None,
                        has_alpha_channel=False,
                        alpha_usage="unknown",
                        probe_complete=False,
                        valid=True,
                        warnings=(
                            (
                                "Image exceeds the bounded independent probe limit "
                                "and requires decoded runtime evidence"
                            ),
                        ),
                    )
                else:
                    probe = probe_image_bytes(stable.payload or b"", row.extension)
                _compare_image_evidence(
                    row,
                    probe,
                    findings,
                    allow_unverified_alpha=allow_unverified_alpha,
                )
            observed[row.path] = ObservedAsset(
                row=row,
                size_bytes=stable.size_bytes,
                sha256=stable.sha256,
                probe=probe,
            )

        if audit.missing_asset_references:
            findings.add(
                "missing-asset-references",
                "warning" if allow_missing_references else "error",
                "Source or resource files reference media absent from the audited repository.",
                evidence={
                    "count": len(audit.missing_asset_references),
                    "sample": [
                        {
                            "requestedPath": item.requested_path,
                            "referencedBy": list(item.referenced_by),
                        }
                        for item in audit.missing_asset_references[:50]
                    ],
                },
            )
        families_with_gaps = [
            family for family in audit.animation_families if family.missing_frame_indices
        ]
        if families_with_gaps:
            findings.add(
                "animation-frame-gaps",
                "warning" if allow_animation_gaps else "error",
                "One or more numbered animation families have missing frame indices.",
                evidence={
                    "familyCount": len(families_with_gaps),
                    "sample": [
                        {
                            "id": family.id,
                            "missingFrameIndices": list(family.missing_frame_indices),
                        }
                        for family in families_with_gaps[:50]
                    ],
                },
            )
        _independent_animation_dimensions(audit, observed, findings)
        _duplicate_cleanup_contract(audit, findings)

        # Re-read every admitted file to prove the final bytes still match the exact
        # identities used by the decision. This deliberately favours release-gate
        # authority over speed; diagnostic callers may raise the byte budgets instead
        # of weakening identity checks.
        for path, asset in observed.items():
            try:
                final = read_stable_regular_file(
                    resolve_project_file(project_root, path),
                    maximum_bytes=maximum_asset_bytes,
                )
            except AssetAuditError as error:
                findings.add(
                    "final-asset-recheck-failed",
                    "error",
                    str(error),
                    path=path,
                )
                continue
            if final.size_bytes != asset.size_bytes or final.sha256 != asset.sha256:
                findings.add(
                    "asset-changed-after-admission",
                    "error",
                    "Asset bytes changed after they were admitted.",
                    path=path,
                    evidence={
                        "admittedBytes": asset.size_bytes,
                        "finalBytes": final.size_bytes,
                        "admittedSha256": asset.sha256,
                        "finalSha256": final.sha256,
                    },
                )
        inventory_after = inventory_art_files(
            project_root,
            extensions=ART_EXTENSIONS,
            ignored_directories=IGNORED_DIRECTORIES,
            maximum_files=max(100_000, len(audit.art_files) + 1),
        )
    except AssetAuditError as error:
        findings.add(
            "asset-audit-validation-error",
            "error",
            str(error),
        )

    after = read_git_state(project_root)
    return _report(
        project=project_root,
        audit_path=audit_source,
        audit_sha256=audit_sha256,
        audit=audit,
        findings=findings,
        before=before,
        after=after,
        inventory_before=inventory_before,
        inventory_after=inventory_after,
        observed=observed,
        policy=policy,
    )
