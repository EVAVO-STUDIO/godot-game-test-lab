from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from .asset_audit_io import AssetAuditError, normalize_relative_path, portable_path_key
from .asset_audit_model import (
    ALPHA_USAGES,
    CATEGORIES,
    COMPRESSION_POLICIES,
    EXTENSION_CATEGORY,
    HEX_64,
    POLICIES,
    ROLE_POLICY,
    ROLES,
    AuditImage,
    AuditRow,
)


def _required(value: dict[str, Any], key: str, label: str) -> Any:
    if key not in value:
        raise AssetAuditError(f"{label} is missing required property {key!r}")
    return value[key]


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AssetAuditError(f"{label} must be an object")
    return value


def _exact_properties(
    value: dict[str, Any],
    label: str,
    *,
    required: set[str] | frozenset[str],
    optional: set[str] | frozenset[str] = frozenset(),
) -> None:
    actual = set(value)
    missing = sorted(set(required) - actual)
    extra = sorted(actual - set(required) - set(optional))
    if missing or extra:
        raise AssetAuditError(
            f"{label} has invalid properties; missing={missing}, extra={extra}"
        )


def _array(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise AssetAuditError(f"{label} must be an array")
    return value


def _string(value: Any, label: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise AssetAuditError(f"{label} must be a string")
    if not allow_empty and not value:
        raise AssetAuditError(f"{label} may not be empty")
    return value


def _boolean(value: Any, label: str) -> bool:
    if type(value) is not bool:
        raise AssetAuditError(f"{label} must be a boolean")
    return value


def _integer(value: Any, label: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise AssetAuditError(f"{label} must be an integer greater than or equal to {minimum}")
    return value


def _number(value: Any, label: str, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise AssetAuditError(f"{label} must be a finite number")
    result = float(value)
    if not math.isfinite(result) or result < minimum:
        raise AssetAuditError(f"{label} must be a finite number at least {minimum}")
    return result


def _optional_integer(value: Any, label: str, *, minimum: int = 1) -> int | None:
    if value is None:
        return None
    return _integer(value, label, minimum=minimum)


def _optional_number(value: Any, label: str, *, minimum: float = 0.0) -> int | float | None:
    if value is None:
        return None
    result = _number(value, label, minimum=minimum)
    return int(result) if result.is_integer() else result


def _strings(value: Any, label: str) -> tuple[str, ...]:
    items = _array(value, label)
    result: list[str] = []
    for index, item in enumerate(items):
        result.append(_string(item, f"{label}[{index}]", allow_empty=False))
    return tuple(result)


def _count_map(
    value: Any,
    label: str,
    *,
    allowed_keys: frozenset[str] | None = None,
) -> dict[str, int]:
    source = _object(value, label)
    output: dict[str, int] = {}
    for raw_key, raw_count in source.items():
        key = _string(raw_key, f"{label} key")
        if allowed_keys is not None and key not in allowed_keys:
            raise AssetAuditError(f"{label} contains unsupported key {key!r}")
        output[key] = _integer(raw_count, f"{label}.{key}")
    if allowed_keys is not None and set(output) != set(allowed_keys):
        missing = sorted(set(allowed_keys) - set(output))
        extra = sorted(set(output) - set(allowed_keys))
        raise AssetAuditError(
            f"{label} must contain the exact governed keys; missing={missing}, extra={extra}"
        )
    return output


def _image(value: Any, label: str) -> AuditImage:
    source = _object(value, label)
    _exact_properties(
        source,
        label,
        required={
            "format",
            "hasAlphaChannel",
            "alphaUsage",
            "probeComplete",
            "warnings",
        },
        optional={"width", "height", "bitDepth", "colourModel"},
    )
    alpha_usage = _string(_required(source, "alphaUsage", label), f"{label}.alphaUsage")
    if alpha_usage not in ALPHA_USAGES:
        raise AssetAuditError(f"{label}.alphaUsage is unsupported: {alpha_usage}")
    warnings = _strings(_required(source, "warnings", label), f"{label}.warnings")
    return AuditImage(
        format=_string(_required(source, "format", label), f"{label}.format"),
        width=_optional_number(source.get("width"), f"{label}.width", minimum=0.000001),
        height=_optional_number(source.get("height"), f"{label}.height", minimum=0.000001),
        bit_depth=_optional_integer(source.get("bitDepth"), f"{label}.bitDepth"),
        colour_model=(
            _string(source["colourModel"], f"{label}.colourModel")
            if source.get("colourModel") is not None
            else None
        ),
        has_alpha_channel=_boolean(
            _required(source, "hasAlphaChannel", label),
            f"{label}.hasAlphaChannel",
        ),
        alpha_usage=alpha_usage,
        probe_complete=_boolean(
            _required(source, "probeComplete", label),
            f"{label}.probeComplete",
        ),
        warnings=warnings,
    )


def _optimization(value: Any, label: str) -> None:
    source = _object(value, label)
    _exact_properties(
        source,
        label,
        required={
            "masterFormat",
            "runtimeFormat",
            "compression",
            "allowUpscale",
            "notes",
        },
        optional={"recommendedRuntimePath"},
    )
    _string(_required(source, "masterFormat", label), f"{label}.masterFormat")
    _string(_required(source, "runtimeFormat", label), f"{label}.runtimeFormat")
    compression = _string(_required(source, "compression", label), f"{label}.compression")
    if compression not in COMPRESSION_POLICIES:
        raise AssetAuditError(f"{label}.compression is unsupported: {compression}")
    if _required(source, "allowUpscale", label) is not False:
        raise AssetAuditError(f"{label}.allowUpscale must be false")
    if source.get("recommendedRuntimePath") is not None:
        normalize_relative_path(
            source["recommendedRuntimePath"],
            label=f"{label}.recommendedRuntimePath",
        )
    _strings(_required(source, "notes", label), f"{label}.notes")


def _art_row(value: Any, index: int) -> AuditRow:
    label = f"artFiles[{index}]"
    source = _object(value, label)
    _exact_properties(
        source,
        label,
        required={
            "path",
            "extension",
            "sizeBytes",
            "category",
            "sha256",
            "role",
            "transparencyPolicy",
            "referencedBy",
            "referenceCount",
            "optimization",
            "findings",
        },
        optional={"image", "animationFamilyId", "animationFrameIndex"},
    )
    path = normalize_relative_path(_required(source, "path", label), label=f"{label}.path")
    extension = _string(
        _required(source, "extension", label),
        f"{label}.extension",
        allow_empty=True,
    )
    if extension != Path(path).suffix.lower():
        raise AssetAuditError(f"{label}.extension does not match the path suffix")
    category = _string(_required(source, "category", label), f"{label}.category")
    if category not in CATEGORIES:
        raise AssetAuditError(f"{label}.category is unsupported: {category}")
    expected_category = EXTENSION_CATEGORY.get(extension, "other")
    if category != expected_category:
        raise AssetAuditError(
            f"{label}.category {category!r} disagrees with extension category {expected_category!r}"
        )
    sha256 = _string(_required(source, "sha256", label), f"{label}.sha256")
    if not HEX_64.fullmatch(sha256):
        raise AssetAuditError(f"{label}.sha256 must be a lowercase 64-character digest")
    role = _string(_required(source, "role", label), f"{label}.role")
    if role not in ROLES:
        raise AssetAuditError(f"{label}.role is unsupported: {role}")
    policy = _string(
        _required(source, "transparencyPolicy", label),
        f"{label}.transparencyPolicy",
    )
    if policy not in POLICIES:
        raise AssetAuditError(f"{label}.transparencyPolicy is unsupported: {policy}")
    if policy != ROLE_POLICY[role]:
        raise AssetAuditError(
            f"{label}.transparencyPolicy {policy!r} disagrees with role {role!r}"
        )
    image = _image(source["image"], f"{label}.image") if source.get("image") is not None else None
    if category == "image" and image is None:
        raise AssetAuditError(f"{label}.image is required for image rows")
    referenced_by = tuple(
        normalize_relative_path(item, label=f"{label}.referencedBy[{item_index}]")
        for item_index, item in enumerate(
            _array(_required(source, "referencedBy", label), f"{label}.referencedBy")
        )
    )
    if len(set(map(portable_path_key, referenced_by))) != len(referenced_by):
        raise AssetAuditError(f"{label}.referencedBy contains duplicate portable paths")
    reference_count = _integer(
        _required(source, "referenceCount", label),
        f"{label}.referenceCount",
    )
    if reference_count != len(referenced_by):
        raise AssetAuditError(f"{label}.referenceCount does not match referencedBy")
    family_id_raw = source.get("animationFamilyId")
    frame_index_raw = source.get("animationFrameIndex")
    if (family_id_raw is None) != (frame_index_raw is None):
        raise AssetAuditError(
            f"{label} must provide both animationFamilyId and animationFrameIndex"
        )
    family_id = (
        normalize_relative_path(family_id_raw, label=f"{label}.animationFamilyId")
        if family_id_raw is not None
        else None
    )
    frame_index = (
        _integer(frame_index_raw, f"{label}.animationFrameIndex")
        if frame_index_raw is not None
        else None
    )
    _optimization(_required(source, "optimization", label), f"{label}.optimization")
    findings = _strings(_required(source, "findings", label), f"{label}.findings")
    return AuditRow(
        path=path,
        extension=extension,
        size_bytes=_integer(_required(source, "sizeBytes", label), f"{label}.sizeBytes"),
        category=category,
        sha256=sha256,
        role=role,
        transparency_policy=policy,
        image=image,
        referenced_by=referenced_by,
        reference_count=reference_count,
        animation_family_id=family_id,
        animation_frame_index=frame_index,
        findings=findings,
    )
