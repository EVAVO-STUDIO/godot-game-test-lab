from __future__ import annotations

from collections import defaultdict
from typing import Any

from .asset_audit_contract_scalar import (
    _array,
    _boolean,
    _count_map,
    _exact_properties,
    _integer,
    _number,
    _object,
    _required,
    _string,
    _strings,
)
from .asset_audit_io import AssetAuditError, normalize_relative_path, portable_path_key
from .asset_audit_model import (
    CLEANUP_ACTIONS,
    HEX_64,
    LOOP_MODES,
    POLICIES,
    ROLES,
    AnimationFamily,
    AnimationFrame,
    AuditRow,
    AuditSummary,
    CleanupCandidate,
    DuplicateGroup,
    MissingReference,
)


def _duplicate_group(value: Any, index: int, rows: dict[str, AuditRow]) -> DuplicateGroup:
    label = f"duplicateGroups[{index}]"
    source = _object(value, label)
    _exact_properties(
        source,
        label,
        required={"sha256", "canonicalPath", "paths", "totalBytes"},
    )
    sha256 = _string(_required(source, "sha256", label), f"{label}.sha256")
    if not HEX_64.fullmatch(sha256):
        raise AssetAuditError(f"{label}.sha256 is invalid")
    paths = tuple(
        normalize_relative_path(item, label=f"{label}.paths[{path_index}]")
        for path_index, item in enumerate(
            _array(_required(source, "paths", label), f"{label}.paths")
        )
    )
    if len(paths) < 2 or len(set(map(portable_path_key, paths))) != len(paths):
        raise AssetAuditError(f"{label}.paths must contain at least two unique paths")
    if tuple(sorted(paths)) != paths:
        raise AssetAuditError(f"{label}.paths must be sorted")
    canonical_path = normalize_relative_path(
        _required(source, "canonicalPath", label),
        label=f"{label}.canonicalPath",
    )
    if canonical_path not in paths:
        raise AssetAuditError(f"{label}.canonicalPath must be present in paths")
    missing = [path for path in paths if path not in rows]
    if missing:
        raise AssetAuditError(f"{label} references unaudited paths: {missing[:10]}")
    if any(rows[path].sha256 != sha256 for path in paths):
        raise AssetAuditError(f"{label} contains paths with a different SHA-256")
    total_bytes = _integer(_required(source, "totalBytes", label), f"{label}.totalBytes")
    if total_bytes != sum(rows[path].size_bytes for path in paths):
        raise AssetAuditError(f"{label}.totalBytes does not match its paths")
    return DuplicateGroup(sha256, canonical_path, paths, total_bytes)


def _animation_family(value: Any, index: int, rows: dict[str, AuditRow]) -> AnimationFamily:
    label = f"animationFamilies[{index}]"
    source = _object(value, label)
    _exact_properties(
        source,
        label,
        required={
            "id",
            "role",
            "frames",
            "missingFrameIndices",
            "consistentDimensions",
            "recommendedFramesPerSecond",
            "loopMode",
            "timingNotes",
        },
    )
    family_id = normalize_relative_path(_required(source, "id", label), label=f"{label}.id")
    role = _string(_required(source, "role", label), f"{label}.role")
    if role not in ROLES:
        raise AssetAuditError(f"{label}.role is unsupported")
    frames: list[AnimationFrame] = []
    identities: set[str] = set()
    indices: set[int] = set()
    for frame_index, raw_frame in enumerate(
        _array(_required(source, "frames", label), f"{label}.frames")
    ):
        frame_label = f"{label}.frames[{frame_index}]"
        frame_source = _object(raw_frame, frame_label)
        _exact_properties(
            frame_source,
            frame_label,
            required={"path", "frameIndex"},
        )
        path = normalize_relative_path(
            _required(frame_source, "path", frame_label),
            label=f"{frame_label}.path",
        )
        index_value = _integer(
            _required(frame_source, "frameIndex", frame_label),
            f"{frame_label}.frameIndex",
        )
        key = portable_path_key(path)
        if key in identities or index_value in indices:
            raise AssetAuditError(f"{label}.frames contains duplicate paths or indices")
        identities.add(key)
        indices.add(index_value)
        row = rows.get(path)
        if row is None:
            raise AssetAuditError(f"{frame_label} references an unaudited path")
        if row.animation_family_id != family_id or row.animation_frame_index != index_value:
            raise AssetAuditError(f"{frame_label} disagrees with its art-file membership")
        frames.append(AnimationFrame(path=path, frame_index=index_value))
    if len(frames) < 2:
        raise AssetAuditError(f"{label}.frames must contain at least two frames")
    if tuple(sorted(frames, key=lambda frame: (frame.frame_index, frame.path))) != tuple(frames):
        raise AssetAuditError(f"{label}.frames must be sorted by frameIndex and path")
    minimum = min(frame.frame_index for frame in frames)
    maximum = max(frame.frame_index for frame in frames)
    expected_missing = tuple(index for index in range(minimum, maximum + 1) if index not in indices)
    missing = tuple(
        _integer(item, f"{label}.missingFrameIndices[{missing_index}]")
        for missing_index, item in enumerate(
            _array(
                _required(source, "missingFrameIndices", label),
                f"{label}.missingFrameIndices",
            )
        )
    )
    if missing != expected_missing:
        raise AssetAuditError(f"{label}.missingFrameIndices is not exact")
    consistent = _required(source, "consistentDimensions", label)
    if not (type(consistent) is bool or consistent == "unknown"):
        raise AssetAuditError(
            f"{label}.consistentDimensions must be true, false or 'unknown'"
        )
    fps = _number(
        _required(source, "recommendedFramesPerSecond", label),
        f"{label}.recommendedFramesPerSecond",
        minimum=0.000001,
    )
    loop_mode = _string(_required(source, "loopMode", label), f"{label}.loopMode")
    if loop_mode not in LOOP_MODES:
        raise AssetAuditError(f"{label}.loopMode is unsupported")
    timing_notes = _strings(_required(source, "timingNotes", label), f"{label}.timingNotes")
    return AnimationFamily(
        id=family_id,
        role=role,
        frames=tuple(frames),
        missing_frame_indices=missing,
        consistent_dimensions=consistent,
        recommended_frames_per_second=fps,
        loop_mode=loop_mode,
        timing_notes=timing_notes,
    )


def _missing_reference(value: Any, index: int) -> MissingReference:
    label = f"missingAssetReferences[{index}]"
    source = _object(value, label)
    _exact_properties(
        source,
        label,
        required={"requestedPath", "referencedBy"},
    )
    requested = _string(
        _required(source, "requestedPath", label),
        f"{label}.requestedPath",
    ).replace("\\", "/")
    if requested.startswith("res://"):
        requested = requested[6:]
    requested = normalize_relative_path(requested, label=f"{label}.requestedPath")
    referenced_by = tuple(
        normalize_relative_path(item, label=f"{label}.referencedBy[{source_index}]")
        for source_index, item in enumerate(
            _array(_required(source, "referencedBy", label), f"{label}.referencedBy")
        )
    )
    if not referenced_by:
        raise AssetAuditError(f"{label}.referencedBy may not be empty")
    if len(set(map(portable_path_key, referenced_by))) != len(referenced_by):
        raise AssetAuditError(f"{label}.referencedBy contains duplicates")
    return MissingReference(requested_path=requested, referenced_by=referenced_by)


def _cleanup_candidate(
    value: Any,
    index: int,
    rows: dict[str, AuditRow],
) -> CleanupCandidate:
    label = f"cleanupCandidates[{index}]"
    source = _object(value, label)
    _exact_properties(
        source,
        label,
        required={"path", "action", "reason", "requiresHumanApproval"},
    )
    path = normalize_relative_path(_required(source, "path", label), label=f"{label}.path")
    if path not in rows:
        raise AssetAuditError(f"{label}.path is not an audited asset")
    action = _string(_required(source, "action", label), f"{label}.action")
    if action not in CLEANUP_ACTIONS:
        raise AssetAuditError(f"{label}.action is unsupported")
    approval = _boolean(
        _required(source, "requiresHumanApproval", label),
        f"{label}.requiresHumanApproval",
    )
    if not approval:
        raise AssetAuditError(f"{label}.requiresHumanApproval must be true")
    return CleanupCandidate(
        path=path,
        action=action,
        reason=_string(_required(source, "reason", label), f"{label}.reason"),
        requires_human_approval=True,
    )


def _summary(value: Any, label: str = "auditSummary") -> AuditSummary:
    source = _object(value, label)
    _exact_properties(
        source,
        label,
        required={
            "auditedFiles",
            "exactDuplicateGroups",
            "animationFamilies",
            "missingReferences",
            "blockingFindings",
            "reviewFindings",
            "roleCounts",
            "transparencyPolicyCounts",
        },
    )
    return AuditSummary(
        audited_files=_integer(_required(source, "auditedFiles", label), f"{label}.auditedFiles"),
        exact_duplicate_groups=_integer(
            _required(source, "exactDuplicateGroups", label),
            f"{label}.exactDuplicateGroups",
        ),
        animation_families=_integer(
            _required(source, "animationFamilies", label),
            f"{label}.animationFamilies",
        ),
        missing_references=_integer(
            _required(source, "missingReferences", label),
            f"{label}.missingReferences",
        ),
        blocking_findings=_integer(
            _required(source, "blockingFindings", label),
            f"{label}.blockingFindings",
        ),
        review_findings=_integer(
            _required(source, "reviewFindings", label),
            f"{label}.reviewFindings",
        ),
        role_counts=_count_map(
            _required(source, "roleCounts", label),
            f"{label}.roleCounts",
            allowed_keys=ROLES,
        ),
        transparency_policy_counts=_count_map(
            _required(source, "transparencyPolicyCounts", label),
            f"{label}.transparencyPolicyCounts",
            allowed_keys=POLICIES,
        ),
    )


def _canonical_duplicate_groups(rows: tuple[AuditRow, ...]) -> dict[str, tuple[str, ...]]:
    groups: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        groups[row.sha256].append(row.path)
    return {
        sha256: tuple(sorted(paths))
        for sha256, paths in groups.items()
        if len(paths) > 1
    }
