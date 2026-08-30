#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
CHECK_STATUSES = {"pass", "fail", "skipped", "unverified"}


def load_receipt(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise AssertionError("receipt must contain a JSON object")
    return value


def parse_time(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise AssertionError(f"{field} must be a non-empty ISO timestamp")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        return datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise AssertionError(f"{field} is not an ISO timestamp: {value}") from exc


def validate_check(name: str, check: Any) -> str:
    if not isinstance(check, dict):
        raise AssertionError(f"{name} must be an object")
    status = check.get("status")
    if status not in CHECK_STATUSES:
        raise AssertionError(f"{name}.status is invalid: {status}")
    exit_code = check.get("exit_code")
    if exit_code is not None and not isinstance(exit_code, int):
        raise AssertionError(f"{name}.exit_code must be integer or null")
    log_path = check.get("log_path")
    if not isinstance(log_path, str):
        raise AssertionError(f"{name}.log_path must be a string")
    started = parse_time(check.get("started_at_utc"), f"{name}.started_at_utc")
    finished = parse_time(check.get("finished_at_utc"), f"{name}.finished_at_utc")
    if finished < started:
        raise AssertionError(f"{name} finished before it started")

    if status == "pass":
        if exit_code != 0:
            raise AssertionError(f"{name} passed with exit code {exit_code}")
        if not log_path or not Path(log_path).is_file():
            raise AssertionError(f"{name} pass log is missing: {log_path}")
        marker = check.get("marker", "")
        if marker:
            log_text = Path(log_path).read_text(encoding="utf-8-sig", errors="replace")
            if marker not in log_text.splitlines():
                raise AssertionError(f"{name} pass marker is absent from its log")
    elif status == "fail":
        if not log_path or not Path(log_path).is_file():
            raise AssertionError(f"{name} failure log is missing: {log_path}")
    elif exit_code is not None:
        raise AssertionError(f"{name} {status} check must use a null exit code")
    return str(status)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(
            "usage: verify-evavo-game-runtime-region-content-delivery-receipt.py RECEIPT"
        )

    receipt_path = Path(sys.argv[1]).resolve()
    receipt = load_receipt(receipt_path)
    if receipt.get("version") != 1:
        raise AssertionError("receipt version must be 1")
    if receipt.get("suite_id") != "evavo_game_runtime_region_content_delivery":
        raise AssertionError("receipt suite_id is invalid")
    if receipt.get("runtime_repository") != "EVAVO-STUDIO/evavo-game-runtime":
        raise AssertionError("runtime repository is invalid")
    if receipt.get("test_lab_repository") != "EVAVO-STUDIO/godot-game-test-lab":
        raise AssertionError("Test Lab repository is invalid")
    if receipt.get("runtime_branch") != "main":
        raise AssertionError("runtime receipt must be produced from main")
    if receipt.get("test_lab_branch") != "main":
        raise AssertionError("Test Lab receipt must be produced from main")

    for field in ("runtime_sha", "test_lab_sha"):
        value = receipt.get(field)
        if not isinstance(value, str) or SHA_RE.fullmatch(value) is None:
            raise AssertionError(f"{field} must be a 40-character lowercase Git SHA")
    parse_time(receipt.get("generated_at_utc"), "generated_at_utc")

    source = receipt.get("source_validation")
    executable = receipt.get("executable_validation")
    if not isinstance(source, dict) or set(source) != {
        "content_delivery",
        "region_package_binding",
    }:
        raise AssertionError("source_validation checks are incomplete")
    if not isinstance(executable, dict) or set(executable) != {
        "godot_import",
        "delivery_session_smoke",
        "region_driver_smoke",
    }:
        raise AssertionError("executable_validation checks are incomplete")

    source_statuses = [
        validate_check(f"source_validation.{name}", check)
        for name, check in source.items()
    ]
    executable_statuses = [
        validate_check(f"executable_validation.{name}", check)
        for name, check in executable.items()
    ]
    if any(status in {"skipped", "unverified"} for status in source_statuses):
        raise AssertionError("source validations may not be skipped or unverified")

    claims = receipt.get("claims")
    required_claims = {
        "real_storefront_install_verified",
        "real_network_transfer_verified",
        "measured_byte_progress_verified",
        "threaded_load_hard_cancel_verified",
        "resource_completion_grants_authority",
        "declared_bytes_are_measured_bytes",
    }
    if not isinstance(claims, dict) or set(claims) != required_claims:
        raise AssertionError("receipt claims are incomplete")
    true_claims = [name for name, value in claims.items() if value is not False]
    if true_claims:
        raise AssertionError(
            "reference suite may not assert production evidence: " + ", ".join(true_claims)
        )

    statuses = source_statuses + executable_statuses
    expected_status = "partial"
    if "fail" in statuses:
        expected_status = "fail"
    elif all(status == "pass" for status in statuses):
        expected_status = "pass"
    if receipt.get("status") != expected_status:
        raise AssertionError(
            f"receipt status {receipt.get('status')} does not match checks {expected_status}"
        )

    evidence_root = receipt.get("evidence_root")
    if not isinstance(evidence_root, str) or not Path(evidence_root).is_dir():
        raise AssertionError("evidence_root does not exist")
    if receipt_path.parent != Path(evidence_root).resolve():
        raise AssertionError("receipt must be stored directly under evidence_root")

    print("EVAVO region content delivery receipt verification passed")


if __name__ == "__main__":
    main()
