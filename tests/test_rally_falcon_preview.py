from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from godot_game_test_lab.rally_falcon_preview import (
    AUTHORITY,
    FalconPreviewError,
    _hash_object,
    capabilities,
    compile_preview_plan,
    validate_preview_plan,
    validate_preview_receipt,
)


INTAKE_AUTHORITY = {
    "validateWorkerEvidence": True,
    "compileReviewIntake": True,
    "importAsset": False,
    "modifyImportSettings": False,
    "modifyCollision": False,
    "modifyScene": False,
    "runtimeAdmission": False,
    "canonicalPromotion": False,
    "gitMutation": False,
    "deployment": False,
    "publication": False,
    "clientRelease": False,
    "namedHumanVisualDecisionRequired": True,
}


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _evidence(path: Path, root: Path) -> dict:
    payload = path.read_bytes()
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": _sha_bytes(payload),
        "bytes": len(payload),
    }


def _make_intake(root: Path) -> Path:
    model = root / "model.glb"
    model.write_bytes(b"glTF" + b"\x00" * 60)
    body = {
        "contractVersion": "evavo_rally_falcon_worker_intake_v1",
        "protocolVersion": "2026-08-18.1",
        "consumerRepository": "EVAVO-STUDIO/godot-462-isometric-rally",
        "sourceReceipt": {
            "path": "falcon-worker-receipt.json",
            "sha256": "d" * 64,
            "bytes": 100,
        },
        "sourceReceiptSha256": "e" * 64,
        "producerRepository": "EVAVO-STUDIO/evavo-3d-studio",
        "producerCommit": "a" * 40,
        "model": _evidence(model, root),
        "prototypeReceipt": {
            "path": "qa/prototype-receipt.json",
            "sha256": "f" * 64,
            "bytes": 100,
        },
        "status": "verified-worker-evidence",
        "runtimeReady": False,
        "automaticImport": False,
        "automaticSceneMutation": False,
        "authority": deepcopy(INTAKE_AUTHORITY),
    }
    intake = {**body, "intakeSha256": _hash_object(body)}
    path = root / "falcon-intake.json"
    _write_json(path, intake)
    return path


def _make_native_receipt(artifacts: Path, plan: dict) -> dict:
    native = {
        "schemaVersion": "2.0",
        "status": "passed",
        "labRepository": "EVAVO-STUDIO/godot-game-test-lab",
        "labSha": plan["lab"]["head"],
        "targetSha": plan["target"]["head"],
        "targetUnchanged": True,
    }
    path = artifacts / "native-validation-receipt.json"
    _write_json(path, native)
    return _evidence(path, artifacts)


def _make_preview_receipt(artifacts: Path, plan: dict) -> dict:
    frames = []
    for index in range(4):
        frame = artifacts / f"frame-{index:02d}.png"
        frame.write_bytes(b"\x89PNG\r\n\x1a\n" + bytes([index]) + b"falcon-frame")
        frames.append(_evidence(frame, artifacts))
    body = {
        "schemaVersion": 1,
        "kind": "evavo-godot-rally-falcon-preview-receipt-v1",
        "assetId": "falcon-rally-production-v1",
        "programId": "rally-vertical-slice-v1",
        "planSha256": plan["planSha256"],
        "lab": deepcopy(plan["lab"]),
        "target": deepcopy(plan["target"]),
        "candidate": deepcopy(plan["candidate"]),
        "nativeValidation": _make_native_receipt(artifacts, plan),
        "godot": {
            "version": "4.6.2",
            "executableSha256": "9" * 64,
            "realProcess": True,
        },
        "import": {"attempted": True, "passed": True},
        "resourceLoad": {"passed": True},
        "renderedFrames": frames,
        "processExitCode": 0,
        "targetUnchanged": True,
        "status": "review-required",
        "creativeApproval": False,
        "runtimeAdmission": False,
        "canonicalImport": False,
        "forbiddenEvidenceObserved": [],
        "authority": deepcopy(AUTHORITY),
    }
    return {**body, "receiptSha256": _hash_object(body)}


def test_compile_plan_binds_exact_intake_and_model_bytes(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    intake = _make_intake(evidence)
    plan = compile_preview_plan(
        intake_path=intake,
        evidence_root=evidence,
        rally_head="b" * 40,
        lab_head="c" * 40,
    )
    assert validate_preview_plan(plan, evidence)
    assert plan["candidate"]["path"] == "model.glb"
    assert plan["execution"]["minimumGodotVersion"] == "4.6.2"
    assert plan["execution"]["minimumRenderedFrames"] == 4
    assert plan["runtimeReadyAfterPass"] is False
    assert plan["canonicalImportAfterPass"] is False
    assert all(value is False for value in plan["authority"].values())


def test_plan_fails_if_candidate_bytes_change(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    intake = _make_intake(evidence)
    plan = compile_preview_plan(
        intake_path=intake,
        evidence_root=evidence,
        rally_head="b" * 40,
        lab_head="c" * 40,
    )
    (evidence / "model.glb").write_bytes(b"changed")
    with pytest.raises(FalconPreviewError, match="bytes differ"):
        validate_preview_plan(plan, evidence)


def test_real_preview_receipt_validates_without_granting_admission(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    artifacts = tmp_path / "artifacts"
    evidence.mkdir()
    artifacts.mkdir()
    intake = _make_intake(evidence)
    plan = compile_preview_plan(
        intake_path=intake,
        evidence_root=evidence,
        rally_head="b" * 40,
        lab_head="c" * 40,
    )
    receipt = _make_preview_receipt(artifacts, plan)
    assert validate_preview_receipt(receipt, plan, evidence, artifacts)
    assert receipt["status"] == "review-required"
    assert receipt["creativeApproval"] is False
    assert receipt["runtimeAdmission"] is False
    assert receipt["canonicalImport"] is False


def test_preview_rejects_nonzero_process_exit_after_rehash(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    artifacts = tmp_path / "artifacts"
    evidence.mkdir()
    artifacts.mkdir()
    intake = _make_intake(evidence)
    plan = compile_preview_plan(
        intake_path=intake,
        evidence_root=evidence,
        rally_head="b" * 40,
        lab_head="c" * 40,
    )
    receipt = _make_preview_receipt(artifacts, plan)
    receipt["processExitCode"] = 1
    body = dict(receipt)
    body.pop("receiptSha256")
    receipt["receiptSha256"] = _hash_object(body)
    with pytest.raises(FalconPreviewError, match="exit zero"):
        validate_preview_receipt(receipt, plan, evidence, artifacts)


def test_preview_rejects_insufficient_frames_after_rehash(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    artifacts = tmp_path / "artifacts"
    evidence.mkdir()
    artifacts.mkdir()
    intake = _make_intake(evidence)
    plan = compile_preview_plan(
        intake_path=intake,
        evidence_root=evidence,
        rally_head="b" * 40,
        lab_head="c" * 40,
    )
    receipt = _make_preview_receipt(artifacts, plan)
    receipt["renderedFrames"] = receipt["renderedFrames"][:3]
    body = dict(receipt)
    body.pop("receiptSha256")
    receipt["receiptSha256"] = _hash_object(body)
    with pytest.raises(FalconPreviewError, match="at least four"):
        validate_preview_receipt(receipt, plan, evidence, artifacts)


def test_preview_rejects_authority_escalation_after_rehash(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    artifacts = tmp_path / "artifacts"
    evidence.mkdir()
    artifacts.mkdir()
    intake = _make_intake(evidence)
    plan = compile_preview_plan(
        intake_path=intake,
        evidence_root=evidence,
        rally_head="b" * 40,
        lab_head="c" * 40,
    )
    receipt = _make_preview_receipt(artifacts, plan)
    receipt["authority"]["runtimeAdmission"] = True
    body = dict(receipt)
    body.pop("receiptSha256")
    receipt["receiptSha256"] = _hash_object(body)
    with pytest.raises(FalconPreviewError, match="authority expanded"):
        validate_preview_receipt(receipt, plan, evidence, artifacts)


def test_capabilities_are_validation_only() -> None:
    value = capabilities()
    assert value["executesGodot"] is False
    assert value["validatesRallyIntakeBytes"] is True
    assert value["validatesRealGodotPreviewReceipt"] is True
    assert value["minimumRenderedFrames"] == 4
    assert all(item is False for item in value["authority"].values())


def test_cli_entrypoint_is_registered() -> None:
    root = Path(__file__).resolve().parents[1]
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    assert (
        'godot-lab-rally-falcon-preview = "godot_game_test_lab.rally_falcon_preview:main"'
        in pyproject
    )
