from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from godot_game_test_lab.rally_falcon_preview import (
    AUTHORITY,
    FalconPreviewError,
    capabilities,
    compile_preview_plan,
    validate_preview_plan,
    validate_preview_receipt,
    _hash_object,
)

INTAKE_AUTHORITY = {
    "validateWorkerEvidence": True,
    "compileReviewIntake": True,
    "readEvidence": True,
    "writeEvidence": True,
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


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_intake(root: Path) -> tuple[Path, bytes]:
    root.mkdir(parents=True, exist_ok=True)
    model = b"glTF-fixture-falcon-model"
    (root / "model.glb").write_bytes(model)
    source_receipt = {
        "schemaVersion": 1,
        "kind": "evavo-falcon-production-receipt-v1",
        "assetId": "falcon-rally-production-v1",
    }
    source_body = deepcopy(source_receipt)
    source_receipt["receiptSha256"] = _hash_object(source_body)
    _write_json(root / "source-receipt.json", source_receipt)
    source_receipt_sha = hashlib.sha256(
        (root / "source-receipt.json").read_bytes()
    ).hexdigest()
    body = {
        "contractVersion": "evavo_rally_falcon_worker_intake_v1",
        "protocolVersion": "2026-08-18.1",
        "consumerRepository": "EVAVO-STUDIO/godot-462-isometric-rally",
        "sourceReceipt": "source-receipt.json",
        "sourceReceiptSha256": source_receipt_sha,
        "producerRepository": "EVAVO-STUDIO/the-falcon",
        "producerCommit": "a" * 40,
        "model": {
            "path": "model.glb",
            "sha256": hashlib.sha256(model).hexdigest(),
            "bytes": len(model),
        },
        "prototypeReceipt": None,
        "status": "verified-worker-evidence",
        "runtimeReady": False,
        "automaticImport": False,
        "automaticSceneMutation": False,
        "authority": deepcopy(INTAKE_AUTHORITY),
    }
    body["intakeSha256"] = _hash_object(body)
    intake = root / "rally-intake.json"
    _write_json(intake, body)
    return intake, model


def _write_native_validation(
    artifact_root: Path,
    *,
    lab_head: str,
    rally_head: str,
) -> dict[str, object]:
    value = {
        "schemaVersion": "2.0",
        "status": "passed",
        "labRepository": "EVAVO-STUDIO/godot-game-test-lab",
        "labSha": lab_head,
        "targetSha": rally_head,
        "targetUnchanged": True,
    }
    path = artifact_root / "native-validation.json"
    _write_json(path, value)
    data = path.read_bytes()
    return {
        "path": path.relative_to(artifact_root).as_posix(),
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
    }


def _write_frame(artifact_root: Path, index: int) -> dict[str, object]:
    payload = b"\x89PNG\r\n\x1a\n" + f"real-frame-{index}".encode("ascii")
    path = artifact_root / "frames" / f"frame-{index:02d}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return {
        "path": path.relative_to(artifact_root).as_posix(),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload),
    }


def _receipt(
    *,
    plan: dict[str, object],
    artifact_root: Path,
    rally_head: str,
    lab_head: str,
) -> dict[str, object]:
    body = {
        "schemaVersion": 1,
        "kind": "evavo-godot-rally-falcon-preview-receipt-v1",
        "assetId": "falcon-rally-production-v1",
        "programId": "rally-vertical-slice-v1",
        "planSha256": plan["planSha256"],
        "lab": {
            "repository": "EVAVO-STUDIO/godot-game-test-lab",
            "head": lab_head,
        },
        "target": {
            "repository": "EVAVO-STUDIO/godot-462-isometric-rally",
            "head": rally_head,
        },
        "candidate": deepcopy(plan["candidate"]),
        "nativeValidation": _write_native_validation(
            artifact_root,
            lab_head=lab_head,
            rally_head=rally_head,
        ),
        "godot": {
            "realProcess": True,
            "version": "4.6.2",
            "executableSha256": "b" * 64,
        },
        "import": {"attempted": True, "passed": True},
        "resourceLoad": {"passed": True},
        "renderedFrames": [_write_frame(artifact_root, index) for index in range(1, 5)],
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


def test_compiles_exact_intake_bound_isolated_preview_plan(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    intake, model = _write_intake(evidence)
    plan = compile_preview_plan(
        intake_path=intake,
        evidence_root=evidence,
        rally_head="1" * 40,
        lab_head="2" * 40,
    )
    assert validate_preview_plan(plan, evidence)
    assert plan["candidate"] == {
        "path": "model.glb",
        "sha256": hashlib.sha256(model).hexdigest(),
        "bytes": len(model),
    }
    assert plan["execution"]["isolatedExternalWorkspaceRequired"] is True
    assert plan["execution"]["realGodotProcessRequired"] is True
    assert plan["execution"]["targetMutationAllowed"] is False
    assert plan["authority"] == AUTHORITY
    assert plan["runtimeReadyAfterPass"] is False
    assert plan["canonicalImportAfterPass"] is False


def test_plan_rejects_intake_drift_authority_expansion_and_bad_hash(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    intake, _model = _write_intake(evidence)
    value = json.loads(intake.read_text(encoding="utf-8"))
    value["runtimeReady"] = True
    body = deepcopy(value)
    body.pop("intakeSha256")
    value["intakeSha256"] = _hash_object(body)
    _write_json(intake, value)
    with pytest.raises(FalconPreviewError, match="non-operative state"):
        compile_preview_plan(
            intake_path=intake,
            evidence_root=evidence,
            rally_head="1" * 40,
            lab_head="2" * 40,
        )

    intake, _model = _write_intake(tmp_path / "other")
    value = json.loads(intake.read_text(encoding="utf-8"))
    value["authority"]["runtimeAdmission"] = True
    body = deepcopy(value)
    body.pop("intakeSha256")
    value["intakeSha256"] = _hash_object(body)
    _write_json(intake, value)
    with pytest.raises(FalconPreviewError, match="authority expanded"):
        compile_preview_plan(
            intake_path=intake,
            evidence_root=intake.parent,
            rally_head="1" * 40,
            lab_head="2" * 40,
        )

    intake, _model = _write_intake(tmp_path / "third")
    value = json.loads(intake.read_text(encoding="utf-8"))
    value["intakeSha256"] = "0" * 64
    _write_json(intake, value)
    with pytest.raises(FalconPreviewError, match="self-hash differs"):
        compile_preview_plan(
            intake_path=intake,
            evidence_root=intake.parent,
            rally_head="1" * 40,
            lab_head="2" * 40,
        )


def test_validates_real_godot_import_load_and_rendered_frame_receipt(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    artifacts = tmp_path / "artifacts"
    evidence.mkdir()
    artifacts.mkdir()
    intake, _model = _write_intake(evidence)
    rally_head = "1" * 40
    lab_head = "2" * 40
    plan = compile_preview_plan(
        intake_path=intake,
        evidence_root=evidence,
        rally_head=rally_head,
        lab_head=lab_head,
    )
    receipt = _receipt(
        plan=plan,
        artifact_root=artifacts,
        rally_head=rally_head,
        lab_head=lab_head,
    )
    assert validate_preview_receipt(receipt, plan, evidence, artifacts)
    assert receipt["status"] == "review-required"
    assert receipt["creativeApproval"] is False
    assert receipt["runtimeAdmission"] is False
    assert receipt["canonicalImport"] is False


def test_receipt_rejects_placeholders_nonzero_process_mutation_and_native_mismatch(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence"
    artifacts = tmp_path / "artifacts"
    evidence.mkdir()
    artifacts.mkdir()
    intake, _model = _write_intake(evidence)
    rally_head = "1" * 40
    lab_head = "2" * 40
    plan = compile_preview_plan(
        intake_path=intake,
        evidence_root=evidence,
        rally_head=rally_head,
        lab_head=lab_head,
    )

    receipt = _receipt(
        plan=plan,
        artifact_root=artifacts,
        rally_head=rally_head,
        lab_head=lab_head,
    )
    receipt["forbiddenEvidenceObserved"] = ["fixture-only-render"]
    body = deepcopy(receipt)
    body.pop("receiptSha256")
    receipt["receiptSha256"] = _hash_object(body)
    with pytest.raises(FalconPreviewError, match="forbidden evidence"):
        validate_preview_receipt(receipt, plan, evidence, artifacts)

    receipt = _receipt(
        plan=plan,
        artifact_root=artifacts,
        rally_head=rally_head,
        lab_head=lab_head,
    )
    receipt["processExitCode"] = 1
    body = deepcopy(receipt)
    body.pop("receiptSha256")
    receipt["receiptSha256"] = _hash_object(body)
    with pytest.raises(FalconPreviewError, match="exit zero"):
        validate_preview_receipt(receipt, plan, evidence, artifacts)

    receipt = _receipt(
        plan=plan,
        artifact_root=artifacts,
        rally_head=rally_head,
        lab_head=lab_head,
    )
    receipt["targetUnchanged"] = False
    body = deepcopy(receipt)
    body.pop("receiptSha256")
    receipt["receiptSha256"] = _hash_object(body)
    with pytest.raises(FalconPreviewError, match="repository changed"):
        validate_preview_receipt(receipt, plan, evidence, artifacts)

    receipt = _receipt(
        plan=plan,
        artifact_root=artifacts,
        rally_head=rally_head,
        lab_head=lab_head,
    )
    native_path = artifacts / receipt["nativeValidation"]["path"]
    native = json.loads(native_path.read_text(encoding="utf-8"))
    native["targetSha"] = "3" * 40
    _write_json(native_path, native)
    native_bytes = native_path.read_bytes()
    receipt["nativeValidation"]["sha256"] = hashlib.sha256(native_bytes).hexdigest()
    receipt["nativeValidation"]["bytes"] = len(native_bytes)
    body = deepcopy(receipt)
    body.pop("receiptSha256")
    receipt["receiptSha256"] = _hash_object(body)
    with pytest.raises(FalconPreviewError, match="exact unchanged target"):
        validate_preview_receipt(receipt, plan, evidence, artifacts)


def test_capabilities_make_non_execution_and_non_admission_explicit() -> None:
    value = capabilities()
    assert value["compilesHashBoundPlan"] is True
    assert value["validatesRealGodotPreviewReceipt"] is True
    assert value["executesGodot"] is False
    assert value["authority"] == AUTHORITY
