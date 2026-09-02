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
SUITE_ID = "evavo_game_runtime_http_range_hardening"
PASS_MARKER = "EVAVO_CONTENT_HTTP_RANGE_HARDENING_TEST=PASS"
INTEGRATION_MARKER = "EVAVO Game Runtime HTTP range hardening integration validation passed"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
CLAIMS = {
    "declared_bytes_are_measured_network_bytes": False,
    "range_response_is_verified_cache_chunk": False,
    "https_origin_proves_content_trust": False,
    "cors_configuration_is_verified": False,
    "source_policy_grants_content_availability": False,
    "source_policy_grants_scene_activation": False,
    "source_policy_grants_simulation_authority": False,
    "https_without_strong_validator_is_production_ready": False,
}


def run(command: list[str], cwd: Path, timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding="utf-8", errors="replace", timeout=timeout, check=False)


def git(root: Path, *args: str) -> str:
    result = run(["git", *args], root, 30.0)
    if result.returncode:
        raise RuntimeError(result.stdout.strip() or f"git {' '.join(args)} failed")
    return result.stdout.strip()


def check(command: list[str], cwd: Path, log: Path, timeout: float, marker: str = "") -> dict[str, Any]:
    result = run(command, cwd, timeout)
    log.write_text(result.stdout, encoding="utf-8")
    marker_ok = not marker or marker in result.stdout.splitlines()
    passed = result.returncode == 0 and marker_ok
    return {
        "status": "pass" if passed else "fail",
        "exit_code": result.returncode,
        "log_path": str(log.resolve()),
        "marker": marker,
        "reason": "" if passed else (f"exit_code:{result.returncode}" if result.returncode else "pass_marker_missing"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-repo", type=Path, required=True)
    parser.add_argument("--godot", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    args = parser.parse_args()

    runtime = args.runtime_repo.resolve()
    godot = args.godot.resolve()
    artifacts = args.artifact_root.resolve()
    if not (runtime / "project.godot").is_file():
        raise SystemExit("Runtime repository project.godot is missing.")
    if not godot.is_file():
        raise SystemExit("Godot executable is missing.")

    runtime_status = git(runtime, "status", "--porcelain")
    test_lab_status = git(TEST_LAB, "status", "--porcelain")
    runtime_sha = git(runtime, "rev-parse", "HEAD")
    test_lab_sha = git(TEST_LAB, "rev-parse", "HEAD")
    runtime_branch = git(runtime, "branch", "--show-current")
    test_lab_branch = git(TEST_LAB, "branch", "--show-current")
    if runtime_status or test_lab_status:
        raise SystemExit("Runtime and Test Lab repositories must be clean.")
    if not SHA_RE.fullmatch(runtime_sha) or not SHA_RE.fullmatch(test_lab_sha):
        raise SystemExit("Unable to resolve exact Git SHAs.")

    version_result = run([str(godot), "--version"], runtime, 30.0)
    version = version_result.stdout.splitlines()[0].strip() if version_result.stdout else ""
    if version_result.returncode or not version.startswith("4.6.2"):
        raise SystemExit(f"Expected Godot 4.6.2, observed: {version}")

    artifacts.mkdir(parents=True, exist_ok=True)
    receipt_path = artifacts / "receipt.json"
    receipt: dict[str, Any] = {
        "version": 1,
        "suite_id": SUITE_ID,
        "run_id": f"http-range-hardening-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "fail",
        "runtime_repository": "EVAVO-STUDIO/evavo-game-runtime",
        "runtime_sha": runtime_sha,
        "runtime_branch": runtime_branch,
        "runtime_clean": True,
        "test_lab_repository": "EVAVO-STUDIO/godot-game-test-lab",
        "test_lab_sha": test_lab_sha,
        "test_lab_branch": test_lab_branch,
        "test_lab_clean": True,
        "godot_version": version,
        "scenarios": {},
        "claims": CLAIMS,
        "evidence_root": str(artifacts),
        "notes": [],
    }

    try:
        receipt["scenarios"]["integration_validator"] = check(
            [sys.executable, str(TEST_LAB / "scripts/validate-evavo-game-runtime-http-range-hardening.py"), "--runtime-repo", str(runtime)],
            TEST_LAB,
            artifacts / "integration-validator.log",
            args.timeout_seconds,
            INTEGRATION_MARKER,
        )
        receipt["scenarios"]["exact_godot_4_6_2_import"] = check(
            [str(godot), "--headless", "--editor", "--path", str(runtime), "--quit"],
            runtime,
            artifacts / "godot-import.log",
            args.timeout_seconds,
        )
        receipt["scenarios"]["http_range_hardening_behavior"] = check(
            [str(godot), "--headless", "--path", str(runtime), "--script", "res://tests/godot/test_content_http_range_hardening.gd"],
            runtime,
            artifacts / "hardening-behavior.log",
            args.timeout_seconds,
            PASS_MARKER,
        )
        failed = [name for name, value in receipt["scenarios"].items() if value["status"] != "pass"]
        if failed:
            raise RuntimeError("HTTP range hardening scenarios failed: " + ", ".join(failed))
        receipt["status"] = "pass"
        receipt["notes"] = [
            "The suite requires the exact Godot 4.6.2 version family.",
            "The suite validates release policy and cannot grant content availability, scene activation or simulation authority.",
        ]
    except Exception as exc:
        receipt["notes"].append(f"failure: {type(exc).__name__}: {exc}")
        raise
    finally:
        receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")

    print(f"Receipt: {receipt_path}")
    print("EVAVO Game Runtime HTTP range hardening Test Lab suite passed")


if __name__ == "__main__":
    main()
