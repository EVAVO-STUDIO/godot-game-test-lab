#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path
from typing import Any

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def load_object(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise AssertionError(f"{path} must contain a JSON object")
    return value


def png_dimensions(path: Path) -> tuple[int, int]:
    with path.open("rb") as handle:
        header = handle.read(24)
    if len(header) < 24 or header[:8] != PNG_SIGNATURE or header[12:16] != b"IHDR":
        raise AssertionError(f"{path} is not a valid PNG with an IHDR header")
    return struct.unpack(">II", header[16:24])


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require(condition: bool, message: str, failures: list[str]) -> None:
    if not condition:
        failures.append(message)


def validate_receipt(receipt: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    viewport = receipt.get("viewport", {})
    checkpoints = receipt.get("checkpoints", [])
    navigation = receipt.get("navigation", {})
    final_evidence = receipt.get("final_evidence", {})
    godot = receipt.get("godot", {})
    artifacts = receipt.get("artifacts", {})

    require(receipt.get("version") == 1, "receipt version must be 1", failures)
    require(receipt.get("status") == "passed", "receipt status is not passed", failures)
    require(not receipt.get("failures"), "receipt contains runner failures", failures)
    require(isinstance(checkpoints, list), "checkpoints must be an array", failures)
    if not isinstance(checkpoints, list):
        checkpoints = []

    minimum = int(receipt.get("minimum_checkpoint_count", 1))
    require(len(checkpoints) >= minimum, f"expected at least {minimum} checkpoints", failures)
    require(
        isinstance(navigation, dict) and navigation.get("passed") is True,
        "navigation journey did not pass",
        failures,
    )
    require(
        isinstance(final_evidence, dict) and final_evidence.get("passed") is True,
        "final runtime evidence did not pass",
        failures,
    )
    require(int(godot.get("import_exit_code", -1)) == 0, "Godot import failed", failures)
    require(int(godot.get("exit_code", -1)) == 0, "Godot journey process failed", failures)
    require(godot.get("timed_out") is False, "Godot journey timed out", failures)

    expected_width = int(viewport.get("width", 0))
    expected_height = int(viewport.get("height", 0))
    screenshot_paths: list[str] = []

    for index, checkpoint in enumerate(checkpoints):
        if not isinstance(checkpoint, dict):
            failures.append(f"checkpoint {index} is not an object")
            continue
        checkpoint_id = str(checkpoint.get("checkpoint_id", f"checkpoint-{index}"))
        geometry = checkpoint.get("geometry", {})
        summary = geometry.get("summary", {}) if isinstance(geometry, dict) else {}
        require(
            int(summary.get("error_count", -1)) == 0,
            f"{checkpoint_id}: geometry errors were reported",
            failures,
        )

        metadata = checkpoint.get("metadata", {})
        require_focus = (
            bool(metadata.get("require_focus", False))
            if isinstance(metadata, dict)
            else False
        )
        if require_focus:
            focus = checkpoint.get("focus", {})
            require(
                isinstance(focus, dict) and bool(focus.get("present", False)),
                f"{checkpoint_id}: required focus owner is missing",
                failures,
            )

        evidence = checkpoint.get("evidence", {})
        if not isinstance(evidence, dict):
            failures.append(f"{checkpoint_id}: screenshot evidence is not an object")
            continue
        screenshot_path = str(evidence.get("screenshot_path", ""))
        require(bool(screenshot_path), f"{checkpoint_id}: screenshot path is missing", failures)
        if not screenshot_path:
            continue

        screenshot = Path(screenshot_path)
        screenshot_paths.append(str(screenshot))
        require(screenshot.is_file(), f"{checkpoint_id}: screenshot file does not exist", failures)
        if not screenshot.is_file():
            continue

        actual_bytes = screenshot.stat().st_size
        actual_sha = sha256_file(screenshot)
        try:
            actual_width, actual_height = png_dimensions(screenshot)
        except AssertionError as error:
            failures.append(str(error))
            continue

        require(
            actual_bytes == int(evidence.get("bytes", -1)),
            f"{checkpoint_id}: screenshot byte count mismatch",
            failures,
        )
        require(
            actual_sha == str(evidence.get("sha256", "")).lower(),
            f"{checkpoint_id}: screenshot SHA-256 mismatch",
            failures,
        )
        require(
            actual_width == int(evidence.get("width", -1)),
            f"{checkpoint_id}: screenshot width metadata mismatch",
            failures,
        )
        require(
            actual_height == int(evidence.get("height", -1)),
            f"{checkpoint_id}: screenshot height metadata mismatch",
            failures,
        )
        require(
            actual_width == expected_width and actual_height == expected_height,
            f"{checkpoint_id}: screenshot dimensions {actual_width}x{actual_height} "
            f"do not match requested {expected_width}x{expected_height}",
            failures,
        )

    declared_screenshots = artifacts.get("screenshots", [])
    if isinstance(declared_screenshots, list):
        require(
            sorted(map(str, declared_screenshots)) == sorted(screenshot_paths),
            "artifact screenshot list does not match checkpoint evidence",
            failures,
        )
    else:
        failures.append("artifacts.screenshots must be an array")

    return failures


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate one EVAVO runtime UI receipt."
    )
    parser.add_argument("receipt", type=Path)
    args = parser.parse_args()

    receipt = load_object(args.receipt)
    failures = validate_receipt(receipt)
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1
    print(f"EVAVO runtime UI receipt passed: {args.receipt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
