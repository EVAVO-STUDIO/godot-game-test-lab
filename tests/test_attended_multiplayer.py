from __future__ import annotations

import json
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from godot_game_test_lab import attended_multiplayer as subject
from godot_game_test_lab import attended_multiplayer_common as subject_common


def _fixture(root: Path, generated_at: datetime | None = None):
    artifacts = root / "artifacts"
    generated = generated_at or datetime.now(UTC) - timedelta(minutes=2)
    files = {
        "hardware.json": b"{}\n",
        "profile.normalized.json": b"{}\n",
        "run-context.json": b"{}\n",
        "source-archive.json": b"{}\n",
        "validation/report.json": b'{"status":"passed"}\n',
    }
    for role in ("host", "guest"):
        files.update(
            {
                f"roles/{role}/gameplay.avi": (role + "-movie").encode(),
                f"roles/{role}/godot.log": b"clean\n",
                f"roles/{role}/journey-report.json": b'{"status":"passed"}\n',
                f"roles/{role}/contact-sheet.png": b"\x89PNG\r\n\x1a\nfixture",
                f"roles/{role}/screenshots/frame-01.png": (
                    b"\x89PNG\r\n\x1a\nfixture"
                ),
            }
        )
    for relative, payload in files.items():
        path = artifacts / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)

    inventory = subject_common.inventory_artifacts(artifacts)
    retained_bytes = sum(item["bytes"] for item in inventory)
    roles = []
    for index, role in enumerate(("host", "guest")):
        base = f"roles/{role}"
        roles.append(
            {
                "id": role,
                "personaId": f"persona-{role}",
                "required": True,
                "status": "passed",
                "scene": "configured main scene",
                "windowPosition": f"{32 + index * 48},32",
                "syntheticInput": True,
                "concurrentClient": True,
                "process": {
                    "exitCode": 0,
                    "timedOut": False,
                    "artifactBudgetExceeded": False,
                },
                "harness": {"status": "passed"},
                "visual": {
                    "status": "passed",
                    "findings": [],
                    "evidence": [
                        f"{base}/gameplay.avi",
                        f"{base}/contact-sheet.png",
                        f"{base}/screenshots/frame-01.png",
                    ],
                },
                "findings": [],
                "evidence": [
                    f"{base}/godot.log",
                    f"{base}/journey-report.json",
                ],
            }
        )
    summary = {
        "schemaVersion": "1.0",
        "runId": "multiplayer-test-001",
        "status": "passed",
        "generatedAt": generated.isoformat(),
        "durationSeconds": 15.5,
        "labSha": "a" * 40,
        "targetSha": "b" * 40,
        "sessionLabel": "fixture-session",
        "interactiveDesktopRequired": True,
        "nativeDesktopEvidence": True,
        "desktopLease": {
            "acquired": True,
            "name": subject.DESKTOP_LEASE_NAME,
            "ownerPid": 1234,
        },
        "hardware": {
            "session": {
                "sessionId": 7,
                "interactive": True,
                "explorerInSameSession": True,
            }
        },
        "validationStatus": "passed",
        "validationFindings": [],
        "roles": roles,
        "concurrentRoleCount": 2,
        "targetMutationDetected": False,
        "targetStatusBefore": "",
        "targetStatusAfter": "",
        "executionBudget": {
            "maximumArtifactBytes": 1024**3,
            "retainedArtifactBytes": retained_bytes,
            "retainedArtifactFiles": len(inventory),
            "measurementComplete": True,
        },
        "findings": [],
        "artifacts": inventory,
    }
    summary_path = artifacts / "multiplayer-agent-summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return artifacts, summary_path, generated


def test_compiles_and_reverifies_exact_attended_receipt(tmp_path: Path) -> None:
    artifacts, summary_path, generated = _fixture(tmp_path)
    evidence = subject.verify_multiplayer_summary_sources(
        summary_path=summary_path,
        artifact_root=artifacts,
    )
    attested = generated + timedelta(minutes=3)
    attestation = subject.build_operator_attestation(
        evidence=evidence,
        campaign_id="campaign-001",
        operator_id="Greg Parker",
        windows_session_id=7,
        confirmation="ATTEND multiplayer-test-001",
        now=attested,
    )
    receipt = subject.compile_attended_multiplayer_receipt(
        evidence=evidence,
        attestation=attestation,
        now=attested + timedelta(minutes=1),
    )
    verified = subject.verify_attended_multiplayer_receipt(
        receipt,
        evidence=evidence,
        attestation=attestation,
    )
    assert verified["status"] == "passed"
    assert verified["authority"]["publicationAuthority"] is False
    assert len(verified["roles"]) == 2


def test_changed_artifact_is_rejected(tmp_path: Path) -> None:
    artifacts, summary_path, _generated = _fixture(tmp_path)
    (artifacts / "roles/host/godot.log").write_text("changed\n", encoding="utf-8")
    with pytest.raises(
        subject.AttendedMultiplayerError,
        match="ARTIFACT_INVENTORY_MISMATCH",
    ):
        subject.verify_multiplayer_summary_sources(
            summary_path=summary_path,
            artifact_root=artifacts,
        )


def test_confirmation_and_session_must_match(tmp_path: Path) -> None:
    artifacts, summary_path, generated = _fixture(tmp_path)
    evidence = subject.verify_multiplayer_summary_sources(
        summary_path=summary_path,
        artifact_root=artifacts,
    )
    with pytest.raises(
        subject.AttendedMultiplayerError,
        match="CONFIRMATION_MISMATCH",
    ):
        subject.build_operator_attestation(
            evidence=evidence,
            campaign_id="campaign-001",
            operator_id="Greg Parker",
            windows_session_id=7,
            confirmation="ATTEND another-run",
            now=generated + timedelta(minutes=1),
        )
    with pytest.raises(
        subject.AttendedMultiplayerError,
        match="ATTESTATION_SESSION_MISMATCH",
    ):
        subject.build_operator_attestation(
            evidence=evidence,
            campaign_id="campaign-001",
            operator_id="Greg Parker",
            windows_session_id=8,
            confirmation="ATTEND multiplayer-test-001",
            now=generated + timedelta(minutes=1),
        )


def test_stale_attestation_is_rejected(tmp_path: Path) -> None:
    artifacts, summary_path, generated = _fixture(tmp_path)
    evidence = subject.verify_multiplayer_summary_sources(
        summary_path=summary_path,
        artifact_root=artifacts,
    )
    with pytest.raises(
        subject.AttendedMultiplayerError,
        match="ATTESTATION_TIME_INVALID",
    ):
        subject.build_operator_attestation(
            evidence=evidence,
            campaign_id="campaign-001",
            operator_id="Greg Parker",
            windows_session_id=7,
            confirmation="ATTEND multiplayer-test-001",
            now=generated + timedelta(minutes=31),
        )


def test_authority_escalation_is_rejected(tmp_path: Path) -> None:
    artifacts, summary_path, generated = _fixture(tmp_path)
    evidence = subject.verify_multiplayer_summary_sources(
        summary_path=summary_path,
        artifact_root=artifacts,
    )
    attested = generated + timedelta(minutes=2)
    attestation = subject.build_operator_attestation(
        evidence=evidence,
        campaign_id="campaign-001",
        operator_id="Greg Parker",
        windows_session_id=7,
        confirmation="ATTEND multiplayer-test-001",
        now=attested,
    )
    receipt = subject.compile_attended_multiplayer_receipt(
        evidence=evidence,
        attestation=attestation,
        now=attested + timedelta(minutes=1),
    )
    receipt["authority"]["publicationAuthority"] = True
    with pytest.raises(
        subject.AttendedMultiplayerError,
        match="RECEIPT_SOURCE_MISMATCH",
    ):
        subject.verify_attended_multiplayer_receipt(
            receipt,
            evidence=evidence,
            attestation=attestation,
        )


def test_create_only_output_and_artifact_root_boundary(tmp_path: Path) -> None:
    artifacts, _summary_path, _generated = _fixture(tmp_path)
    output = tmp_path / "receipt.json"
    subject_common.write_json_create_only(output, {"status": "passed"})
    with pytest.raises(
        subject.AttendedMultiplayerError,
        match="OUTPUT_ALREADY_EXISTS",
    ):
        subject_common.write_json_create_only(output, {"status": "passed"})
    with pytest.raises(
        subject.AttendedMultiplayerError,
        match="OUTPUT_INSIDE_ARTIFACT_ROOT",
    ):
        subject_common.ensure_output_outside_artifacts(
            artifacts / "receipt.json",
            artifacts,
        )
