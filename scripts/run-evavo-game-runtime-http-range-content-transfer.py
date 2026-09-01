#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TEST_LAB = Path(__file__).resolve().parents[1]
SUITE_ID = "evavo_game_runtime_http_range_content_transfer"
RUNTIME_PASS_MARKER = "EVAVO_CONTENT_HTTP_RANGE_TRANSFER_TEST=PASS"
INTEGRATION_PASS_MARKER = (
    "EVAVO Game Runtime HTTP range content transfer "
    "integration validation passed"
)
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
EXPECTED_RANGES = {
    "bytes=0-11",
    "bytes=12-23",
    "bytes=24-35",
    "bytes=36-47",
}
CLAIMS = {
    "http_dispatch_is_transfer_completion": False,
    "range_response_is_cache_verification": False,
    "provider_completion_is_cache_verification": False,
    "cancel_request_is_terminal_cancellation": False,
    "runtime_ready_grants_content_availability": False,
    "runtime_ready_grants_scene_activation": False,
    "runtime_ready_grants_simulation_authority": False,
    "web_cors_configuration_is_verified": False,
    "process_local_handles_are_portable": False,
}


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-repo", type=Path, required=True)
    parser.add_argument("--godot", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=240.0)
    return parser.parse_args()


def run(
    command: list[str],
    cwd: Path,
    *,
    timeout: float,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def git_value(root: Path, *arguments: str) -> str:
    result = run(["git", *arguments], root, timeout=30.0)
    if result.returncode != 0:
        raise RuntimeError(
            result.stdout.strip() or f"git {' '.join(arguments)} failed"
        )
    return result.stdout.strip()


def execute_check(
    command: list[str],
    cwd: Path,
    log_path: Path,
    *,
    timeout: float,
    marker: str = "",
) -> dict[str, Any]:
    result = run(command, cwd, timeout=timeout)
    log_path.write_text(result.stdout, encoding="utf-8")
    marker_ok = not marker or marker in result.stdout.splitlines()
    passed = result.returncode == 0 and marker_ok
    reason = ""
    if result.returncode != 0:
        reason = f"exit_code:{result.returncode}"
    elif not marker_ok:
        reason = "pass_marker_missing"
    return {
        "status": "pass" if passed else "fail",
        "exit_code": result.returncode,
        "log_path": str(log_path.resolve()),
        "marker": marker,
        "reason": reason,
        "output": result.stdout,
    }


def imported_check(runtime_receipt: dict[str, Any]) -> dict[str, Any]:
    checks = runtime_receipt.get("checks", {})
    value = checks.get("headless_import_parse", {})
    if not isinstance(value, dict):
        value = {}
    passed = value.get("status") == "pass" and int(
        value.get("exit_code", 1)
    ) == 0
    return {
        "status": "pass" if passed else "fail",
        "exit_code": value.get("exit_code"),
        "log_path": str(value.get("log_path", "")),
        "marker": "GODOT_4_6_2_IMPORT_PARSE=PASS",
        "reason": "" if passed else "runtime_import_parse_failed",
    }


def behavior_check(runtime_receipt: dict[str, Any]) -> dict[str, Any]:
    checks = runtime_receipt.get("checks", {})
    value = checks.get("http_range_behavior", {})
    if not isinstance(value, dict):
        value = {}
    passed = value.get("status") == "pass" and int(
        value.get("exit_code", 1)
    ) == 0
    return {
        "status": "pass" if passed else "fail",
        "exit_code": value.get("exit_code"),
        "log_path": str(value.get("log_path", "")),
        "marker": RUNTIME_PASS_MARKER,
        "reason": "" if passed else "runtime_http_range_behavior_failed",
    }


def range_evidence(
    runtime_receipt: dict[str, Any],
    runtime_artifacts: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    value = runtime_receipt.get("range_server_report", {})
    report = value if isinstance(value, dict) else {}
    good_ranges = set(report.get("good_ranges", []))
    retry_ranges = set(report.get("retry_ranges", []))
    passed = (
        bool(report.get("ok", False))
        and EXPECTED_RANGES.issubset(good_ranges)
        and EXPECTED_RANGES.issubset(retry_ranges)
        and int(report.get("retry_503_count", 0)) >= 1
        and int(report.get("ignore_range_200_count", 0)) >= 1
        and int(report.get("bad_content_range_count", 0)) >= 1
        and int(report.get("corrupt_range_attempt_count", 0)) >= 3
        and bool(report.get("ranges_are_bounded", False))
    )
    normalized = {
        "request_count": int(report.get("request_count", 0)),
        "good_ranges": sorted(good_ranges),
        "retry_ranges": sorted(retry_ranges),
        "retry_503_count": int(report.get("retry_503_count", 0)),
        "ignore_range_200_count": int(
            report.get("ignore_range_200_count", 0)
        ),
        "bad_content_range_count": int(
            report.get("bad_content_range_count", 0)
        ),
        "corrupt_range_attempt_count": int(
            report.get("corrupt_range_attempt_count", 0)
        ),
        "ranges_are_bounded": bool(
            report.get("ranges_are_bounded", False)
        ),
    }
    check = {
        "status": "pass" if passed else "fail",
        "exit_code": 0 if passed else 1,
        "log_path": str(
            (runtime_artifacts / "range-server-report.json").resolve()
        ),
        "marker": "EVAVO_HTTP_RANGE_SERVER_EVIDENCE=PASS",
        "reason": "" if passed else "range_server_evidence_invalid",
    }
    return check, normalized


def strip_output(value: dict[str, Any]) -> dict[str, Any]:
    return {key: row for key, row in value.items() if key != "output"}


def main() -> None:
    args = parse_args()
    runtime = args.runtime_repo.resolve()
    godot = args.godot.resolve()
    artifact_root = args.artifact_root.resolve()

    if not (runtime / "project.godot").is_file():
        raise SystemExit("Runtime repository project.godot is missing.")
    if not godot.is_file():
        raise SystemExit("Godot executable is missing.")

    runtime_status = git_value(runtime, "status", "--porcelain")
    test_lab_status = git_value(TEST_LAB, "status", "--porcelain")
    runtime_sha = git_value(runtime, "rev-parse", "HEAD")
    test_lab_sha = git_value(TEST_LAB, "rev-parse", "HEAD")
    runtime_branch = git_value(runtime, "branch", "--show-current")
    test_lab_branch = git_value(TEST_LAB, "branch", "--show-current")
    if not SHA_RE.fullmatch(runtime_sha) or not SHA_RE.fullmatch(test_lab_sha):
        raise SystemExit("Unable to resolve exact Git SHAs.")
    if runtime_status:
        raise SystemExit("Runtime repository must be clean.")
    if test_lab_status:
        raise SystemExit("Test Lab repository must be clean.")

    artifact_root.mkdir(parents=True, exist_ok=True)
    run_id = (
        f"http-range-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-"
        f"{uuid.uuid4().hex[:8]}"
    )
    receipt_path = artifact_root / "receipt.json"
    runtime_artifacts = artifact_root / "runtime-suite"
    runtime_artifacts.mkdir(parents=True, exist_ok=True)

    receipt: dict[str, Any] = {
        "version": 1,
        "suite_id": SUITE_ID,
        "run_id": run_id,
        "generated_at_utc": timestamp(),
        "status": "fail",
        "runtime_repository": "EVAVO-STUDIO/evavo-game-runtime",
        "runtime_sha": runtime_sha,
        "runtime_branch": runtime_branch,
        "runtime_clean": not runtime_status,
        "test_lab_repository": "EVAVO-STUDIO/godot-game-test-lab",
        "test_lab_sha": test_lab_sha,
        "test_lab_branch": test_lab_branch,
        "test_lab_clean": not test_lab_status,
        "godot_version": "",
        "scenarios": {},
        "runtime_receipt_path": str(
            (runtime_artifacts / "receipt.json").resolve()
        ),
        "range_server": {
            "request_count": 0,
            "good_ranges": [],
            "retry_ranges": [],
            "retry_503_count": 0,
            "ignore_range_200_count": 0,
            "bad_content_range_count": 0,
            "corrupt_range_attempt_count": 0,
            "ranges_are_bounded": False,
        },
        "claims": CLAIMS,
        "evidence_root": str(artifact_root),
        "notes": [],
    }

    try:
        version_result = run([str(godot), "--version"], runtime, timeout=30.0)
        version_line = version_result.stdout.splitlines()[0].strip()
        receipt["godot_version"] = version_line
        if version_result.returncode != 0 or not version_line.startswith("4.6.2"):
            raise RuntimeError(f"Expected Godot 4.6.2, observed: {version_line}")

        integration = execute_check(
            [
                sys.executable,
                str(
                    TEST_LAB
                    / "scripts"
                    / "validate-evavo-game-runtime-http-range-content-transfer.py"
                ),
                "--runtime-repo",
                str(runtime),
            ],
            TEST_LAB,
            artifact_root / "integration-validator.log",
            timeout=args.timeout_seconds,
            marker=INTEGRATION_PASS_MARKER,
        )
        receipt["scenarios"]["integration_validator"] = strip_output(
            integration
        )
        if integration["status"] != "pass":
            raise RuntimeError("HTTP range integration validator failed")

        runtime_run = execute_check(
            [
                sys.executable,
                str(
                    runtime
                    / "scripts"
                    / "run-content-http-range-transfer-smoke.py"
                ),
                "--repo-root",
                str(runtime),
                "--godot",
                str(godot),
                "--artifact-root",
                str(runtime_artifacts),
                "--timeout-seconds",
                str(args.timeout_seconds),
            ],
            runtime,
            artifact_root / "runtime-suite.log",
            timeout=max(args.timeout_seconds * 2.0, 60.0),
            marker="EVAVO HTTP range content transfer smoke passed",
        )
        runtime_receipt_path = runtime_artifacts / "receipt.json"
        if not runtime_receipt_path.is_file():
            raise RuntimeError("Runtime HTTP range receipt is missing")
        runtime_receipt = json.loads(
            runtime_receipt_path.read_text(encoding="utf-8")
        )
        if not isinstance(runtime_receipt, dict):
            raise RuntimeError("Runtime HTTP range receipt must be an object")
        if runtime_run["status"] != "pass":
            raise RuntimeError("Runtime HTTP range suite failed")
        if runtime_receipt.get("status") != "pass":
            raise RuntimeError("Runtime HTTP range receipt did not pass")
        if runtime_receipt.get("runtime_sha") != runtime_sha:
            raise RuntimeError("Runtime receipt SHA does not match checkout")
        if runtime_receipt.get("godot_version") != version_line:
            raise RuntimeError("Runtime receipt Godot version mismatch")
        if runtime_receipt.get("claims") != CLAIMS:
            raise RuntimeError("Runtime receipt truth boundaries mismatch")

        receipt["scenarios"]["exact_godot_4_6_2_import"] = imported_check(
            runtime_receipt
        )
        receipt["scenarios"]["http_range_behavior"] = behavior_check(
            runtime_receipt
        )
        evidence_check, evidence = range_evidence(
            runtime_receipt,
            runtime_artifacts,
        )
        receipt["scenarios"]["range_server_evidence"] = evidence_check
        receipt["range_server"] = evidence

        failed = [
            key
            for key, value in receipt["scenarios"].items()
            if value.get("status") != "pass"
        ]
        if failed:
            raise RuntimeError(
                "HTTP range Test Lab scenarios failed: " + ", ".join(failed)
            )

        receipt["notes"] = [
            "The suite used a real loopback HTTP server and real HTTPClient range requests.",
            "The suite does not claim production CDN, CORS, service-worker or storefront validation.",
            "Provider and cache receipts remain separate from activation and simulation authority.",
        ]
        receipt["status"] = "pass"
    except Exception as exc:  # noqa: BLE001 - receipt must capture all failures
        receipt["notes"].append(f"failure: {type(exc).__name__}: {exc}")
        raise
    finally:
        receipt_path.write_text(
            json.dumps(receipt, indent=2) + "\n",
            encoding="utf-8",
        )

    print(f"Receipt: {receipt_path}")
    for scenario_id, value in receipt["scenarios"].items():
        print(f"{scenario_id}: {value['status'].upper()}")
    print("EVAVO Game Runtime HTTP range Test Lab suite passed")


if __name__ == "__main__":
    main()
