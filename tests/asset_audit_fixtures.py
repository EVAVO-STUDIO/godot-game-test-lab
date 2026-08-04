from __future__ import annotations

import hashlib
import json
import struct
import subprocess
import zlib
from collections import Counter, defaultdict
from pathlib import Path

from godot_game_test_lab.asset_audit_contract import (
    ART_EXTENSIONS,
    CATEGORIES,
    EXTENSION_CATEGORY,
    POLICIES,
    ROLE_POLICY,
    ROLES,
)
from godot_game_test_lab.asset_audit_png import probe_image_bytes


def _chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )


def _png(width: int, height: int, pixels: bytes) -> bytes:
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    row_bytes = width * 4
    rows = b"".join(
        b"\x00" + pixels[row * row_bytes : (row + 1) * row_bytes]
        for row in range(height)
    )
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(rows))
        + _chunk(b"IEND", b"")
    )


def _rgba(width: int, height: int, alpha: list[int]) -> bytes:
    assert len(alpha) == width * height
    payload = bytearray()
    for value in alpha:
        payload.extend((255, 255, 255, value))
    return _png(width, height, bytes(payload))


def _role(path: str) -> str:
    lower = path.lower()
    if path == "project.godot":
        return "metadata"
    if "rain" in lower or "weather" in lower:
        return "weather-overlay"
    if "icon" in lower:
        return "ui-icon"
    if "background" in lower:
        return "location-background"
    return "metadata"


def _all_files(root: Path) -> list[Path]:
    return sorted(
        (
            path
            for path in root.rglob("*")
            if path.is_file() and ".git" not in path.parts
        ),
        key=lambda path: path.relative_to(root).as_posix().casefold(),
    )


def _row(
    root: Path,
    path: Path,
    *,
    family_id: str | None = None,
    frame_index: int | None = None,
) -> dict[str, object]:
    relative = path.relative_to(root).as_posix()
    extension = path.suffix.lower()
    category = EXTENSION_CATEGORY[extension]
    role = _role(relative)
    row: dict[str, object] = {
        "path": relative,
        "extension": extension,
        "sizeBytes": path.stat().st_size,
        "category": category,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "role": role,
        "transparencyPolicy": ROLE_POLICY[role],
        "referencedBy": [],
        "referenceCount": 0,
        "optimization": {
            "masterFormat": "png" if category == "image" else "source",
            "runtimeFormat": "webp" if category == "image" else "preserve",
            "compression": "lossless" if category == "image" else "source-only",
            "allowUpscale": False,
            "notes": ["fixture"],
        },
        "findings": [],
    }
    if category == "image":
        probe = probe_image_bytes(path.read_bytes(), extension)
        row["image"] = {
            "format": probe.format,
            "width": probe.width,
            "height": probe.height,
            "bitDepth": probe.bit_depth,
            "colourModel": probe.colour_model,
            "hasAlphaChannel": probe.has_alpha_channel,
            "alphaUsage": probe.alpha_usage,
            "probeComplete": probe.probe_complete,
            "warnings": list(probe.warnings),
        }
    if family_id is not None:
        row["animationFamilyId"] = family_id
        row["animationFrameIndex"] = frame_index
    return row


def _audit(
    root: Path,
    *,
    families: list[dict[str, object]] | None = None,
    extra_cleanup: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    files = _all_files(root)
    family_members: dict[str, tuple[str, int]] = {}
    for family in families or []:
        for frame in family["frames"]:  # type: ignore[index]
            frame = dict(frame)  # type: ignore[arg-type]
            family_members[str(frame["path"])] = (
                str(family["id"]),
                int(frame["frameIndex"]),
            )
    rows = [
        _row(
            root,
            path,
            family_id=family_members.get(path.relative_to(root).as_posix(), (None, None))[0],
            frame_index=family_members.get(path.relative_to(root).as_posix(), (None, None))[1],
        )
        for path in files
        if path.suffix.lower() in ART_EXTENSIONS
    ]
    extension_counts = Counter(path.suffix.lower() or "<none>" for path in files)
    category_counts = Counter(
        EXTENSION_CATEGORY.get(path.suffix.lower(), "other") for path in files
    )
    sha_groups: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        sha_groups[str(row["sha256"])].append(row)
    duplicate_groups: list[dict[str, object]] = []
    cleanup: list[dict[str, object]] = []
    for digest, group in sorted(sha_groups.items()):
        if len(group) < 2:
            continue
        paths = sorted(str(row["path"]) for row in group)
        duplicate_groups.append(
            {
                "sha256": digest,
                "canonicalPath": paths[0],
                "paths": paths,
                "totalBytes": sum(int(row["sizeBytes"]) for row in group),
            }
        )
        cleanup.extend(
            {
                "path": duplicate,
                "action": "review-exact-duplicate",
                "reason": f"Exact duplicate of {paths[0]}",
                "requiresHumanApproval": True,
            }
            for duplicate in paths[1:]
        )
    cleanup.extend(extra_cleanup or [])
    role_counts = Counter(str(row["role"]) for row in rows)
    policy_counts = Counter(str(row["transparencyPolicy"]) for row in rows)
    return {
        "schemaVersion": "1.0",
        "analysisVersion": "1.0",
        "root": str(root.resolve()),
        "projectName": "Asset Audit",
        "engine": "godot",
        "filesScanned": len(files),
        "artFiles": rows,
        "extensionCounts": dict(extension_counts),
        "categoryCounts": {
            category: category_counts.get(category, 0) for category in CATEGORIES
        },
        "signals": ["fixture"],
        "gaps": [],
        "truncated": False,
        "duplicateGroups": duplicate_groups,
        "animationFamilies": families or [],
        "missingAssetReferences": [],
        "cleanupCandidates": cleanup,
        "auditSummary": {
            "auditedFiles": len(rows),
            "exactDuplicateGroups": len(duplicate_groups),
            "animationFamilies": len(families or []),
            "missingReferences": 0,
            "blockingFindings": 0,
            "reviewFindings": 0,
            "roleCounts": {role: role_counts.get(role, 0) for role in ROLES},
            "transparencyPolicyCounts": {
                policy: policy_counts.get(policy, 0) for policy in POLICIES
            },
        },
        "auditRules": ["fixture"],
    }


def _write_audit(path: Path, value: dict[str, object]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _project(tmp_path: Path, *, alpha: list[int] | None = None) -> tuple[Path, Path]:
    root = tmp_path / "game"
    root.mkdir()
    (root / "project.godot").write_text(
        '[application]\nconfig/name="Asset Audit"\n',
        encoding="utf-8",
    )
    icon = root / "assets" / "art" / "ui" / "icons" / "cargo_icon.png"
    icon.parent.mkdir(parents=True)
    icon.write_bytes(_rgba(2, 1, alpha or [255, 0]))
    audit_path = tmp_path / "audit.json"
    _write_audit(audit_path, _audit(root))
    return root, audit_path


def _codes(report: dict[str, object]) -> set[str]:
    return {str(item["code"]) for item in report["findings"]}  # type: ignore[index]


def _git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *arguments],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _init_git(root: Path) -> str:
    _git(root, "init")
    _git(root, "config", "user.name", "Asset Audit Test")
    _git(root, "config", "user.email", "asset-audit@example.invalid")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "fixture")
    return _git(root, "rev-parse", "HEAD")
