#!/usr/bin/env python3
"""Fail closed when the classic-adventure VGA source-art gate drifts."""

from __future__ import annotations

import sys
from pathlib import Path, PurePosixPath

ROOT = Path.cwd().resolve(strict=True)
MAXIMUM_SOURCE_BYTES = 1_000_000
ERRORS: list[str] = []
FILES = {
    "checker": "src/godot_game_test_lab/classic_adventure_vga.py",
    "contract": "src/godot_game_test_lab/classic_adventure_vga_contract.py",
    "png": "src/godot_game_test_lab/classic_adventure_vga_png.py",
    "script": "scripts/classic_adventure_vga_qa.py",
    "tests": "tests/test_classic_adventure_vga.py",
    "docs": "docs/CLASSIC_ADVENTURE_VGA_QA.md",
}


def fail(message: str) -> None:
    ERRORS.append(message)


def read_text(relative: str) -> str:
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts:
        raise RuntimeError(f"CLASSIC_VGA_SOURCE_PATH_INVALID:{relative}")
    candidate = ROOT.joinpath(*pure.parts)
    if not candidate.is_file() or candidate.is_symlink():
        raise RuntimeError(f"CLASSIC_VGA_SOURCE_FILE_INVALID:{relative}")
    if candidate.resolve(strict=True) != candidate.absolute():
        raise RuntimeError(f"CLASSIC_VGA_SOURCE_FILE_NONCANONICAL:{relative}")
    if candidate.stat().st_size > MAXIMUM_SOURCE_BYTES:
        raise RuntimeError(f"CLASSIC_VGA_SOURCE_FILE_TOO_LARGE:{relative}")
    source = candidate.read_text(encoding="utf-8")
    if source.startswith("\ufeff"):
        raise RuntimeError(f"CLASSIC_VGA_SOURCE_FILE_BOM:{relative}")
    return source


def require_tokens(label: str, source: str, tokens: tuple[str, ...]) -> None:
    for token in tokens:
        if token not in source:
            fail(f"{label} is missing required token: {token}")


def forbid_tokens(label: str, source: str, tokens: tuple[str, ...]) -> None:
    for token in tokens:
        if token in source:
            fail(f"{label} contains prohibited material: {token}")


def main() -> int:
    try:
        sources = {name: read_text(path) for name, path in FILES.items()}
    except (OSError, UnicodeError, RuntimeError) as error:
        print(f"Classic-adventure VGA toolchain check failed: {error}", file=sys.stderr)
        return 1

    require_tokens(
        "classic-adventure VGA checker",
        sources["checker"],
        (
            "validate_classic_adventure_vga",
            '"classic-adventure-vga-art"',
            '"decodedSourcePixels": True',
            '"subjectiveArtApproval": False',
            '"referenceTitleCopying": False',
            "maximumIsolatedVisiblePixelRatio",
        ),
    )
    require_tokens(
        "classic-adventure VGA contract",
        sources["contract"],
        (
            'CONTRACT_SCHEMA_VERSION = "1.0"',
            "MAX_ASSETS = 256",
            "MAX_DECODED_BYTES",
            "safe_relative_path",
            "safe_project_file",
        ),
    )
    require_tokens(
        "classic-adventure VGA PNG decoder",
        sources["png"],
        (
            "PNG chunk CRC is invalid",
            "PNG IDAT chunks must remain consecutive",
            "Indexed PNG is missing its PLTE palette",
            "decode_png_rgba",
            "pixel_metrics",
            "_paeth",
        ),
    )
    require_tokens(
        "classic-adventure VGA focused tests",
        sources["tests"],
        (
            "test_classic_adventure_vga_accepts_bounded_palette_and_binary_alpha",
            "test_classic_adventure_vga_rejects_partial_alpha",
            "test_classic_adventure_vga_rejects_palette_overflow",
            "test_classic_adventure_vga_accepts_indexed_room_and_binary_actor",
        ),
    )
    require_tokens(
        "classic-adventure VGA documentation",
        sources["docs"],
        (
            "Linux sandbox integration",
            "Quality boundary",
            "commercial game assets",
            "binary alpha",
        ),
    )
    require_tokens(
        "classic-adventure VGA script",
        sources["script"],
        (
            "godot_game_test_lab.classic_adventure_vga import main",
            "raise SystemExit(main())",
        ),
    )
    for label in ("checker", "contract", "png", "script"):
        forbid_tokens(
            f"classic-adventure VGA {label}",
            sources[label],
            (
                "subprocess",
                "requests.",
                "urllib.request",
                "git push",
                "os.system(",
                "shell=True",
            ),
        )

    if len(sources["checker"].encode("utf-8")) > 48_000:
        fail("classic-adventure VGA checker exceeds its bounded source limit")
    if len(sources["png"].encode("utf-8")) > 48_000:
        fail("classic-adventure VGA PNG decoder exceeds its bounded source limit")

    if ERRORS:
        print("Classic-adventure VGA toolchain check failed:", file=sys.stderr)
        print(file=sys.stderr)
        for error in ERRORS:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("Classic-adventure VGA toolchain check passed.")
    print("- indexed/RGB/RGBA PNG decoding and bounded palette evidence remain governed")
    print("- native dimensions, strict alpha and hidden-RGB checks remain fail-closed")
    print("- source-art QA remains read-only and does not grant creative approval")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
