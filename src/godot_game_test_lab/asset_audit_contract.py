from __future__ import annotations

from collections import Counter
from pathlib import Path

from .asset_audit_contract_groups import (
    _animation_family,
    _canonical_duplicate_groups,
    _cleanup_candidate,
    _duplicate_group,
    _missing_reference,
    _summary,
)
from .asset_audit_contract_scalar import (
    _array,
    _art_row,
    _boolean,
    _count_map,
    _exact_properties,
    _integer,
    _object,
    _required,
    _string,
    _strings,
)
from .asset_audit_io import AssetAuditError, portable_path_key
from .asset_audit_model import (
    ART_EXTENSIONS as ART_EXTENSIONS,
)
from .asset_audit_model import (
    AUDIT_ANALYSIS_VERSION,
    AUDIT_SCHEMA_VERSION,
    CATEGORIES,
    ENGINES,
    MAX_AUDIT_BYTES,
    MAX_FILES,
    POLICIES,
    ROLES,
    AuditDocument,
    AuditRow,
)
from .asset_audit_model import (
    EXTENSION_CATEGORY as EXTENSION_CATEGORY,
)
from .asset_audit_model import (
    IGNORED_DIRECTORIES as IGNORED_DIRECTORIES,
)
from .asset_audit_model import (
    ROLE_POLICY as ROLE_POLICY,
)
from .strict_json import StrictJsonError, load_strict_json_object


def load_art_studio_audit(
    path: Path,
    *,
    maximum_bytes: int = MAX_AUDIT_BYTES,
) -> tuple[AuditDocument, str]:
    try:
        source, sha256 = load_strict_json_object(path, maximum_bytes=maximum_bytes)
    except (StrictJsonError, OSError, ValueError) as error:
        raise AssetAuditError(f"Art Studio audit failed strict JSON admission: {error}") from error

    _exact_properties(
        source,
        "audit",
        required={
            "schemaVersion",
            "analysisVersion",
            "root",
            "projectName",
            "engine",
            "filesScanned",
            "artFiles",
            "extensionCounts",
            "categoryCounts",
            "signals",
            "gaps",
            "truncated",
            "duplicateGroups",
            "animationFamilies",
            "missingAssetReferences",
            "cleanupCandidates",
            "auditSummary",
            "auditRules",
        },
        optional={"engineVersionHint", "viewport"},
    )

    schema_version = _string(
        _required(source, "schemaVersion", "audit"),
        "audit.schemaVersion",
    )
    analysis_version = _string(
        _required(source, "analysisVersion", "audit"),
        "audit.analysisVersion",
    )
    if schema_version != AUDIT_SCHEMA_VERSION:
        raise AssetAuditError(
            f"Unsupported Art Studio audit schemaVersion: {schema_version}"
        )
    if analysis_version != AUDIT_ANALYSIS_VERSION:
        raise AssetAuditError(
            f"Unsupported Art Studio analysisVersion: {analysis_version}"
        )
    engine = _string(_required(source, "engine", "audit"), "audit.engine")
    if engine not in ENGINES:
        raise AssetAuditError(f"audit.engine is unsupported: {engine}")
    rows_source = _array(_required(source, "artFiles", "audit"), "audit.artFiles")
    if len(rows_source) > MAX_FILES:
        raise AssetAuditError(f"audit contains more than {MAX_FILES} art files")
    rows = tuple(_art_row(row, index) for index, row in enumerate(rows_source))
    rows_by_path: dict[str, AuditRow] = {}
    portable_identities: dict[str, str] = {}
    for row in rows:
        identity = portable_path_key(row.path)
        previous = portable_identities.get(identity)
        if previous is not None:
            raise AssetAuditError(
                "audit contains duplicate case-insensitive or Unicode-normalized paths: "
                f"{previous!r} and {row.path!r}"
            )
        portable_identities[identity] = row.path
        rows_by_path[row.path] = row

    duplicate_groups = tuple(
        _duplicate_group(group, index, rows_by_path)
        for index, group in enumerate(
            _array(_required(source, "duplicateGroups", "audit"), "audit.duplicateGroups")
        )
    )
    canonical_groups = _canonical_duplicate_groups(rows)
    observed_groups = {group.sha256: group.paths for group in duplicate_groups}
    if observed_groups != canonical_groups:
        raise AssetAuditError(
            "audit.duplicateGroups does not exactly match the audited SHA-256 groups"
        )

    animation_families = tuple(
        _animation_family(family, index, rows_by_path)
        for index, family in enumerate(
            _array(
                _required(source, "animationFamilies", "audit"),
                "audit.animationFamilies",
            )
        )
    )
    family_ids = [family.id for family in animation_families]
    if len(set(map(portable_path_key, family_ids))) != len(family_ids):
        raise AssetAuditError("audit.animationFamilies contains duplicate IDs")
    row_families = Counter(
        row.animation_family_id for row in rows if row.animation_family_id is not None
    )
    declared_families = Counter(family.id for family in animation_families)
    for family_id, count in row_families.items():
        if count >= 2 and declared_families[family_id] != 1:
            raise AssetAuditError(
                f"audit.animationFamilies is missing exact family {family_id!r}"
            )

    missing_references = tuple(
        _missing_reference(item, index)
        for index, item in enumerate(
            _array(
                _required(source, "missingAssetReferences", "audit"),
                "audit.missingAssetReferences",
            )
        )
    )
    missing_keys = [portable_path_key(item.requested_path) for item in missing_references]
    if len(set(missing_keys)) != len(missing_keys):
        raise AssetAuditError("audit.missingAssetReferences contains duplicates")

    cleanup_candidates = tuple(
        _cleanup_candidate(item, index, rows_by_path)
        for index, item in enumerate(
            _array(
                _required(source, "cleanupCandidates", "audit"),
                "audit.cleanupCandidates",
            )
        )
    )
    candidate_keys = [
        (portable_path_key(item.path), item.action) for item in cleanup_candidates
    ]
    if len(set(candidate_keys)) != len(candidate_keys):
        raise AssetAuditError("audit.cleanupCandidates contains duplicates")

    summary = _summary(_required(source, "auditSummary", "audit"))
    role_counts = Counter(row.role for row in rows)
    policy_counts = Counter(row.transparency_policy for row in rows)
    blocking_findings = sum(
        finding.startswith("blocking:") for row in rows for finding in row.findings
    )
    review_findings = sum(
        finding.startswith("review:") for row in rows for finding in row.findings
    )
    expected_summary = {
        "audited_files": len(rows),
        "exact_duplicate_groups": len(duplicate_groups),
        "animation_families": len(animation_families),
        "missing_references": len(missing_references),
        "blocking_findings": blocking_findings,
        "review_findings": review_findings,
        "role_counts": {role: role_counts.get(role, 0) for role in ROLES},
        "transparency_policy_counts": {
            policy: policy_counts.get(policy, 0) for policy in POLICIES
        },
    }
    for field, expected in expected_summary.items():
        if getattr(summary, field) != expected:
            raise AssetAuditError(
                f"auditSummary.{field} does not match the audited evidence"
            )

    files_scanned = _integer(
        _required(source, "filesScanned", "audit"),
        "audit.filesScanned",
    )
    if files_scanned > MAX_FILES:
        raise AssetAuditError(
            f"audit.filesScanned exceeds the bounded {MAX_FILES}-file limit"
        )
    extension_counts = _count_map(
        _required(source, "extensionCounts", "audit"),
        "audit.extensionCounts",
    )
    category_counts = _count_map(
        _required(source, "categoryCounts", "audit"),
        "audit.categoryCounts",
        allowed_keys=CATEGORIES,
    )
    if sum(extension_counts.values()) != files_scanned:
        raise AssetAuditError("audit.extensionCounts does not sum to filesScanned")
    if sum(category_counts.values()) != files_scanned:
        raise AssetAuditError("audit.categoryCounts does not sum to filesScanned")
    row_extension_counts = Counter(row.extension or "<none>" for row in rows)
    for extension, count in row_extension_counts.items():
        if extension_counts.get(extension) != count:
            raise AssetAuditError(
                f"audit.extensionCounts[{extension!r}] does not match artFiles"
            )
    row_category_counts = Counter(row.category for row in rows)
    for category in CATEGORIES - {"other"}:
        if category_counts.get(category) != row_category_counts.get(category, 0):
            raise AssetAuditError(
                f"audit.categoryCounts[{category!r}] does not match artFiles"
            )

    viewport = None
    if source.get("viewport") is not None:
        viewport_source = _object(source["viewport"], "audit.viewport")
        _exact_properties(
            viewport_source,
            "audit.viewport",
            required={"width", "height"},
        )
        viewport = (
            _integer(
                _required(viewport_source, "width", "audit.viewport"),
                "audit.viewport.width",
                minimum=1,
            ),
            _integer(
                _required(viewport_source, "height", "audit.viewport"),
                "audit.viewport.height",
                minimum=1,
            ),
        )

    document = AuditDocument(
        schema_version=schema_version,
        analysis_version=analysis_version,
        root=_string(_required(source, "root", "audit"), "audit.root"),
        project_name=_string(
            _required(source, "projectName", "audit"),
            "audit.projectName",
        ),
        engine=engine,
        files_scanned=files_scanned,
        art_files=rows,
        extension_counts=extension_counts,
        category_counts=category_counts,
        signals=_strings(_required(source, "signals", "audit"), "audit.signals"),
        gaps=_strings(_required(source, "gaps", "audit"), "audit.gaps"),
        truncated=_boolean(_required(source, "truncated", "audit"), "audit.truncated"),
        duplicate_groups=duplicate_groups,
        animation_families=animation_families,
        missing_asset_references=missing_references,
        cleanup_candidates=cleanup_candidates,
        audit_summary=summary,
        audit_rules=_strings(
            _required(source, "auditRules", "audit"),
            "audit.auditRules",
        ),
        engine_version_hint=(
            _string(source["engineVersionHint"], "audit.engineVersionHint")
            if source.get("engineVersionHint") is not None
            else None
        ),
        viewport=viewport,
    )
    return document, sha256
