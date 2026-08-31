#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

TEST_LAB = Path(__file__).resolve().parents[1]
SUITE_ID = "evavo_game_runtime_native_provider_transfer"
PASS_MARKER = "EVAVO_CONTENT_NATIVE_PROVIDER_TRANSFER_TEST=PASS"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
CLAIMS = {
    "native_dispatch_is_transfer_completion": False,
    "chunk_handle_is_chunk_bytes": False,
    "provider_completion_is_cache_verification": False,
    "cancel_request_is_terminal_cancellation": False,
    "transfer_provider_ready_grants_content_availability": False,
    "transfer_provider_ready_grants_scene_activation": False,
    "transfer_provider_ready_grants_simulation_authority": False,
    "portable_resume_contains_native_request_id": False,
    "portable_resume_contains_chunk_handles": False,
    "platform_mapping_proves_native_sdk_available": False,
}


def run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def git_value(root: Path, *arguments: str) -> str:
    result = run(["git", *arguments], root)
    if result.returncode != 0:
        raise RuntimeError(result.stdout.strip() or "git command failed")
    return result.stdout.strip()


def scenario(
    scenario_id: str,
    command: list[str],
    cwd: Path,
    artifact_root: Path,
    pass_marker: str = "",
) -> dict:
    result = run(command, cwd)
    log_path = artifact_root / f"{scenario_id}.log"
    log_path.write_text(result.stdout, encoding="utf-8")
    marker_observed = not pass_marker or pass_marker in result.stdout.splitlines()
    return {
        "id": scenario_id,
        "passed": result.returncode == 0 and marker_observed,
        "exit_code": result.returncode,
        "log_path": str(log_path),
        "pass_marker_observed": marker_observed,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-repo", type=Path, required=True)
    parser.add_argument("--godot", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    args = parser.parse_args()

    runtime = args.runtime_repo.resolve()
    godot = args.godot.resolve()
    artifact_root = args.artifact_root.resolve()
    artifact_root.mkdir(parents=True, exist_ok=True)

    if not (runtime / "project.godot").is_file():
        raise SystemExit("Runtime repository project.godot is missing.")
    if not godot.is_file():
        raise SystemExit("Godot executable is missing.")

    runtime_status = git_value(runtime, "status", "--porcelain")
    test_lab_status = git_value(TEST_LAB, "status", "--porcelain")
    runtime_sha = git_value(runtime, "rev-parse", "HEAD")
    test_lab_sha = git_value(TEST_LAB, "rev-parse", "HEAD")
    if not SHA_RE.fullmatch(runtime_sha) or not SHA_RE.fullmatch(test_lab_sha):
        raise SystemExit("Unable to resolve exact Git SHAs.")

    version_result = run([str(godot), "--version"], runtime)
    godot_version = version_result.stdout.splitlines()[0].strip()
    if version_result.returncode != 0 or not godot_version.startswith("4.6.2"):
        raise SystemExit(f"Expected Godot 4.6.2, observed: {godot_version}")

    scenarios = [
        scenario(
            "dependency_free_validator",
            [sys.executable, "tests/validate_content_native_provider_transfer.py"],
            runtime,
            artifact_root,
        ),
        scenario(
            "headless_import_parse",
            [str(godot), "--headless", "--editor", "--path", str(runtime), "--quit"],
            runtime,
            artifact_root,
        ),
        scenario(
            "native_provider_transfer_behavior",
            [
                str(godot),
                "--headless",
                "--path",
                str(runtime),
                "--script",
                str(runtime / "tests" / "godot" / "test_content_native_provider_transfer.gd"),
            ],
            runtime,
            artifact_root,
            PASS_MARKER,
        ),
    ]

    passed = (
        not runtime_status
        and not test_lab_status
        and all(row["passed"] for row in scenarios)
    )
    receipt = {
        "version": 1,
        "suite_id": SUITE_ID,
        "runtime_sha": runtime_sha,
        "test_lab_sha": test_lab_sha,
        "godot_version": godot_version,
        "runtime_clean": not runtime_status,
        "test_lab_clean": not test_lab_status,
        "scenarios": scenarios,
        "passed": passed,
        "claims": CLAIMS,
    }
    receipt_path = artifact_root / "receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(f"Receipt: {receipt_path}")
    for row in scenarios:
        print(f"{row['id']}: {'PASS' if row['passed'] else 'FAIL'}")
    if not passed:
        raise SystemExit("EVAVO native provider transfer suite failed.")
    print("EVAVO native provider transfer suite passed.")


if __name__ == "__main__":
    main()
