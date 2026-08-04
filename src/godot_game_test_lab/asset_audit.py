from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import struct
import sys
import unicodedata
import zlib
from typing import Any, Iterable, Sequence

AUDIT_SCHEMA_VERSION = "1.0"
AUDIT_ANALYSIS_VERSION = "1.0"
MAX_AUDIT_BYTES = 64 * 1024 * 1024
MAX_FILES = 100_000
MAX_DECODED_ALPHA_BYTES = 256 * 1024 * 1024

ART_EXTENSIONS = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".avif",
        ".gif",
        ".bmp",
        ".tga",
        ".tif",
        ".tiff",
        ".svg",
        ".exr",
        ".hdr",
        ".apng",
        ".mp4",
        ".webm",
        ".mov",
        ".mkv",
        ".ttf",
        ".otf",
        ".woff",
        ".woff2",
        ".tres",
        ".res",
        ".tscn",
        ".scn",
        ".import",
        ".godot",
        ".psd",
        ".ase",
        ".aseprite",
        ".kra",
        ".xcf",
        ".ai",
        ".afdesign",
        ".blend",
        ".json",
        ".yaml",
        ".yml",
        ".toml",
        ".xml",
        ".atlas",
    }
)
IGNORED_DIRECTORIES = frozenset(
    {".git", ".godot", ".next", "node_modules", "dist", "build", "coverage", ".cache", ".turbo"}
)
HEX_64 = re.compile(r"^[0-9a-f]{64}$")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _portable_relative(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("asset path must be a string")
    candidate = unicodedata.normalize("NFC", value.replace("\\", "/").strip())
    if not candidate or candidate.startswith("/") or re.match(r"^[A-Za-z]:", candidate):
        raise ValueError(f"asset path is absolute or empty: {value!r}")
    parts = PurePosixPath(candidate).parts
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"asset path traverses outside the repository: {value!r}")
    return PurePosixPath(*parts).as_posix()


def _safe_project_file(project: Path, relative: str) -> Path:
    target = project.joinpath(*PurePosixPath(relative).parts)
    try:
        resolved = target.resolve(strict=True)
    except FileNotFoundError as error:
        raise ValueError(f"asset file is missing: {relative}") from error
    if project != resolved and project not in resolved.parents:
        raise ValueError(f"asset path resolves outside the project: {relative}")
    if target.is_symlink() or not resolved.is_file():
        raise ValueError(f"asset path is not a regular in-project file: {relative}")
    return resolved


def _as_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _as_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be an array")
    return value


def _read_audit(path: Path) -> tuple[dict[str, Any], str]:
    resolved = path.expanduser().resolve(strict=True)
    if not resolved.is_file() or resolved.is_symlink():
        raise ValueError("audit path must be a regular file")
    if resolved.stat().st_size > MAX_AUDIT_BYTES:
        raise ValueError(f"audit exceeds the bounded {MAX_AUDIT_BYTES}-byte limit")
    raw = resolved.read_bytes()
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"audit is not valid UTF-8 JSON: {error}") from error
    return _as_object(document, "audit"), hashlib.sha256(raw).hexdigest()


def _iter_current_art_files(project: Path) -> Iterable[str]:
    count = 0
    stack = [project]
    while stack:
        directory = stack.pop()
        entries = sorted(directory.iterdir(), key=lambda item: item.name.casefold())
        for entry in entries:
            if entry.is_symlink():
                continue
            if entry.is_dir():
                if entry.name not in IGNORED_DIRECTORIES:
                    stack.append(entry)
                continue
            if not entry.is_file():
                continue
            count += 1
            if count > MAX_FILES:
                raise ValueError(f"project exceeds the bounded {MAX_FILES}-file inventory limit")
            if entry.suffix.lower() in ART_EXTENSIONS:
                yield entry.relative_to(project).as_posix()


def _paeth(left: int, above: int, upper_left: int) -> int:
    estimate = left + above - upper_left
    distances = (abs(estimate - left), abs(estimate - above), abs(estimate - upper_left))
    if distances[0] <= distances[1] and distances[0] <= distances[2]:
        return left
    if distances[1] <= distances[2]:
        return above
    return upper_left


def _png_alpha(path: Path) -> tuple[str, int | None, int | None, list[str]]:
    data = path.read_bytes()
    if len(data) < 33 or data[:8] != b"\x89PNG\r\n\x1a\n":
        return "unknown", None, None, ["PNG signature is invalid"]
    offset = 8
    width = height = bit_depth = colour_type = None
    interlace = 0
    idat: list[bytes] = []
    has_trns = False
    while offset + 12 <= len(data):
        length = struct.unpack_from(">I", data, offset)[0]
        chunk_type = data[offset + 4 : offset + 8]
        start = offset + 8
        end = start + length
        if end + 4 > len(data):
            return "unknown", width, height, ["PNG chunk exceeds file bounds"]
        if chunk_type == b"IHDR" and length >= 13:
            width, height, bit_depth, colour_type, _, _, interlace = struct.unpack_from(">IIBBBBB", data, start)
        elif chunk_type == b"IDAT":
            idat.append(data[start:end])
        elif chunk_type == b"tRNS":
            has_trns = True
        offset = end + 4
        if chunk_type == b"IEND":
            break
    if not width or not height or bit_depth is None or colour_type is None:
        return "unknown", width, height, ["PNG IHDR is incomplete"]
    if colour_type not in {4, 6}:
        return ("unknown" if has_trns else "none"), width, height, (
            ["indexed tRNS transparency requires decoded-image QA"] if has_trns else []
        )
    if interlace != 0 or bit_depth not in {8, 16}:
        return "unknown", width, height, ["PNG alpha layout is unsupported by the bounded independent probe"]
    channels = 4 if colour_type == 6 else 2
    sample_bytes = bit_depth // 8
    bytes_per_pixel = channels * sample_bytes
    row_bytes = width * bytes_per_pixel
    expected = height * (row_bytes + 1)
    if expected > MAX_DECODED_ALPHA_BYTES:
        return "unknown", width, height, ["decoded PNG alpha exceeds the bounded 256 MiB limit"]
    try:
        decompressor = zlib.decompressobj()
        decoded = decompressor.decompress(b"".join(idat), expected + 1)
        if len(decoded) > expected or decompressor.unconsumed_tail:
            return "unknown", width, height, ["decoded PNG alpha exceeds the declared canvas"]
        decoded += decompressor.flush()
    except (zlib.error, ValueError) as error:
        return "unknown", width, height, [f"PNG alpha decompression failed: {error}"]
    if len(decoded) < expected:
        return "unknown", width, height, ["PNG scanline data is shorter than the declared canvas"]
    previous = bytearray(row_bytes)
    current = bytearray(row_bytes)
    cursor = 0
    maximum = 65535 if bit_depth == 16 else 255
    alpha_offset = (3 if colour_type == 6 else 1) * sample_bytes
    visible = False
    non_opaque = False
    opaque = False
    for _ in range(height):
        filter_type = decoded[cursor]
        cursor += 1
        for index in range(row_bytes):
            encoded = decoded[cursor + index]
            left = current[index - bytes_per_pixel] if index >= bytes_per_pixel else 0
            above = previous[index]
            upper_left = previous[index - bytes_per_pixel] if index >= bytes_per_pixel else 0
            if filter_type == 0:
                value = encoded
            elif filter_type == 1:
                value = encoded + left
            elif filter_type == 2:
                value = encoded + above
            elif filter_type == 3:
                value = encoded + ((left + above) // 2)
            elif filter_type == 4:
                value = encoded + _paeth(left, above, upper_left)
            else:
                return "unknown", width, height, [f"PNG scanline filter {filter_type} is unsupported"]
            current[index] = value & 0xFF
        cursor += row_bytes
        for pixel in range(width):
            alpha_index = pixel * bytes_per_pixel + alpha_offset
            alpha = (
                (current[alpha_index] << 8) | current[alpha_index + 1]
                if bit_depth == 16
                else current[alpha_index]
            )
            visible |= alpha > 0
            non_opaque |= alpha < maximum
            opaque |= alpha == maximum
        previous[:] = current
    if not visible:
        return "fully-transparent", width, height, []
    if non_opaque:
        return "meaningful", width, height, []
    if opaque:
        return "opaque-channel", width, height, []
    return "unknown", width, height, []


def _independent_image_probe(path: Path) -> tuple[str, int | None, int | None, list[str]]:
    extension = path.suffix.lower()
    if extension == ".png":
        return _png_alpha(path)
    return "unknown", None, None, [
        f"{extension or 'unknown'} requires decoded runtime or media-toolchain verification"
    ]


def _finding(
    code: str,
    severity: str,
    message: str,
    *,
    path: str | None = None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    value: dict[str, Any] = {"code": code, "severity": severity, "message": message}
    if path is not None:
        value["path"] = path
    if evidence:
        value["evidence"] = evidence
    return value


def validate_asset_audit(
    project: Path,
    audit_path: Path,
    *,
    allow_unrecorded_assets: bool = False,
    allow_missing_references: bool = False,
    allow_animation_gaps: bool = False,
    allow_unverified_alpha: bool = False,
) -> dict[str, Any]:
    project_root = project.expanduser().resolve(strict=True)
    if not project_root.is_dir() or not (project_root / "project.godot").is_file():
        raise ValueError("project must resolve to a Godot repository containing project.godot")
    audit, audit_sha256 = _read_audit(audit_path)
    findings: list[dict[str, Any]] = []

    if audit.get("schemaVersion") != AUDIT_SCHEMA_VERSION:
        findings.append(_finding("audit-schema-version", "error", "Unsupported Art Studio audit schemaVersion."))
    if audit.get("analysisVersion") != AUDIT_ANALYSIS_VERSION:
        findings.append(_finding("audit-analysis-version", "error", "Unsupported Art Studio analysisVersion."))

    art_rows = _as_list(audit.get("artFiles"), "artFiles")
    if len(art_rows) > MAX_FILES:
        raise ValueError(f"audit contains more than {MAX_FILES} art files")
    audited_paths: set[str] = set()
    valid_rows = 0
    identity_failures = 0
    alpha_failures = 0

    for index, raw_row in enumerate(art_rows):
        try:
            row = _as_object(raw_row, f"artFiles[{index}]")
            relative = _portable_relative(row.get("path"))
            if relative in audited_paths:
                raise ValueError(f"duplicate audit path: {relative}")
            audited_paths.add(relative)
            target = _safe_project_file(project_root, relative)
            expected_bytes = row.get("sizeBytes")
            expected_sha = row.get("sha256")
            if not isinstance(expected_bytes, int) or expected_bytes < 0:
                raise ValueError("sizeBytes must be a non-negative integer")
            if not isinstance(expected_sha, str) or not HEX_64.fullmatch(expected_sha):
                raise ValueError("sha256 must be a lowercase 64-character digest")
            actual_bytes = target.stat().st_size
            actual_sha = _sha256(target)
            if actual_bytes != expected_bytes or actual_sha != expected_sha:
                identity_failures += 1
                findings.append(
                    _finding(
                        "asset-identity-mismatch",
                        "error",
                        "Current bytes do not match the audited asset identity.",
                        path=relative,
                        evidence={
                            "expectedBytes": expected_bytes,
                            "actualBytes": actual_bytes,
                            "expectedSha256": expected_sha,
                            "actualSha256": actual_sha,
                        },
                    )
                )
                continue

            policy = row.get("transparencyPolicy")
            image = row.get("image")
            if policy == "require-meaningful-alpha":
                if not isinstance(image, dict):
                    alpha_failures += 1
                    findings.append(
                        _finding(
                            "alpha-evidence-missing",
                            "error",
                            "Alpha-required asset has no image evidence.",
                            path=relative,
                        )
                    )
                else:
                    audited_alpha = image.get("alphaUsage")
                    independent_alpha, width, height, warnings = _independent_image_probe(target)
                    if independent_alpha == "unknown" and allow_unverified_alpha:
                        findings.append(
                            _finding(
                                "alpha-runtime-verification-required",
                                "warning",
                                "Compressed or unsupported alpha remains for native runtime verification.",
                                path=relative,
                                evidence={"auditedAlpha": audited_alpha, "warnings": warnings},
                            )
                        )
                    elif independent_alpha != "meaningful":
                        alpha_failures += 1
                        findings.append(
                            _finding(
                                "meaningful-alpha-not-proven",
                                "error",
                                "Role requires meaningful transparency and the independent probe did not prove it.",
                                path=relative,
                                evidence={
                                    "auditedAlpha": audited_alpha,
                                    "independentAlpha": independent_alpha,
                                    "width": width,
                                    "height": height,
                                    "warnings": warnings,
                                },
                            )
                        )
                    elif audited_alpha != "meaningful":
                        alpha_failures += 1
                        findings.append(
                            _finding(
                                "audit-alpha-disagrees",
                                "error",
                                "Independent PNG alpha is meaningful but the audit did not record that state.",
                                path=relative,
                            )
                        )
            valid_rows += 1
        except ValueError as error:
            findings.append(
                _finding(
                    "invalid-art-row",
                    "error",
                    str(error),
                    evidence={"rowIndex": index},
                )
            )

    current_paths = set(_iter_current_art_files(project_root))
    unrecorded = sorted(current_paths - audited_paths)
    absent_from_current = sorted(audited_paths - current_paths)
    if unrecorded:
        findings.append(
            _finding(
                "unrecorded-art-files",
                "warning" if allow_unrecorded_assets else "error",
                "Current project contains art or resource files that are absent from the audit.",
                evidence={"count": len(unrecorded), "sample": unrecorded[:50]},
            )
        )
    if absent_from_current:
        findings.append(
            _finding(
                "audited-files-absent",
                "error",
                "Audit contains paths that no longer exist in the current project inventory.",
                evidence={"count": len(absent_from_current), "sample": absent_from_current[:50]},
            )
        )

    missing_references = _as_list(audit.get("missingAssetReferences", []), "missingAssetReferences")
    if missing_references:
        findings.append(
            _finding(
                "missing-asset-references",
                "warning" if allow_missing_references else "error",
                "Source or resource files reference media absent from the audited repository.",
                evidence={"count": len(missing_references), "sample": missing_references[:25]},
            )
        )

    animation_families = _as_list(audit.get("animationFamilies", []), "animationFamilies")
    gap_count = 0
    inconsistent_count = 0
    for index, raw_family in enumerate(animation_families):
        family = _as_object(raw_family, f"animationFamilies[{index}]")
        missing = _as_list(family.get("missingFrameIndices", []), "missingFrameIndices")
        if missing:
            gap_count += 1
        if family.get("consistentDimensions") is False:
            inconsistent_count += 1
    if gap_count:
        findings.append(
            _finding(
                "animation-frame-gaps",
                "warning" if allow_animation_gaps else "error",
                "One or more numbered animation families have missing frame indices.",
                evidence={"familyCount": gap_count},
            )
        )
    if inconsistent_count:
        findings.append(
            _finding(
                "animation-canvas-mismatch",
                "error",
                "One or more animation families contain inconsistent frame canvases.",
                evidence={"familyCount": inconsistent_count},
            )
        )

    audit_summary = audit.get("auditSummary")
    if isinstance(audit_summary, dict) and audit_summary.get("blockingFindings", 0):
        findings.append(
            _finding(
                "art-studio-blocking-findings",
                "error",
                "Art Studio audit still contains blocking findings.",
                evidence={"count": audit_summary.get("blockingFindings")},
            )
        )

    errors = sum(1 for item in findings if item["severity"] == "error")
    warnings = sum(1 for item in findings if item["severity"] == "warning")
    return {
        "schemaVersion": "1.0",
        "tool": "godot-game-test-lab",
        "check": "art-studio-asset-audit",
        "status": "passed" if errors == 0 else "failed",
        "project": str(project_root),
        "auditPath": str(audit_path.expanduser().resolve()),
        "auditSha256": audit_sha256,
        "policy": {
            "allowUnrecordedAssets": allow_unrecorded_assets,
            "allowMissingReferences": allow_missing_references,
            "allowAnimationGaps": allow_animation_gaps,
            "allowUnverifiedAlpha": allow_unverified_alpha,
        },
        "summary": {
            "auditedRows": len(art_rows),
            "validRows": valid_rows,
            "currentArtFiles": len(current_paths),
            "identityFailures": identity_failures,
            "alphaFailures": alpha_failures,
            "unrecordedFiles": len(unrecorded),
            "missingReferences": len(missing_references),
            "animationFamilies": len(animation_families),
            "animationFamiliesWithGaps": gap_count,
            "animationFamiliesWithCanvasMismatch": inconsistent_count,
            "errors": errors,
            "warnings": warnings,
        },
        "findings": findings,
        "truthBoundaries": [
            "This check proves current file identity against one Art Studio audit; it does not approve artistic quality.",
            "Static reference analysis cannot prove dynamic runtime ownership or deletion safety.",
            "Unsupported or compressed alpha requires native or decoded media evidence unless explicitly allowed.",
            "A passing source check does not replace Godot import, runtime rendering, visual captures or human review.",
        ],
    }


def _write_json(value: object, output: Path | None) -> None:
    content = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if output is not None:
        destination = output.expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")
    sys.stdout.write(content)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="godot-lab-asset-audit",
        description="Validate an EVAVO Art Studio bulk asset audit against current Godot project bytes.",
    )
    parser.add_argument("project", type=Path)
    parser.add_argument("audit", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--allow-unrecorded-assets", action="store_true")
    parser.add_argument("--allow-missing-references", action="store_true")
    parser.add_argument("--allow-animation-gaps", action="store_true")
    parser.add_argument("--allow-unverified-alpha", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        report = validate_asset_audit(
            args.project,
            args.audit,
            allow_unrecorded_assets=args.allow_unrecorded_assets,
            allow_missing_references=args.allow_missing_references,
            allow_animation_gaps=args.allow_animation_gaps,
            allow_unverified_alpha=args.allow_unverified_alpha,
        )
    except (OSError, ValueError) as error:
        report = {
            "schemaVersion": "1.0",
            "tool": "godot-game-test-lab",
            "check": "art-studio-asset-audit",
            "status": "failed",
            "summary": {"errors": 1, "warnings": 0},
            "findings": [
                _finding("asset-audit-validation-error", "error", str(error))
            ],
        }
    _write_json(report, args.output)
    return 0 if report.get("status") == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
