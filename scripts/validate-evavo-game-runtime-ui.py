#!/usr/bin/env python3
from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise AssertionError(f"{path.relative_to(ROOT)} must be a JSON object")
    return value


def main() -> None:
    matrix_path = ROOT / "config/evavo-game-runtime-ui-matrix.v1.json"
    receipt_path = ROOT / "contracts/evavo-game-runtime-ui-receipt-v1.json"
    runner_path = ROOT / "scripts/run-evavo-game-runtime-ui.ps1"
    receipt_validator_path = ROOT / "scripts/validate-evavo-game-runtime-ui-receipt.py"
    docs_path = ROOT / "docs/EVAVO_GAME_RUNTIME_UI_MATRIX.md"

    for path in (
        matrix_path,
        receipt_path,
        runner_path,
        receipt_validator_path,
        docs_path,
    ):
        assert path.is_file(), f"Missing {path.relative_to(ROOT)}"

    matrix = load_json(matrix_path)
    receipt = load_json(receipt_path)
    runner = runner_path.read_text(encoding="utf-8")
    receipt_validator = receipt_validator_path.read_text(encoding="utf-8")

    assert matrix.get("version") == 1
    assert matrix.get("consumer") == "EVAVO-STUDIO/evavo-game-runtime"
    assert matrix.get("project_relative_path") == "."
    assert int(matrix.get("minimum_checkpoint_count", 0)) >= 10
    assert int(matrix.get("default_timeout_seconds", 0)) > 0
    assert str(matrix.get("default_evidence_root_windows", "")).startswith(
        "C:\\GodotLabEvidence\\"
    )

    scenarios = matrix.get("scenarios", [])
    assert isinstance(scenarios, list) and len(scenarios) >= 5
    expected = {
        "retro_16_9",
        "desktop_16_9",
        "desktop_ultrawide",
        "mobile_landscape",
        "mobile_portrait",
    }
    assert expected.issubset({str(item.get("id", "")) for item in scenarios})
    for scenario in scenarios:
        assert int(scenario.get("width", 0)) > 0
        assert int(scenario.get("height", 0)) > 0
        assert float(scenario.get("minimum_target_px", 0)) > 0
        insets = scenario.get("safe_insets")
        assert isinstance(insets, list) and len(insets) == 4
        assert all(float(value) >= 0 for value in insets)

    checks = set(matrix.get("required_checks", []))
    for required in (
        "deterministic_navigation",
        "focus_transitions",
        "offscreen_interactive",
        "ancestor_clipping",
        "safe_area_containment",
        "screenshot_hash",
        "screenshot_dimensions",
        "exact_source_identity",
    ):
        assert required in checks, f"Matrix missing required check: {required}"

    assert receipt.get("properties", {}).get("version", {}).get("const") == 1
    required_receipt = set(receipt.get("required", []))
    for key in (
        "runtime_sha",
        "test_lab_sha",
        "checkpoints",
        "navigation",
        "final_evidence",
        "failures",
    ):
        assert key in required_receipt, f"Receipt contract missing required key {key}"

    for marker in (
        "EVAVO_QA_ENABLED",
        "EVAVO_QA_SCREENSHOTS",
        "EVAVO_QA_OUTPUT_DIR",
        "EVAVO_QA_RUN_ID",
        "EVAVO_QA_SCENARIO",
        "EVAVO_QA_LAYOUT",
        "EVAVO_QA_MIN_TARGET",
        "EVAVO_QA_SAFE_INSETS",
        "EVAVO_QA_AUTOQUIT",
        "EVAVO_UI_CHECKPOINT",
        "EVAVO_UI_NAVIGATION",
        "EVAVO_UI_EVIDENCE",
    ):
        assert marker in runner, f"Runner missing handshake marker {marker}"

    for marker in (
        "Start-Process",
        "WaitForExit",
        "rev-parse HEAD",
        "validate-evavo-game-runtime-ui-receipt.py",
        "frame_%04d.png",
        "ffmpeg",
        "Test-Path",
        "summary.json",
    ):
        assert marker in runner, f"Runner missing governed behavior {marker}"

    ast.parse(receipt_validator)
    for marker in ("png_dimensions", "sha256_file", "geometry errors", "navigation journey"):
        assert marker in receipt_validator

    print("EVAVO game runtime UI Test Lab handshake validation passed")


if __name__ == "__main__":
    main()
