from __future__ import annotations

from pathlib import Path
from typing import Any

from .attended_multiplayer_common import (
    DESKTOP_LEASE_NAME,
    MAX_ARTIFACT_BYTES,
    MAX_ARTIFACT_FILES,
    assert_no_symlink_chain,
    bounded_line,
    digest,
    exact_fields,
    exact_sha,
    exact_timestamp,
    fail,
    inventory_artifacts,
    is_record,
    load_json_bytes,
    nonnegative_int,
    positive_int,
    safe_id,
    safe_relative_path,
    sha256_bytes,
    sha256_object,
)


def _normalize_summary_inventory(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > MAX_ARTIFACT_FILES:
        fail("ATTENDED_MULTIPLAYER_SUMMARY_ARTIFACTS_INVALID")
    records: list[dict[str, Any]] = []
    paths: set[str] = set()
    total_bytes = 0
    for raw in value:
        if not is_record(raw):
            fail("ATTENDED_MULTIPLAYER_SUMMARY_ARTIFACT_INVALID")
        item = dict(raw)
        exact_fields(
            item,
            {"path", "bytes", "sha256"},
            "ATTENDED_MULTIPLAYER_SUMMARY_ARTIFACT_FIELDS_INVALID",
        )
        path = safe_relative_path(
            item.get("path"), "ATTENDED_MULTIPLAYER_SUMMARY_ARTIFACT_PATH_INVALID"
        )
        if path in paths:
            fail("ATTENDED_MULTIPLAYER_SUMMARY_ARTIFACT_DUPLICATED")
        paths.add(path)
        size = nonnegative_int(
            item.get("bytes"), "ATTENDED_MULTIPLAYER_SUMMARY_ARTIFACT_SIZE_INVALID"
        )
        total_bytes += size
        if total_bytes > MAX_ARTIFACT_BYTES:
            fail("ATTENDED_MULTIPLAYER_SUMMARY_ARTIFACT_BYTE_LIMIT_EXCEEDED")
        records.append(
            {
                "path": path,
                "bytes": size,
                "sha256": digest(
                    item.get("sha256"),
                    "ATTENDED_MULTIPLAYER_SUMMARY_ARTIFACT_DIGEST_INVALID",
                ),
            }
        )
    return sorted(records, key=lambda record: str(record["path"]).casefold())


def _required_role_artifacts(role_id: str, artifact_paths: set[str]) -> list[str]:
    base = f"roles/{role_id}"
    required = {
        f"{base}/gameplay.avi",
        f"{base}/godot.log",
        f"{base}/journey-report.json",
        f"{base}/contact-sheet.png",
    }
    screenshots = sorted(
        path
        for path in artifact_paths
        if path.startswith(f"{base}/screenshots/frame-") and path.endswith(".png")
    )
    if not screenshots:
        fail("ATTENDED_MULTIPLAYER_ROLE_SCREENSHOT_EVIDENCE_MISSING")
    required.add(screenshots[0])
    if not required.issubset(artifact_paths):
        fail("ATTENDED_MULTIPLAYER_ROLE_ARTIFACT_MISSING")
    return sorted(required)


def _verify_role_result(role: object, artifact_paths: set[str]) -> dict[str, Any]:
    if not is_record(role):
        fail("ATTENDED_MULTIPLAYER_ROLE_INVALID")
    value = dict(role)
    role_id = safe_id(value.get("id"), "ATTENDED_MULTIPLAYER_ROLE_ID_INVALID")
    if value.get("status") != "passed":
        fail("ATTENDED_MULTIPLAYER_ROLE_NOT_PASSABLE")
    if not isinstance(value.get("required"), bool):
        fail("ATTENDED_MULTIPLAYER_ROLE_REQUIRED_INVALID")
    if value.get("syntheticInput") is not True or value.get("concurrentClient") is not True:
        fail("ATTENDED_MULTIPLAYER_ROLE_EXECUTION_BOUNDARY_INVALID")
    if value.get("findings") != []:
        fail("ATTENDED_MULTIPLAYER_ROLE_FINDINGS_PRESENT")
    process = value.get("process")
    if not is_record(process):
        fail("ATTENDED_MULTIPLAYER_ROLE_PROCESS_INVALID")
    if (
        process.get("exitCode") != 0
        or process.get("timedOut") is not False
        or process.get("artifactBudgetExceeded") is not False
    ):
        fail("ATTENDED_MULTIPLAYER_ROLE_PROCESS_FAILED")
    harness = value.get("harness")
    if not is_record(harness) or harness.get("status") != "passed":
        fail("ATTENDED_MULTIPLAYER_ROLE_HARNESS_FAILED")
    visual = value.get("visual")
    if (
        not is_record(visual)
        or visual.get("status") != "passed"
        or visual.get("findings") != []
    ):
        fail("ATTENDED_MULTIPLAYER_ROLE_VISUAL_FAILED")
    return {
        "id": role_id,
        "personaId": value.get("personaId"),
        "required": value["required"],
        "status": "passed",
        "scene": value.get("scene"),
        "windowPosition": value.get("windowPosition"),
        "syntheticInput": True,
        "concurrentClient": True,
        "processExitCode": 0,
        "harnessStatus": "passed",
        "visualStatus": "passed",
        "requiredEvidence": _required_role_artifacts(role_id, artifact_paths),
    }


def verify_multiplayer_summary_sources(
    *, summary_path: Path, artifact_root: Path
) -> dict[str, Any]:
    summary, summary_bytes, summary_file = load_json_bytes(summary_path, "SUMMARY")
    root = assert_no_symlink_chain(artifact_root).resolve(strict=True)
    try:
        summary_file.relative_to(root)
    except ValueError:
        fail("ATTENDED_MULTIPLAYER_SUMMARY_ROOT_MISMATCH")
    if summary_file.name != "multiplayer-agent-summary.json":
        fail("ATTENDED_MULTIPLAYER_SUMMARY_NAME_INVALID")
    if summary.get("schemaVersion") != "1.0" or summary.get("status") != "passed":
        fail("ATTENDED_MULTIPLAYER_SUMMARY_NOT_PASSABLE")

    lab_sha = exact_sha(summary.get("labSha"), "ATTENDED_MULTIPLAYER_LAB_SHA_INVALID")
    target_sha = exact_sha(
        summary.get("targetSha"), "ATTENDED_MULTIPLAYER_TARGET_SHA_INVALID"
    )
    run_id = safe_id(summary.get("runId"), "ATTENDED_MULTIPLAYER_RUN_ID_INVALID")
    session_label = bounded_line(
        summary.get("sessionLabel"), "ATTENDED_MULTIPLAYER_SESSION_LABEL_INVALID", 128
    )
    generated_text, generated_at = exact_timestamp(
        summary.get("generatedAt"), "ATTENDED_MULTIPLAYER_GENERATED_AT_INVALID"
    )
    duration = summary.get("durationSeconds")
    if (
        not isinstance(duration, (int, float))
        or isinstance(duration, bool)
        or duration <= 0
        or duration > 14_400
    ):
        fail("ATTENDED_MULTIPLAYER_DURATION_INVALID")
    if summary.get("nativeDesktopEvidence") is not True:
        fail("ATTENDED_MULTIPLAYER_NATIVE_DESKTOP_MISSING")
    if summary.get("interactiveDesktopRequired") is not True:
        fail("ATTENDED_MULTIPLAYER_INTERACTIVE_REQUIREMENT_MISSING")
    if summary.get("validationStatus") != "passed":
        fail("ATTENDED_MULTIPLAYER_VALIDATION_FAILED")
    if summary.get("targetMutationDetected") is not False:
        fail("ATTENDED_MULTIPLAYER_TARGET_MUTATION_DETECTED")
    if summary.get("targetStatusBefore") != summary.get("targetStatusAfter"):
        fail("ATTENDED_MULTIPLAYER_TARGET_STATUS_CHANGED")
    if summary.get("findings") != [] or summary.get("validationFindings") != []:
        fail("ATTENDED_MULTIPLAYER_SUMMARY_FINDINGS_PRESENT")

    lease = summary.get("desktopLease")
    if (
        not is_record(lease)
        or lease.get("acquired") is not True
        or lease.get("name") != DESKTOP_LEASE_NAME
    ):
        fail("ATTENDED_MULTIPLAYER_DESKTOP_LEASE_INVALID")
    positive_int(lease.get("ownerPid"), "ATTENDED_MULTIPLAYER_LEASE_OWNER_INVALID")

    hardware = summary.get("hardware")
    if not is_record(hardware):
        fail("ATTENDED_MULTIPLAYER_HARDWARE_INVALID")
    session = hardware.get("session")
    if not is_record(session):
        fail("ATTENDED_MULTIPLAYER_SESSION_INVALID")
    if session.get("interactive") is not True or session.get("explorerInSameSession") is not True:
        fail("ATTENDED_MULTIPLAYER_SESSION_NOT_INTERACTIVE")
    windows_session_id = positive_int(
        session.get("sessionId"), "ATTENDED_MULTIPLAYER_WINDOWS_SESSION_INVALID", 2**31 - 1
    )

    actual_inventory = inventory_artifacts(root)
    declared_inventory = _normalize_summary_inventory(summary.get("artifacts"))
    if actual_inventory != declared_inventory:
        fail("ATTENDED_MULTIPLAYER_ARTIFACT_INVENTORY_MISMATCH")
    artifact_paths = {str(record["path"]) for record in actual_inventory}
    common_required = {
        "hardware.json",
        "profile.normalized.json",
        "run-context.json",
        "source-archive.json",
        "validation/report.json",
    }
    if not common_required.issubset(artifact_paths):
        fail("ATTENDED_MULTIPLAYER_COMMON_ARTIFACT_MISSING")

    roles_value = summary.get("roles")
    if not isinstance(roles_value, list) or not 2 <= len(roles_value) <= 8:
        fail("ATTENDED_MULTIPLAYER_ROLE_COUNT_INVALID")
    if summary.get("concurrentRoleCount") != len(roles_value):
        fail("ATTENDED_MULTIPLAYER_CONCURRENT_ROLE_COUNT_MISMATCH")
    roles = [_verify_role_result(role, artifact_paths) for role in roles_value]
    role_ids = [str(role["id"]) for role in roles]
    if len(set(role_ids)) != len(role_ids):
        fail("ATTENDED_MULTIPLAYER_ROLE_ID_DUPLICATED")

    retained_bytes = sum(int(record["bytes"]) for record in actual_inventory)
    execution_budget = summary.get("executionBudget")
    if not is_record(execution_budget):
        fail("ATTENDED_MULTIPLAYER_EXECUTION_BUDGET_INVALID")
    if execution_budget.get("measurementComplete") is not True:
        fail("ATTENDED_MULTIPLAYER_EXECUTION_BUDGET_INCOMPLETE")
    if execution_budget.get("retainedArtifactBytes") != retained_bytes:
        fail("ATTENDED_MULTIPLAYER_RETAINED_BYTES_MISMATCH")
    if execution_budget.get("retainedArtifactFiles") != len(actual_inventory):
        fail("ATTENDED_MULTIPLAYER_RETAINED_FILES_MISMATCH")
    maximum_bytes = positive_int(
        execution_budget.get("maximumArtifactBytes"),
        "ATTENDED_MULTIPLAYER_MAXIMUM_BYTES_INVALID",
        MAX_ARTIFACT_BYTES,
    )
    if retained_bytes > maximum_bytes:
        fail("ATTENDED_MULTIPLAYER_RETAINED_BYTES_EXCEEDED")

    return {
        "campaignSource": "godot-game-test-lab-multiplayer-summary",
        "runId": run_id,
        "labSha": lab_sha,
        "targetSha": target_sha,
        "sessionLabel": session_label,
        "generatedAt": generated_text,
        "generatedAtInstant": generated_at,
        "durationSeconds": float(duration),
        "summaryBytes": len(summary_bytes),
        "summarySha256": sha256_bytes(summary_bytes),
        "artifactCount": len(actual_inventory),
        "artifactBytes": retained_bytes,
        "artifactInventorySha256": sha256_object(actual_inventory),
        "windowsSessionId": windows_session_id,
        "desktopLeaseName": DESKTOP_LEASE_NAME,
        "roles": roles,
        "targetMutationDetected": False,
        "nativeDesktopEvidence": True,
        "interactiveDesktop": True,
        "explorerInSameSession": True,
    }
