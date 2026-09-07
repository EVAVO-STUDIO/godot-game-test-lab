from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from godot_game_test_lab import attended_multiplayer as subject
from godot_game_test_lab import attended_multiplayer_common as subject_common


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _fixture(root: Path, generated_at: datetime | None = None):
    artifacts = root / "artifacts"
    generated = generated_at or datetime.now(UTC) - timedelta(minutes=2)
    lab_sha = "a" * 40
    target_sha = "b" * 40
    profile_sha = "c" * 64
    target_git_root = r"C:\GitRepos\fixture-target"
    project_subpath = "."
    profile_path = "examples/multiplayer-qa.profile.json"
    session_label = "fixture-session"
    maximum_total_seconds = 3600
    maximum_artifact_bytes = 1024**3

    hardware = {
        "session": {
            "sessionId": 7,
            "interactive": True,
            "explorerInSameSession": True,
        }
    }
    normalized_profile = {
        "schemaVersion": "1.0",
        "roles": [{"id": "host"}, {"id": "guest"}],
    }
    run_context = {
        "schemaVersion": "1.0",
        "runId": "multiplayer-test-001",
        "labSha": lab_sha,
        "targetSha": target_sha,
        "targetGitRoot": target_git_root,
        "projectSubpath": project_subpath,
        "profile": profile_path,
        "profileSha256": profile_sha,
        "sessionLabel": session_label,
        "roleCount": 2,
        "maximumTotalSeconds": maximum_total_seconds,
        "maximumArtifactBytes": maximum_artifact_bytes,
    }
    source_archive = {"members": 12, "files": 10, "bytes": 4096}
    validation_report = {"status": "passed"}

    _write_json(artifacts / "hardware.json", hardware)
    _write_json(artifacts / "profile.normalized.json", normalized_profile)
    _write_json(artifacts / "run-context.json", run_context)
    _write_json(artifacts / "source-archive.json", source_archive)
    _write_json(artifacts / "validation/report.json", validation_report)

    files: dict[str, bytes] = {}
    for role in ("host", "guest"):
        files.update(
            {
                f"roles/{role}/gameplay.avi": (role + "-movie").encode(),
                f"roles/{role}/godot.log": b"clean\n",
                f"roles/{role}/journey-report.json": b'{"status":"passed"}\n',
                f"roles/{role}/contact-sheet.png": b"\x89PNG\r\n\x1a\nfixture",
                f"roles/{role}/screenshots/frame-01.png": b"\x89PNG\r\n\x1a\nfixture",
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
        "labSha": lab_sha,
        "targetSha": target_sha,
        "targetGitRoot": target_git_root,
        "projectSubpath": project_subpath,
        "profile": profile_path,
        "profileSha256": profile_sha,
        "sessionLabel": session_label,
        "interactiveDesktopRequired": True,
        "nativeDesktopEvidence": True,
        "desktopLease": {
            "acquired": True,
            "name": subject.DESKTOP_LEASE_NAME,
            "ownerPid": 1234,
        },
        "hardware": hardware,
        "sourceArchive": source_archive,
        "validationStatus": "passed",
        "validationFindings": [],
        "roles": roles,
        "concurrentRoleCount": 2,
        "targetMutationDetected": False,
        "targetStatusBefore": "",
        "targetStatusAfter": "",
        "executionBudget": {
            "maximumTotalSeconds": maximum_total_seconds,
            "maximumArtifactBytes": maximum_artifact_bytes,
            "retainedArtifactBytes": retained_bytes,
            "retainedArtifactFiles": len(inventory),
            "measurementComplete": True,
        },
        "findings": [],
        "artifacts": inventory,
    }
    summary_path = artifacts / "multiplayer-agent-summary.json"
    _write_json(summary_path, summary)
    return artifacts, summary_path, generated


def test_compiles_and_reverifies_exact_attended_receipt(tmp_path: Path) -> None:
    artifacts, summary_path, generated = _fixture(tmp_path)
    evidence = subject.verify_multiplayer_summary_sources(
        summary_path=summary_path,
        artifact_root=artifacts,
    )
    assert evidence["retainedSourceReceiptsVerified"] is True
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
    assert verified["sourceVerification"]["operatorAttestationBoundToExactEvidence"] is True
    assert verified["operatorAttestation"]["boundSummarySha256"] == evidence["summarySha256"]
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


def test_run_context_must_independently_match_summary(tmp_path: Path) -> None:
    artifacts, summary_path, _generated = _fixture(tmp_path)
    run_context_path = artifacts / "run-context.json"
    run_context = json.loads(run_context_path.read_text(encoding="utf-8"))
    run_context["sessionLabel"] = "other-session"
    _write_json(run_context_path, run_context)

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    inventory = subject_common.inventory_artifacts(artifacts)
    summary["artifacts"] = inventory
    summary["executionBudget"]["retainedArtifactBytes"] = sum(
        item["bytes"] for item in inventory
    )
    summary["executionBudget"]["retainedArtifactFiles"] = len(inventory)
    _write_json(summary_path, summary)

    with pytest.raises(
        subject.AttendedMultiplayerError,
        match="RUN_CONTEXT_SUMMARY_MISMATCH",
    ):
        subject.verify_multiplayer_summary_sources(
            summary_path=summary_path,
            artifact_root=artifacts,
        )


def test_attestation_cannot_be_reused_for_changed_evidence(tmp_path: Path) -> None:
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
    changed_evidence = dict(evidence)
    changed_evidence["summarySha256"] = "d" * 64
    with pytest.raises(
        subject.AttendedMultiplayerError,
        match="ATTESTATION_SUMMARY_DIGEST_MISMATCH",
    ):
        subject.compile_attended_multiplayer_receipt(
            evidence=changed_evidence,
            attestation=attestation,
            now=attested + timedelta(minutes=1),
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
