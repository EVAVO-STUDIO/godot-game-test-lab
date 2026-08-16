from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .asset_audit_png import probe_image_bytes
from .classic_adventure_vga_contract import (
    MAX_ASSETS,
    MAX_ASSET_BYTES,
    REPORT_SCHEMA_VERSION,
    ClassicAdventureVgaError,
    bounded_float,
    finding,
    load_contract,
    positive_int,
    safe_project_file,
    safe_relative_path,
)
from .classic_adventure_vga_png import decode_png_rgba, pixel_metrics


def validate_classic_adventure_vga(
    project: Path,
    contract_path: Path,
) -> dict[str, Any]:
    project_root = project.expanduser().resolve()
    if not project_root.is_dir() or project_root.is_symlink():
        raise ClassicAdventureVgaError(f"Project must be one real directory: {project}")
    contract = load_contract(contract_path.expanduser().resolve())

    native = contract.get("nativeCanvas")
    if not isinstance(native, dict):
        raise ClassicAdventureVgaError("nativeCanvas must be an object")
    native_width = positive_int(native.get("width"), "nativeCanvas.width")
    native_height = positive_int(native.get("height"), "nativeCanvas.height")
    if (native_width, native_height) not in {(320, 200), (640, 480)}:
        raise ClassicAdventureVgaError(
            "Classic adventure nativeCanvas must be 320x200 or 640x480"
        )

    raw_assets = contract.get("assets")
    if not isinstance(raw_assets, list) or not raw_assets or len(raw_assets) > MAX_ASSETS:
        raise ClassicAdventureVgaError(
            f"assets must contain between 1 and {MAX_ASSETS} records"
        )

    findings: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw_asset in enumerate(raw_assets):
        if not isinstance(raw_asset, dict):
            raise ClassicAdventureVgaError(f"assets[{index}] must be an object")
        relative_path = safe_relative_path(raw_asset.get("path"), f"assets[{index}].path")
        if relative_path in seen:
            raise ClassicAdventureVgaError(f"assets repeats path {relative_path}")
        seen.add(relative_path)
        target = safe_project_file(project_root, relative_path)
        if target.stat().st_size > MAX_ASSET_BYTES:
            findings.append(
                finding(
                    "classic-vga-asset-too-large",
                    "Asset exceeds the 64 MiB classic-art admission limit.",
                    path=relative_path,
                )
            )
            continue
        data = target.read_bytes()
        probe = probe_image_bytes(data, target.suffix)
        record: dict[str, Any] = {
            "path": relative_path,
            "role": str(raw_asset.get("role", "asset")),
            "sha256": hashlib.sha256(data).hexdigest(),
            "byteLength": len(data),
            "probe": probe.to_dict(),
        }
        if not probe.valid or probe.format != "png":
            findings.append(
                finding(
                    "classic-vga-invalid-png",
                    "Classic adventure assets must be valid PNG files.",
                    path=relative_path,
                    evidence={"probe": probe.to_dict()},
                )
            )
            records.append(record)
            continue
        try:
            width, height, rgba = decode_png_rgba(data)
        except ClassicAdventureVgaError as error:
            findings.append(
                finding(
                    "classic-vga-png-decode-failed",
                    str(error),
                    path=relative_path,
                )
            )
            records.append(record)
            continue
        metrics = pixel_metrics(width, height, rgba)
        record["pixels"] = metrics
        expected_width = positive_int(raw_asset.get("width"), f"assets[{index}].width")
        expected_height = positive_int(raw_asset.get("height"), f"assets[{index}].height")
        if (width, height) != (expected_width, expected_height):
            findings.append(
                finding(
                    "classic-vga-dimensions-mismatch",
                    "Decoded dimensions do not match the art contract.",
                    path=relative_path,
                    evidence={
                        "expected": [expected_width, expected_height],
                        "observed": [width, height],
                    },
                )
            )
        maximum_colours = positive_int(
            raw_asset.get("maximumColours", 256),
            f"assets[{index}].maximumColours",
            256,
        )
        if int(metrics["uniqueRgbaColours"]) > maximum_colours:
            findings.append(
                finding(
                    "classic-vga-palette-budget-exceeded",
                    "Decoded asset exceeds its bounded colour budget.",
                    path=relative_path,
                    evidence={
                        "maximumColours": maximum_colours,
                        "observedColours": metrics["uniqueRgbaColours"],
                    },
                )
            )
        alpha_policy = str(raw_asset.get("alpha", "opaque")).strip().lower()
        alpha_values = set(int(value) for value in metrics["alphaValues"])
        if alpha_policy == "opaque":
            if alpha_values != {255}:
                findings.append(
                    finding(
                        "classic-vga-opaque-alpha-violation",
                        "Opaque classic plate contains transparent or partial-alpha pixels.",
                        path=relative_path,
                        evidence={"alphaValues": sorted(alpha_values)},
                    )
                )
        elif alpha_policy == "binary":
            if not alpha_values.issubset({0, 255}) or alpha_values != {0, 255}:
                findings.append(
                    finding(
                        "classic-vga-binary-alpha-violation",
                        "Sprite alpha must contain genuine transparent and opaque pixels only.",
                        path=relative_path,
                        evidence={"alphaValues": sorted(alpha_values)},
                    )
                )
            if int(metrics["hiddenTransparentRgbPixels"]) != 0:
                findings.append(
                    finding(
                        "classic-vga-hidden-transparent-rgb",
                        "Fully transparent pixels must contain zero hidden RGB values.",
                        path=relative_path,
                        evidence={
                            "hiddenTransparentRgbPixels": metrics[
                                "hiddenTransparentRgbPixels"
                            ]
                        },
                    )
                )
        else:
            raise ClassicAdventureVgaError(
                f"assets[{index}].alpha must be opaque or binary"
            )
        maximum_isolated = bounded_float(
            raw_asset.get("maximumIsolatedVisiblePixelRatio", 1.0),
            f"assets[{index}].maximumIsolatedVisiblePixelRatio",
            0.0,
            1.0,
        )
        if float(metrics["isolatedVisiblePixelRatio"]) > maximum_isolated:
            findings.append(
                finding(
                    "classic-vga-isolated-pixel-noise",
                    "Visible single-pixel islands exceed the authored cluster limit.",
                    path=relative_path,
                    evidence={
                        "maximumRatio": maximum_isolated,
                        "observedRatio": metrics["isolatedVisiblePixelRatio"],
                    },
                )
            )
        records.append(record)

    report = {
        "schemaVersion": REPORT_SCHEMA_VERSION,
        "tool": "godot-game-test-lab",
        "check": "classic-adventure-vga-art",
        "status": "passed" if not findings else "failed",
        "project": str(project_root),
        "contract": str(contract_path.expanduser().resolve()),
        "nativeCanvas": {"width": native_width, "height": native_height},
        "assetCount": len(records),
        "findings": findings,
        "assets": records,
        "qualityBoundary": {
            "decodedSourcePixels": True,
            "nativeDimensions": True,
            "boundedPalette": True,
            "binaryAlpha": True,
            "hiddenTransparentRgb": True,
            "clusterNoiseProxy": True,
            "subjectiveArtApproval": False,
            "referenceTitleCopying": False,
        },
    }
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="classic-adventure-vga-qa",
        description=(
            "Validate bounded native-pixel, palette and alpha evidence for a classic adventure."
        ),
    )
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        report = validate_classic_adventure_vga(args.project, args.contract)
    except (ClassicAdventureVgaError, OSError, ValueError) as error:
        report = {
            "schemaVersion": REPORT_SCHEMA_VERSION,
            "tool": "godot-game-test-lab",
            "check": "classic-adventure-vga-art",
            "status": "blocked",
            "findings": [
                {
                    "code": "classic-vga-command-error",
                    "severity": "error",
                    "message": str(error),
                }
            ],
        }
    rendered = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if args.output is not None:
        output = args.output.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    sys.stdout.write(rendered)
    return 0 if report.get("status") == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
