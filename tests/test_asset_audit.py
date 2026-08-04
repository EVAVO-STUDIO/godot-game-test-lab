from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
import zlib

from godot_game_test_lab.asset_audit import validate_asset_audit


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


def _row(
    root: Path,
    relative: str,
    *,
    policy: str = "review-required",
    alpha: str | None = None,
) -> dict[str, object]:
    target = root / relative
    row: dict[str, object] = {
        "path": relative,
        "extension": target.suffix.lower(),
        "sizeBytes": target.stat().st_size,
        "category": "image" if target.suffix.lower() == ".png" else "engine-resource",
        "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "role": "ui-icon" if policy == "require-meaningful-alpha" else "metadata",
        "transparencyPolicy": policy,
        "referenceCount": 0,
        "referencedBy": [],
        "optimization": {
            "masterFormat": "png",
            "runtimeFormat": "webp",
            "compression": "lossless",
            "allowUpscale": False,
            "notes": [],
        },
        "findings": [],
    }
    if alpha is not None:
        row["image"] = {
            "format": "png",
            "width": 2,
            "height": 1,
            "hasAlphaChannel": True,
            "alphaUsage": alpha,
            "probeComplete": True,
            "warnings": [],
        }
    return row


def _audit(root: Path, rows: list[dict[str, object]]) -> dict[str, object]:
    return {
        "schemaVersion": "1.0",
        "analysisVersion": "1.0",
        "root": str(root),
        "projectName": "Audit",
        "engine": "godot",
        "filesScanned": len(rows),
        "artFiles": rows,
        "extensionCounts": {},
        "categoryCounts": {},
        "signals": [],
        "gaps": [],
        "truncated": False,
        "duplicateGroups": [],
        "animationFamilies": [],
        "missingAssetReferences": [],
        "cleanupCandidates": [],
        "auditSummary": {"blockingFindings": 0},
        "auditRules": [],
    }


def _write_audit(path: Path, value: dict[str, object]) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def _project(tmp_path: Path, *, opaque: bool = False) -> tuple[Path, Path]:
    root = tmp_path / "game"
    root.mkdir()
    (root / "project.godot").write_text(
        '[application]\nconfig/name="Audit"\n', encoding="utf-8"
    )
    icon = root / "assets" / "art" / "ui" / "icons" / "cargo.png"
    icon.parent.mkdir(parents=True)
    alpha = 255 if opaque else 0
    icon.write_bytes(
        _png(2, 1, bytes([255, 255, 255, 255, 255, 255, 255, alpha]))
    )
    audit_path = tmp_path / "audit.json"
    rows = [
        _row(root, "project.godot"),
        _row(
            root,
            "assets/art/ui/icons/cargo.png",
            policy="require-meaningful-alpha",
            alpha="opaque-channel" if opaque else "meaningful",
        ),
    ]
    _write_audit(audit_path, _audit(root, rows))
    return root, audit_path


def test_valid_audit_passes(tmp_path: Path) -> None:
    root, audit_path = _project(tmp_path)
    report = validate_asset_audit(root, audit_path)
    assert report["status"] == "passed"
    assert report["summary"]["identityFailures"] == 0
    assert report["summary"]["alphaFailures"] == 0


def test_changed_bytes_fail_identity(tmp_path: Path) -> None:
    root, audit_path = _project(tmp_path)
    (root / "assets/art/ui/icons/cargo.png").write_bytes(b"changed")
    report = validate_asset_audit(root, audit_path)
    assert report["status"] == "failed"
    assert report["summary"]["identityFailures"] == 1


def test_unrecorded_asset_fails_closed(tmp_path: Path) -> None:
    root, audit_path = _project(tmp_path)
    extra = root / "assets" / "art" / "ui" / "icons" / "extra.png"
    extra.write_bytes(_png(1, 1, bytes([255, 255, 255, 0])))
    report = validate_asset_audit(root, audit_path)
    assert report["status"] == "failed"
    assert report["summary"]["unrecordedFiles"] == 1
    allowed = validate_asset_audit(root, audit_path, allow_unrecorded_assets=True)
    assert allowed["status"] == "passed"


def test_opaque_alpha_required_asset_fails(tmp_path: Path) -> None:
    root, audit_path = _project(tmp_path, opaque=True)
    report = validate_asset_audit(root, audit_path)
    assert report["status"] == "failed"
    assert report["summary"]["alphaFailures"] == 1
