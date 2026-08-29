from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import visual_qa_self_test as base
from .visual_qa_self_test_runner import _exact_source_digest


class VisualQaDoctorError(RuntimeError):
    pass


def _confined_file(root: Path, relative_path: object) -> Path:
    if not isinstance(relative_path, str) or not relative_path:
        raise VisualQaDoctorError("Evidence path is missing")
    candidate = (root / relative_path).resolve(strict=True)
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise VisualQaDoctorError(
            f"Evidence path escapes its admitted root: {relative_path}"
        ) from error
    if not candidate.is_file() or candidate.is_symlink():
        raise VisualQaDoctorError(f"Evidence path is not a regular file: {relative_path}")
    return candidate


def _load_receipt(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise VisualQaDoctorError(f"Visual QA receipt is unavailable: {path}")
    size = path.stat().st_size
    if not 1 <= size <= 4 * 1024 * 1024:
        raise VisualQaDoctorError("Visual QA receipt size is outside policy")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise VisualQaDoctorError(f"Visual QA receipt is invalid JSON: {error}") from error
    if not isinstance(value, dict):
        raise VisualQaDoctorError("Visual QA receipt must be an object")
    return value


def diagnose_visual_qa(
    *,
    lab_root: Path,
    artifacts: Path,
    now: datetime | None = None,
) -> dict[str, Any]:
    checked_at = now or datetime.now(UTC)
    repository = lab_root.expanduser().resolve(strict=True)
    artifact_root = artifacts.expanduser().resolve(strict=True)
    if artifact_root == repository or base._is_within(artifact_root, repository):
        raise VisualQaDoctorError("Visual QA artifacts may not be inside the repository")
    receipt_path = artifact_root / "latest-receipt.json"
    receipt = _load_receipt(receipt_path)
    reasons: list[str] = []
    if receipt.get("schemaVersion") != "2.0":
        reasons.append("receipt-schema-unsupported")
    if receipt.get("status") != "locally-verified" or receipt.get("truth") != "locally-verified":
        reasons.append("receipt-not-locally-verified")
    if receipt.get("ready") is not True:
        reasons.append("receipt-not-ready")
    expected_source = _exact_source_digest(repository)
    if receipt.get("sourceSha256") != expected_source:
        reasons.append("source-identity-mismatch")
    checked_value = receipt.get("checkedAt")
    expires_value = receipt.get("expiresAt")
    try:
        issued_at = datetime.fromisoformat(str(checked_value))
        expires_at = datetime.fromisoformat(str(expires_value))
        if issued_at.tzinfo is None or expires_at.tzinfo is None:
            raise ValueError("timestamps require timezone offsets")
        if issued_at > checked_at + base.timedelta(minutes=5):
            reasons.append("receipt-issued-in-future")
        if expires_at <= checked_at:
            reasons.append("receipt-expired")
        if expires_at <= issued_at:
            reasons.append("receipt-window-invalid")
    except (TypeError, ValueError):
        reasons.append("receipt-time-invalid")

    evidence = receipt.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        reasons.append("receipt-evidence-missing")
        evidence = []
    verified_evidence: list[dict[str, Any]] = []
    for index, raw in enumerate(evidence):
        if not isinstance(raw, dict):
            reasons.append(f"evidence-{index}-invalid")
            continue
        try:
            path = _confined_file(artifact_root, raw.get("path"))
        except (FileNotFoundError, OSError, VisualQaDoctorError):
            reasons.append(f"evidence-{index}-unavailable")
            continue
        size = path.stat().st_size
        digest = base._sha256_file(path)
        if raw.get("bytes") != size:
            reasons.append(f"evidence-{index}-size-mismatch")
        if raw.get("sha256") != digest:
            reasons.append(f"evidence-{index}-digest-mismatch")
        verified_evidence.append(
            {
                "kind": raw.get("kind"),
                "path": path.relative_to(artifact_root).as_posix(),
                "bytes": size,
                "sha256": digest,
            }
        )

    screenshot_raw = receipt.get("screenshot")
    if not isinstance(screenshot_raw, dict):
        reasons.append("screenshot-record-missing")
    else:
        try:
            screenshot = _confined_file(artifact_root, screenshot_raw.get("path"))
            width, height, rgba = base._decode_png_rgba(screenshot)
            statistics = base._pixel_statistics(rgba, width, height)
            if screenshot_raw.get("sha256") != base._sha256_file(screenshot):
                reasons.append("screenshot-digest-mismatch")
            if screenshot_raw.get("bytes") != screenshot.stat().st_size:
                reasons.append("screenshot-size-mismatch")
            if screenshot_raw.get("width") != width or screenshot_raw.get("height") != height:
                reasons.append("screenshot-dimensions-mismatch")
            if not statistics["nonUniform"] or not statistics["notAllBlack"]:
                reasons.append("screenshot-not-visible-render")
        except (FileNotFoundError, OSError, base.VisualQaSelfTestError, VisualQaDoctorError):
            reasons.append("screenshot-unavailable-or-invalid")

    detected = receipt.get("detected")
    if not isinstance(detected, dict):
        reasons.append("layout-findings-missing")
    else:
        for key in base._REQUIRED_LAYOUT_KEYS:
            count = detected.get(key)
            if not isinstance(count, int) or isinstance(count, bool) or count < 1:
                reasons.append(f"required-layout-finding-missing:{key}")

    return {
        "schemaVersion": "2.0",
        "status": "locally-verified" if not reasons else "source-present",
        "truth": "locally-verified" if not reasons else "source-present",
        "ready": not reasons,
        "checkedAt": checked_at.isoformat(),
        "sourceSha256": expected_source,
        "receiptPath": receipt_path.as_posix(),
        "runId": receipt.get("runId"),
        "verifiedEvidence": verified_evidence,
        "reasons": sorted(set(reasons)),
        "truthBoundary": (
            "The doctor validates the exact self-test source identity, receipt freshness, "
            "confined evidence hashes, visible PNG content and deliberate defect findings. "
            "It does not certify a separate game campaign."
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="godot-lab-visual-qa-doctor",
        description="Validate the latest exact-source Godot visual QA self-test receipt.",
    )
    parser.add_argument(
        "--lab-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    parser.add_argument("--artifacts", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        result = diagnose_visual_qa(
            lab_root=args.lab_root,
            artifacts=args.artifacts,
        )
    except (
        FileNotFoundError,
        OSError,
        ValueError,
        VisualQaDoctorError,
        base.VisualQaSelfTestError,
    ) as error:
        result = {
            "schemaVersion": "2.0",
            "status": "source-present",
            "truth": "source-present",
            "ready": False,
            "checkedAt": datetime.now(UTC).isoformat(),
            "reasons": [str(error)],
        }
    print(json.dumps(result, sort_keys=True))
    return 0 if result.get("ready") is True else 1


if __name__ == "__main__":
    sys.exit(main())
