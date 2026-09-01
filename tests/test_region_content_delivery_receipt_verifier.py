#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
VERIFIER = (
    ROOT
    / "scripts"
    / "verify-evavo-game-runtime-region-content-delivery-receipt.py"
)
RUNTIME_SHA = "1" * 40
TEST_LAB_SHA = "2" * 40


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_log(root: Path, name: str, marker: str) -> str:
    path = root / f"{name}.log"
    path.write_text(marker + "\n", encoding="utf-8")
    return str(path)


def check(root: Path, name: str, marker: str) -> dict[str, Any]:
    now = timestamp()
    return {
        "status": "pass",
        "exit_code": 0,
        "log_path": write_log(root, name, marker),
        "marker": marker,
        "reason": "",
        "started_at_utc": now,
        "finished_at_utc": now,
    }


def valid_receipt(root: Path) -> dict[str, Any]:
    source = {
        "content_delivery": check(
            root,
            "source-content-delivery",
            "EVAVO region content delivery validation passed",
        ),
        "region_package_binding": check(
            root,
            "source-region-package-binding",
            "EVAVO region package binding validation passed",
        ),
    }
    executable = {
        "godot_import": check(root, "godot-import", "GODOT_IMPORT=PASS"),
        "delivery_session_smoke": check(
            root,
            "delivery-session",
            "EVAVO_CONTENT_DELIVERY_SESSION_TEST=PASS",
        ),
        "region_driver_smoke": check(
            root,
            "region-driver",
            "EVAVO_REGION_CONTENT_DRIVER_TEST=PASS",
        ),
        "delegated_host_smoke": check(
            root,
            "delegated-host",
            "EVAVO_DELEGATED_CONTENT_DELIVERY_HOST_TEST=PASS",
        ),
        "composition_smoke": check(
            root,
            "composition",
            "EVAVO_WORLD_STREAM_CONTENT_RUNTIME_TEST=PASS",
        ),
    }
    return {
        "version": 1,
        "suite_id": "evavo_game_runtime_region_content_delivery",
        "run_id": "receipt-verifier-unit-test",
        "generated_at_utc": timestamp(),
        "status": "pass",
        "runtime_repository": "EVAVO-STUDIO/evavo-game-runtime",
        "runtime_sha": RUNTIME_SHA,
        "test_lab_repository": "EVAVO-STUDIO/godot-game-test-lab",
        "test_lab_sha": TEST_LAB_SHA,
        "runtime_branch": "main",
        "test_lab_branch": "main",
        "godot_version": "4.6.2.test",
        "source_validation": source,
        "executable_validation": executable,
        "claims": {
            "real_storefront_install_verified": False,
            "real_network_transfer_verified": False,
            "measured_byte_progress_verified": False,
            "threaded_load_hard_cancel_verified": False,
            "resource_completion_grants_authority": False,
            "declared_bytes_are_measured_bytes": False,
        },
        "evidence_root": str(root),
        "notes": ["synthetic unit-test receipt"],
    }


def run_verifier(receipt: dict[str, Any], root: Path, name: str) -> subprocess.CompletedProcess[str]:
    receipt_path = root / f"{name}.json"
    receipt_path.write_text(
        json.dumps(receipt, indent=2) + "\n",
        encoding="utf-8",
    )
    return subprocess.run(
        [sys.executable, str(VERIFIER), str(receipt_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def require_pass(receipt: dict[str, Any], root: Path, name: str) -> None:
    result = run_verifier(receipt, root, name)
    if result.returncode != 0:
        raise AssertionError(
            f"{name} unexpectedly failed:\nstdout={result.stdout}\nstderr={result.stderr}"
        )
    marker = "EVAVO region content delivery receipt verification passed"
    if marker not in result.stdout.splitlines():
        raise AssertionError(f"{name} did not emit the verifier PASS marker")


def require_failure(
    receipt: dict[str, Any],
    root: Path,
    name: str,
    expected_text: str,
) -> None:
    result = run_verifier(receipt, root, name)
    if result.returncode == 0:
        raise AssertionError(f"{name} unexpectedly passed")
    combined = result.stdout + "\n" + result.stderr
    if expected_text not in combined:
        raise AssertionError(
            f"{name} failed for the wrong reason; expected {expected_text!r}:\n{combined}"
        )


def main() -> None:
    if not VERIFIER.is_file():
        raise AssertionError(f"receipt verifier is missing: {VERIFIER}")

    with tempfile.TemporaryDirectory(prefix="evavo-region-receipt-") as raw_root:
        root = Path(raw_root).resolve()
        base = valid_receipt(root)
        require_pass(base, root, "valid")

        missing_composition = copy.deepcopy(base)
        del missing_composition["executable_validation"]["composition_smoke"]
        require_failure(
            missing_composition,
            root,
            "missing-composition",
            "executable_validation checks are incomplete",
        )

        forged_claim = copy.deepcopy(base)
        forged_claim["claims"]["real_storefront_install_verified"] = True
        require_failure(
            forged_claim,
            root,
            "forged-storefront-claim",
            "reference suite may not assert production evidence",
        )

        skipped_source = copy.deepcopy(base)
        skipped_source["source_validation"]["content_delivery"].update(
            {
                "status": "skipped",
                "exit_code": None,
                "marker": "",
            }
        )
        skipped_source["status"] = "partial"
        require_failure(
            skipped_source,
            root,
            "skipped-source",
            "source validations may not be skipped or unverified",
        )

        forged_marker = copy.deepcopy(base)
        marker_log = Path(
            forged_marker["executable_validation"]["composition_smoke"]["log_path"]
        )
        marker_log.write_text("wrong marker\n", encoding="utf-8")
        require_failure(
            forged_marker,
            root,
            "forged-pass-marker",
            "pass marker is absent from its log",
        )

        wrong_status = copy.deepcopy(base)
        wrong_status["status"] = "partial"
        require_failure(
            wrong_status,
            root,
            "wrong-aggregate-status",
            "does not match checks pass",
        )

        non_main = copy.deepcopy(base)
        non_main["runtime_branch"] = "feature"
        require_failure(
            non_main,
            root,
            "non-main-runtime",
            "runtime receipt must be produced from main",
        )

        invalid_sha = copy.deepcopy(base)
        invalid_sha["runtime_sha"] = "not-a-sha"
        require_failure(
            invalid_sha,
            root,
            "invalid-runtime-sha",
            "runtime_sha must be a 40-character lowercase Git SHA",
        )

    print("EVAVO Test Lab region content delivery receipt verifier tests passed")


if __name__ == "__main__":
    main()
