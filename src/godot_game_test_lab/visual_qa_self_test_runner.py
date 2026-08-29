from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from . import visual_qa_self_test as base
from .native_qa_profile_visual import normalize_profile


def _exact_source_digest(lab_root: Path) -> str:
    digest = hashlib.sha256()
    digest.update(base._source_digest(lab_root).encode("ascii"))
    digest.update(b"\0")
    digest.update(Path(__file__).read_bytes())
    return digest.hexdigest()


def _normalized_fixture_journey(profile_path: Path) -> dict[str, Any]:
    profile = base._read_json_object(profile_path, "visual QA fixture profile")
    normalized = normalize_profile(profile)
    journeys = base._safe_list(normalized.get("journeys"), "normalized journeys")
    if len(journeys) != 1 or not isinstance(journeys[0], dict):
        raise base.VisualQaSelfTestError(
            "Visual QA fixture profile must normalize to exactly one journey"
        )
    return journeys[0]


def run_visual_qa_self_test(args: argparse.Namespace) -> dict[str, Any]:
    lab_root = args.lab_root.expanduser().resolve(strict=True)
    fixture_root = lab_root / "fixtures" / "visual-qa-overlap"
    driver = lab_root / "scripts" / "godot_input_journey.gd"
    profile_path = fixture_root / "native-agent-qa.profile.json"
    for required in (
        fixture_root / "project.godot",
        fixture_root / "main.tscn",
        driver,
        profile_path,
    ):
        if not required.is_file():
            raise base.VisualQaSelfTestError(
                f"Required self-test file is missing: {required}"
            )

    artifacts_root = base._resolve_artifact_root(args.artifacts, lab_root)
    source_sha256 = _exact_source_digest(lab_root)
    godot = base._resolve_godot(args.godot)
    checked_at = datetime.now(UTC)
    latest_receipt = artifacts_root / "latest-receipt.json"
    if godot is None:
        receipt = {
            "schemaVersion": "2.0",
            "status": "source-present",
            "truth": "source-present",
            "ready": False,
            "checkedAt": checked_at.isoformat(),
            "sourceSha256": source_sha256,
            "reason": "Godot executable was not found",
            "requiredRuntime": "Godot 4.6.2 or a compatible Godot 4 runtime",
        }
        base._write_atomic_json(latest_receipt, receipt)
        return receipt

    run_id = (
        f"godot-visual-qa-{checked_at.strftime('%Y%m%dT%H%M%SZ')}"
        f"-{uuid.uuid4().hex[:8]}"
    )
    run_root = artifacts_root / "runs" / run_id
    checkpoints = run_root / "checkpoints"
    run_root.mkdir(parents=True, exist_ok=False)
    checkpoints.mkdir(parents=True, exist_ok=False)
    journey_path = run_root / "journey.normalized.json"
    journey_path.write_text(
        base._canonical_json(_normalized_fixture_journey(profile_path)),
        encoding="utf-8",
    )
    report_path = run_root / "journey-report.json"
    stdout_path = run_root / "godot.stdout.log"
    stderr_path = run_root / "godot.stderr.log"

    environment = os.environ.copy()
    environment.update(
        {
            "EVAVO_JOURNEY_PATH": str(journey_path),
            "EVAVO_JOURNEY_REPORT": str(report_path),
            "EVAVO_JOURNEY_CHECKPOINT_ROOT": str(checkpoints),
            "EVAVO_JOURNEY_SCENE": "res://main.tscn",
            "EVAVO_JOURNEY_MAX_FRAMES": "180",
        }
    )
    command = [
        str(godot),
        "--path",
        str(fixture_root),
        "--rendering-method",
        "gl_compatibility",
        "--rendering-driver",
        "opengl3",
        "--resolution",
        "640x360",
    ]
    if args.headless:
        command.append("--headless")
    command.extend(["--script", str(driver)])
    exit_code = base._run_process(
        command,
        cwd=fixture_root,
        environment=environment,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        timeout=args.timeout,
    )

    report = base._read_json_object(report_path, "Godot journey report")
    if report.get("journeyId") != "visual-qa-overlap":
        raise base.VisualQaSelfTestError(
            "Godot driver did not execute the normalized fixture journey"
        )
    ui = base._safe_mapping(
        report.get("ui"), "Godot journey report UI telemetry"
    )
    detected: dict[str, int] = {}
    for key in sorted(base._REQUIRED_LAYOUT_KEYS):
        count = len(base._safe_list(ui.get(key), f"UI telemetry {key}"))
        detected[key] = count
        if count < 1:
            raise base.VisualQaSelfTestError(
                f"Deliberate fixture did not produce required finding: {key}"
            )
    if any(
        bool(ui.get(key, False))
        for key in (
            "controlRecordsTruncated",
            "interactiveRecordsTruncated",
            "pairAnalysisTruncated",
        )
    ):
        raise base.VisualQaSelfTestError("Godot layout telemetry was truncated")

    screenshot_path = checkpoints / "deliberate-defects.png"
    if not screenshot_path.is_file():
        screenshot_path = checkpoints / "final.png"
    if not screenshot_path.is_file():
        raise base.VisualQaSelfTestError("Godot did not retain a checkpoint PNG")
    width, height, rgba = base._decode_png_rgba(screenshot_path)
    if (width, height) != (640, 360):
        raise base.VisualQaSelfTestError(
            f"Godot checkpoint dimensions are {width}x{height}, expected 640x360"
        )
    pixel_statistics = base._pixel_statistics(rgba, width, height)
    if not pixel_statistics["nonUniform"] or not pixel_statistics["notAllBlack"]:
        raise base.VisualQaSelfTestError(
            "Godot checkpoint did not contain a non-uniform visible render"
        )
    checkpoint_ui = base._safe_list(report.get("checkpointUi", []), "checkpointUi")
    if not checkpoint_ui:
        raise base.VisualQaSelfTestError(
            "Godot did not retain checkpoint UI telemetry"
        )

    evidence = []
    for path, kind in (
        (journey_path, "normalized-journey"),
        (report_path, "semantic-report"),
        (screenshot_path, "rendered-pixels"),
        (stdout_path, "runtime-stdout"),
        (stderr_path, "runtime-stderr"),
    ):
        evidence.append(
            {
                "kind": kind,
                "path": path.relative_to(artifacts_root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": base._sha256_file(path),
            }
        )

    receipt = {
        "schemaVersion": "2.0",
        "status": "locally-verified",
        "truth": "locally-verified",
        "ready": True,
        "runId": run_id,
        "checkedAt": checked_at.isoformat(),
        "expiresAt": (checked_at + timedelta(minutes=30)).isoformat(),
        "sourceSha256": source_sha256,
        "godotExecutable": str(godot),
        "godotVersion": base._godot_version(godot, args.timeout),
        "displayMode": (
            "headless-offscreen" if args.headless else "interactive-window"
        ),
        "processExitCode": exit_code,
        "expectedJourneyFailure": report.get("status") == "failed",
        "detected": detected,
        "pixelStatistics": pixel_statistics,
        "screenshot": {
            "path": screenshot_path.relative_to(artifacts_root).as_posix(),
            "width": width,
            "height": height,
            "bytes": screenshot_path.stat().st_size,
            "sha256": base._sha256_file(screenshot_path),
        },
        "report": {
            "path": report_path.relative_to(artifacts_root).as_posix(),
            "bytes": report_path.stat().st_size,
            "sha256": base._sha256_file(report_path),
        },
        "evidence": evidence,
        "truthBoundary": (
            "This receipt proves that the exact self-test sources launched Godot, "
            "retained non-uniform rendered pixels and detected deliberate semantic "
            "layout defects. It does not certify an unrelated game or application."
        ),
    }
    base._write_atomic_json(run_root / "receipt.json", receipt)
    base._write_atomic_json(latest_receipt, receipt)
    return receipt


def build_parser() -> argparse.ArgumentParser:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(
        prog="godot-lab-visual-qa-self-test",
        description=(
            "Normalize one fixture journey, render it in Godot, and require screenshot "
            "plus semantic defect evidence before issuing a local receipt."
        ),
    )
    parser.add_argument("--lab-root", type=Path, default=root)
    parser.add_argument("--godot", type=Path)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--headless", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    if not 10 <= args.timeout <= 900:
        raise SystemExit("--timeout must be between 10 and 900 seconds")
    try:
        receipt = run_visual_qa_self_test(args)
    except (
        base.VisualQaSelfTestError,
        FileNotFoundError,
        OSError,
        subprocess.SubprocessError,
        ValueError,
    ) as error:
        result = {
            "schemaVersion": "2.0",
            "status": "failed",
            "truth": "source-present",
            "ready": False,
            "checkedAt": datetime.now(UTC).isoformat(),
            "errorType": type(error).__name__,
            "error": str(error),
        }
        print(json.dumps(result, sort_keys=True))
        return 2
    print(json.dumps(receipt, sort_keys=True))
    return 0 if receipt.get("ready") is True else 1


if __name__ == "__main__":
    sys.exit(main())
