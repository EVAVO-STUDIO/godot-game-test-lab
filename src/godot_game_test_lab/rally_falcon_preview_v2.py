"""Governed Falcon preview planning and evidence validation.

This module does not launch Godot. It independently validates retained Rally
intake bytes, compiles an exact hash-bound isolated preview plan, and validates
retained evidence from the governed real-Godot executor.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path, PurePosixPath
from typing import Any

PLAN_KIND = "evavo-godot-rally-falcon-preview-plan-v2"
RECEIPT_KIND = "evavo-godot-rally-falcon-preview-receipt-v2"
POLICY_KIND = "evavo-godot-rally-falcon-preview-policy-v2"
CAPABILITIES_KIND = "evavo-godot-rally-falcon-preview-capabilities-v2"
ASSET_ID = "falcon-rally-production-v1"
PROGRAM_ID = "rally-vertical-slice-v1"
RALLY_REPOSITORY = "EVAVO-STUDIO/godot-462-isometric-rally"
LAB_REPOSITORY = "EVAVO-STUDIO/godot-game-test-lab"
INTAKE_CONTRACT = "evavo_rally_falcon_worker_intake_v1"
PROTOCOL_VERSION = "2026-08-18.1"
MINIMUM_GODOT_VERSION = "4.6.2"
NATIVE_VALIDATION_ENTRYPOINT = "scripts/Invoke-GodotLabNativeValidation.ps1"
EXECUTOR_PATH = "src/godot_game_test_lab/rally_falcon_preview_execute.py"
MINIMUM_RENDERED_FRAMES = 4
RENDER_WIDTH = 1024
RENDER_HEIGHT = 1024
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA64 = re.compile(r"^[0-9a-f]{64}$")
SHA128 = re.compile(r"^[0-9a-f]{128}$")
SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
VERSION_SEARCH = re.compile(r"(?P<version>\d+\.\d+\.\d+)")
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

AUTHORITY = {
    "creativeApproval": False,
    "runtimeAdmission": False,
    "canonicalImport": False,
    "sceneMutation": False,
    "physicsAuthority": False,
    "collisionAuthority": False,
    "gameplayAuthority": False,
    "targetRepositoryWrite": False,
    "gitMutation": False,
    "commit": False,
    "push": False,
    "publication": False,
    "deployment": False,
    "clientRelease": False,
}

INTAKE_FALSE_AUTHORITY = (
    "importAsset",
    "modifyImportSettings",
    "modifyCollision",
    "modifyScene",
    "runtimeAdmission",
    "canonicalPromotion",
    "gitMutation",
    "deployment",
    "publication",
    "clientRelease",
)


class FalconPreviewError(ValueError):
    """Falcon preview contract failure."""


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _hash_object(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _object(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise FalconPreviewError(f"{label} must be an object")
    return value


def _read_json(path: Path, label: str) -> Mapping[str, Any]:
    if path.is_symlink():
        raise FalconPreviewError(f"{label} may not be a symlink")
    exact = path.resolve(strict=True)
    if not exact.is_file():
        raise FalconPreviewError(f"{label} must be a regular JSON file")
    try:
        value = json.loads(exact.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FalconPreviewError(f"{label} is invalid JSON: {exc}") from exc
    return _object(value, label)


def _self_hash(value: Mapping[str, Any], key: str, label: str) -> str:
    body = deepcopy(dict(value))
    digest = body.pop(key, None)
    if not isinstance(digest, str) or not SHA64.fullmatch(digest):
        raise FalconPreviewError(f"{label} is missing a valid {key}")
    if _hash_object(body) != digest:
        raise FalconPreviewError(f"{label} self-hash differs")
    return digest


def _relative_path(value: Any, label: str) -> PurePosixPath:
    if not isinstance(value, str) or not value:
        raise FalconPreviewError(f"{label} must be a non-empty relative path")
    candidate = PurePosixPath(value)
    if (
        candidate.is_absolute()
        or not candidate.parts
        or any(part in {"", ".", ".."} for part in candidate.parts)
    ):
        raise FalconPreviewError(f"{label} must be a traversal-free relative path")
    return candidate


def _root(path: Path, label: str) -> Path:
    if path.is_symlink():
        raise FalconPreviewError(f"{label} may not be a symlink")
    exact = path.resolve(strict=True)
    if not exact.is_dir():
        raise FalconPreviewError(f"{label} must be a regular directory")
    return exact


def _inside(path: Path, root: Path, label: str) -> Path:
    if path.is_symlink():
        raise FalconPreviewError(f"{label} may not be a symlink")
    exact = path.resolve(strict=True)
    try:
        exact.relative_to(root)
    except ValueError as exc:
        raise FalconPreviewError(f"{label} escapes its evidence root") from exc
    return exact


def _evidence_file(
    root: Path,
    item: Mapping[str, Any],
    label: str,
    *,
    allow_empty: bool = False,
) -> Path:
    if set(item) != {"path", "sha256", "bytes"}:
        raise FalconPreviewError(f"{label} evidence fields differ")
    relative = _relative_path(item.get("path"), f"{label}.path")
    digest = item.get("sha256")
    size = item.get("bytes")
    minimum_size = 0 if allow_empty else 1
    if not isinstance(digest, str) or not SHA64.fullmatch(digest):
        raise FalconPreviewError(f"{label}.sha256 is invalid")
    if not isinstance(size, int) or isinstance(size, bool) or size < minimum_size:
        raise FalconPreviewError(f"{label}.bytes is invalid")
    path = _inside(root.joinpath(*relative.parts), root, label)
    if not path.is_file():
        raise FalconPreviewError(f"{label} must resolve to a regular file")
    if path.stat().st_size != size or _hash_file(path) != digest:
        raise FalconPreviewError(f"{label} bytes differ")
    return path


def _file_evidence(path: Path, root: Path) -> dict[str, Any]:
    exact = _inside(path, root, "evidence")
    if not exact.is_file() or exact.stat().st_size < 1:
        raise FalconPreviewError("evidence file is unsafe")
    return {
        "path": exact.relative_to(root).as_posix(),
        "sha256": _hash_file(exact),
        "bytes": exact.stat().st_size,
    }


def _version(value: Any, label: str) -> tuple[int, int, int]:
    if not isinstance(value, str):
        raise FalconPreviewError(f"{label} must be a semantic version")
    match = SEMVER.fullmatch(value)
    if not match:
        raise FalconPreviewError(f"{label} must be a semantic version")
    return tuple(int(part) for part in match.groups())


def _png_dimensions(path: Path) -> tuple[int, int]:
    with path.open("rb") as handle:
        header = handle.read(24)
    if len(header) < 24 or header[:8] != PNG_SIGNATURE or header[12:16] != b"IHDR":
        raise FalconPreviewError("rendered evidence must be a PNG with an IHDR header")
    return int.from_bytes(header[16:20], "big"), int.from_bytes(header[20:24], "big")


def _validate_process_evidence(root: Path, value: Any, label: str) -> Mapping[str, Any]:
    item = _object(value, label)
    if set(item) != {"returnCode", "stdout", "stderr"}:
        raise FalconPreviewError(f"{label} field closure differs")
    if item.get("returnCode") != 0:
        raise FalconPreviewError(f"{label} did not exit zero")
    _evidence_file(
        root,
        _object(item.get("stdout"), f"{label}.stdout"),
        f"{label}.stdout",
        allow_empty=True,
    )
    _evidence_file(
        root,
        _object(item.get("stderr"), f"{label}.stderr"),
        f"{label}.stderr",
        allow_empty=True,
    )
    return item


def _contract_sha256() -> str:
    candidate = Path(__file__)
    if not candidate.is_file() or candidate.is_symlink():
        raise FalconPreviewError("Falcon preview contract source is unavailable")
    return _hash_file(candidate.resolve(strict=True))


def _executor_sha256() -> str:
    candidate = Path(__file__).with_name("rally_falcon_preview_execute.py")
    if not candidate.is_file() or candidate.is_symlink():
        raise FalconPreviewError("Falcon preview executor source is unavailable")
    return _hash_file(candidate.resolve(strict=True))


def validate_rally_intake(intake_path: Path, evidence_root: Path) -> Mapping[str, Any]:
    root = _root(evidence_root, "evidence_root")
    exact_intake = _inside(intake_path, root, "intake")
    intake = _read_json(exact_intake, "Rally Falcon intake")
    expected = {
        "contractVersion",
        "protocolVersion",
        "consumerRepository",
        "sourceReceipt",
        "sourceReceiptSha256",
        "producerRepository",
        "producerCommit",
        "model",
        "prototypeReceipt",
        "status",
        "runtimeReady",
        "automaticImport",
        "automaticSceneMutation",
        "authority",
        "intakeSha256",
    }
    if set(intake) != expected:
        raise FalconPreviewError("Rally Falcon intake field closure differs")
    _self_hash(intake, "intakeSha256", "Rally Falcon intake")
    if (
        intake.get("contractVersion") != INTAKE_CONTRACT
        or intake.get("protocolVersion") != PROTOCOL_VERSION
        or intake.get("consumerRepository") != RALLY_REPOSITORY
        or intake.get("status") != "verified-worker-evidence"
    ):
        raise FalconPreviewError("Rally Falcon intake identity/state differs")
    if any(
        intake.get(key) is not False
        for key in ("runtimeReady", "automaticImport", "automaticSceneMutation")
    ):
        raise FalconPreviewError("Rally Falcon intake exceeded non-operative state")
    producer_commit = intake.get("producerCommit")
    source_receipt_sha = intake.get("sourceReceiptSha256")
    if not isinstance(producer_commit, str) or not SHA40.fullmatch(producer_commit):
        raise FalconPreviewError("Rally Falcon producerCommit is invalid")
    if not isinstance(source_receipt_sha, str) or not SHA64.fullmatch(source_receipt_sha):
        raise FalconPreviewError("Rally Falcon sourceReceiptSha256 is invalid")
    authority = _object(intake.get("authority"), "Rally Falcon intake authority")
    if authority.get("namedHumanVisualDecisionRequired") is not True:
        raise FalconPreviewError("Rally Falcon intake no longer requires named-human review")
    if any(authority.get(key) is not False for key in INTAKE_FALSE_AUTHORITY):
        raise FalconPreviewError("Rally Falcon intake authority expanded")
    model = _object(intake.get("model"), "Rally Falcon model")
    if model.get("path") != "model.glb":
        raise FalconPreviewError("Rally Falcon model path differs")
    _evidence_file(root, model, "Rally Falcon model")
    return intake


def compile_preview_plan(
    *,
    intake_path: Path,
    evidence_root: Path,
    rally_head: str,
    lab_head: str,
) -> dict[str, Any]:
    if not SHA40.fullmatch(rally_head):
        raise FalconPreviewError("rally_head must be an exact lowercase Git SHA")
    if not SHA40.fullmatch(lab_head):
        raise FalconPreviewError("lab_head must be an exact lowercase Git SHA")
    root = _root(evidence_root, "evidence_root")
    intake = validate_rally_intake(intake_path, root)
    exact_intake = _inside(intake_path, root, "intake")
    model = dict(_object(intake.get("model"), "Rally Falcon model"))
    body = {
        "schemaVersion": 2,
        "kind": PLAN_KIND,
        "assetId": ASSET_ID,
        "programId": PROGRAM_ID,
        "intake": {
            **_file_evidence(exact_intake, root),
            "intakeSha256": intake["intakeSha256"],
            "sourceReceiptSha256": intake["sourceReceiptSha256"],
            "producerCommit": intake["producerCommit"],
        },
        "candidate": model,
        "lab": {"repository": LAB_REPOSITORY, "head": lab_head},
        "target": {"repository": RALLY_REPOSITORY, "head": rally_head},
        "execution": {
            "executorPath": EXECUTOR_PATH,
            "nativeValidationEntrypoint": NATIVE_VALIDATION_ENTRYPOINT,
            "minimumGodotVersion": MINIMUM_GODOT_VERSION,
            "managedGodotInstallationRequired": True,
            "managedEngineReceiptRequired": True,
            "executableHashRequired": True,
            "payloadHashRequired": True,
            "boundedProcessLogsRequired": True,
            "isolatedExternalWorkspaceRequired": True,
            "createOnlyArtifactRootRequired": True,
            "networkDisabledByOuterWorkerRequired": True,
            "targetMutationAllowed": False,
            "realGodotProcessRequired": True,
            "minimumRenderedFrames": MINIMUM_RENDERED_FRAMES,
            "renderWidth": RENDER_WIDTH,
            "renderHeight": RENDER_HEIGHT,
        },
        "requiredEvidence": [
            "passed-native-validation-receipt",
            "exact-executor-source",
            "verified-managed-godot-installation",
            "exact-workspace-candidate-copy",
            "bounded-version-import-render-process-logs",
            "real-godot-process",
            "real-godot-model-import",
            "resource-load",
            "hash-bound-rendered-frames",
            "process-exit-zero",
            "lab-and-target-repositories-unchanged",
        ],
        "forbiddenEvidence": [
            "synthetic-render-placeholder",
            "fixture-only-render",
            "source-validation-only",
            "queued-job",
            "worker-heartbeat",
            "generated-plan-without-godot-process",
            "arbitrary-unmanaged-godot-binary",
        ],
        "previewReceiptKind": RECEIPT_KIND,
        "runtimeReadyAfterPass": False,
        "canonicalImportAfterPass": False,
        "authority": deepcopy(AUTHORITY),
    }
    return {**body, "planSha256": _hash_object(body)}


def validate_preview_plan(value: Mapping[str, Any], evidence_root: Path) -> bool:
    expected = {
        "schemaVersion",
        "kind",
        "assetId",
        "programId",
        "intake",
        "candidate",
        "lab",
        "target",
        "execution",
        "requiredEvidence",
        "forbiddenEvidence",
        "previewReceiptKind",
        "runtimeReadyAfterPass",
        "canonicalImportAfterPass",
        "authority",
        "planSha256",
    }
    if set(value) != expected:
        raise FalconPreviewError("Falcon preview plan field closure differs")
    _self_hash(value, "planSha256", "Falcon preview plan")
    if (
        value.get("schemaVersion") != 2
        or value.get("kind") != PLAN_KIND
        or value.get("assetId") != ASSET_ID
        or value.get("programId") != PROGRAM_ID
        or value.get("previewReceiptKind") != RECEIPT_KIND
    ):
        raise FalconPreviewError("Falcon preview plan identity differs")
    if value.get("authority") != AUTHORITY:
        raise FalconPreviewError("Falcon preview plan authority expanded")
    if value.get("runtimeReadyAfterPass") is not False:
        raise FalconPreviewError("Falcon preview plan cannot grant runtime readiness")
    if value.get("canonicalImportAfterPass") is not False:
        raise FalconPreviewError("Falcon preview plan cannot grant canonical import")
    lab = _object(value.get("lab"), "Falcon preview lab")
    target = _object(value.get("target"), "Falcon preview target")
    if (
        lab.get("repository") != LAB_REPOSITORY
        or not SHA40.fullmatch(str(lab.get("head", "")))
    ):
        raise FalconPreviewError("Falcon preview lab binding differs")
    if (
        target.get("repository") != RALLY_REPOSITORY
        or not SHA40.fullmatch(str(target.get("head", "")))
    ):
        raise FalconPreviewError("Falcon preview target binding differs")
    execution = _object(value.get("execution"), "Falcon preview execution")
    expected_execution = {
        "executorPath": EXECUTOR_PATH,
        "nativeValidationEntrypoint": NATIVE_VALIDATION_ENTRYPOINT,
        "minimumGodotVersion": MINIMUM_GODOT_VERSION,
        "managedGodotInstallationRequired": True,
        "managedEngineReceiptRequired": True,
        "executableHashRequired": True,
        "payloadHashRequired": True,
        "boundedProcessLogsRequired": True,
        "isolatedExternalWorkspaceRequired": True,
        "createOnlyArtifactRootRequired": True,
        "networkDisabledByOuterWorkerRequired": True,
        "targetMutationAllowed": False,
        "realGodotProcessRequired": True,
        "minimumRenderedFrames": MINIMUM_RENDERED_FRAMES,
        "renderWidth": RENDER_WIDTH,
        "renderHeight": RENDER_HEIGHT,
    }
    if execution != expected_execution:
        raise FalconPreviewError("Falcon preview execution policy differs")
    root = _root(evidence_root, "evidence_root")
    intake_item = _object(value.get("intake"), "Falcon preview intake evidence")
    intake_path = _evidence_file(
        root,
        {key: intake_item.get(key) for key in ("path", "sha256", "bytes")},
        "Falcon preview intake",
    )
    intake = validate_rally_intake(intake_path, root)
    for key in ("intakeSha256", "sourceReceiptSha256", "producerCommit"):
        if intake_item.get(key) != intake.get(key):
            raise FalconPreviewError(f"Falcon preview intake {key} binding differs")
    if value.get("candidate") != intake.get("model"):
        raise FalconPreviewError("Falcon preview candidate binding differs")
    return True


def _validate_engine_installation(
    value: Mapping[str, Any],
    godot: Mapping[str, Any],
) -> None:
    schema = value.get("schema_version")
    if schema not in {"1.1", "1.2"}:
        raise FalconPreviewError("managed engine receipt schema is unsupported")
    if value.get("version") != godot.get("version"):
        raise FalconPreviewError("managed engine receipt version differs")
    if value.get("flavor") != "standard":
        raise FalconPreviewError("Falcon preview requires managed standard Godot")
    if value.get("platform") not in {"windows", "linux"}:
        raise FalconPreviewError("managed engine platform is invalid")
    if value.get("architecture") not in {"x86_64", "arm64"}:
        raise FalconPreviewError("managed engine architecture is invalid")
    if value.get("self_contained") is not True:
        raise FalconPreviewError("managed Godot must be self-contained")
    executable_sha = value.get("executable_sha256")
    payload_sha = value.get("payload_sha256")
    editor_sha = value.get("editor_sha512")
    if (
        not isinstance(executable_sha, str)
        or not SHA64.fullmatch(executable_sha)
        or executable_sha != godot.get("executableSha256")
    ):
        raise FalconPreviewError("managed Godot executable hash differs")
    if (
        not isinstance(payload_sha, str)
        or not SHA64.fullmatch(payload_sha)
        or payload_sha != godot.get("payloadSha256")
    ):
        raise FalconPreviewError("managed Godot payload hash differs")
    if not isinstance(editor_sha, str) or not SHA128.fullmatch(editor_sha):
        raise FalconPreviewError("managed Godot editor release hash is invalid")
    if not isinstance(value.get("root"), str) or not value.get("root"):
        raise FalconPreviewError("managed Godot root is invalid")
    if not isinstance(value.get("executable"), str) or not value.get("executable"):
        raise FalconPreviewError("managed Godot executable path is invalid")


def validate_preview_receipt(
    value: Mapping[str, Any],
    plan: Mapping[str, Any],
    evidence_root: Path,
    artifact_root: Path,
) -> bool:
    validate_preview_plan(plan, evidence_root)
    expected = {
        "schemaVersion",
        "kind",
        "assetId",
        "programId",
        "planSha256",
        "lab",
        "target",
        "candidate",
        "nativeValidation",
        "contractSource",
        "executorSource",
        "engineInstallation",
        "workspaceCandidate",
        "previewHarness",
        "godot",
        "processEvidence",
        "import",
        "resourceLoad",
        "previewResult",
        "renderedFrames",
        "processExitCode",
        "targetUnchanged",
        "labUnchanged",
        "status",
        "creativeApproval",
        "runtimeAdmission",
        "canonicalImport",
        "forbiddenEvidenceObserved",
        "authority",
        "receiptSha256",
    }
    if set(value) != expected:
        raise FalconPreviewError("Falcon preview receipt field closure differs")
    _self_hash(value, "receiptSha256", "Falcon preview receipt")
    if (
        value.get("schemaVersion") != 2
        or value.get("kind") != RECEIPT_KIND
        or value.get("assetId") != ASSET_ID
        or value.get("programId") != PROGRAM_ID
        or value.get("planSha256") != plan.get("planSha256")
        or value.get("status") != "review-required"
    ):
        raise FalconPreviewError("Falcon preview receipt identity/state differs")
    if value.get("authority") != AUTHORITY:
        raise FalconPreviewError("Falcon preview receipt authority expanded")
    if any(
        value.get(key) is not False
        for key in ("creativeApproval", "runtimeAdmission", "canonicalImport")
    ):
        raise FalconPreviewError("Falcon preview receipt exceeded review-only authority")
    if value.get("forbiddenEvidenceObserved") != []:
        raise FalconPreviewError("Falcon preview receipt observed forbidden evidence")
    if value.get("lab") != plan.get("lab") or value.get("target") != plan.get("target"):
        raise FalconPreviewError("Falcon preview repository binding differs")
    if value.get("candidate") != plan.get("candidate"):
        raise FalconPreviewError("Falcon preview candidate binding differs")
    if value.get("targetUnchanged") is not True or value.get("labUnchanged") is not True:
        raise FalconPreviewError("Falcon preview source repositories changed")

    artifacts = _root(artifact_root, "artifact_root")
    native_item = _object(value.get("nativeValidation"), "nativeValidation")
    native_path = _evidence_file(artifacts, native_item, "nativeValidation")
    native = _read_json(native_path, "native validation receipt")
    target = _object(plan.get("target"), "Falcon preview target")
    lab = _object(plan.get("lab"), "Falcon preview lab")
    if (
        native.get("schemaVersion") != "2.0"
        or native.get("status") != "passed"
        or native.get("labRepository") != LAB_REPOSITORY
        or native.get("labSha") != lab.get("head")
        or native.get("targetSha") != target.get("head")
        or native.get("targetUnchanged") is not True
    ):
        raise FalconPreviewError(
            "native validation receipt does not prove exact unchanged target"
        )

    contract_item = _object(value.get("contractSource"), "contractSource")
    contract_copy = _evidence_file(artifacts, contract_item, "contractSource")
    if contract_item.get("sha256") != _contract_sha256():
        raise FalconPreviewError("Falcon preview contract source differs from validator checkout")
    if contract_copy.name != "rally_falcon_preview_v2.py":
        raise FalconPreviewError("Falcon preview contract evidence filename differs")

    executor_item = _object(value.get("executorSource"), "executorSource")
    executor_copy = _evidence_file(artifacts, executor_item, "executorSource")
    if executor_item.get("sha256") != _executor_sha256():
        raise FalconPreviewError("Falcon preview executor source differs from validator checkout")
    if executor_copy.name != "rally_falcon_preview_execute.py":
        raise FalconPreviewError("Falcon preview executor evidence filename differs")

    godot = _object(value.get("godot"), "godot")
    if set(godot) != {
        "version",
        "executableSha256",
        "payloadSha256",
        "managedInstallation",
        "realProcess",
    }:
        raise FalconPreviewError("Godot identity field closure differs")
    executable_sha = godot.get("executableSha256")
    payload_sha = godot.get("payloadSha256")
    if godot.get("managedInstallation") is not True or godot.get("realProcess") is not True:
        raise FalconPreviewError("Falcon preview requires a verified managed Godot process")
    if not isinstance(executable_sha, str) or not SHA64.fullmatch(executable_sha):
        raise FalconPreviewError("Godot executable hash is invalid")
    if not isinstance(payload_sha, str) or not SHA64.fullmatch(payload_sha):
        raise FalconPreviewError("Godot payload hash is invalid")
    if _version(godot.get("version"), "godot.version") < _version(
        MINIMUM_GODOT_VERSION, "minimum Godot version"
    ):
        raise FalconPreviewError("Godot version is below the Falcon preview minimum")

    engine_item = _object(value.get("engineInstallation"), "engineInstallation")
    engine_path = _evidence_file(artifacts, engine_item, "engineInstallation")
    engine = _read_json(engine_path, "managed engine installation receipt")
    _validate_engine_installation(engine, godot)

    workspace_candidate = _object(value.get("workspaceCandidate"), "workspaceCandidate")
    _evidence_file(artifacts, workspace_candidate, "workspaceCandidate")
    candidate = _object(plan.get("candidate"), "Falcon preview candidate")
    if (
        workspace_candidate.get("sha256") != candidate.get("sha256")
        or workspace_candidate.get("bytes") != candidate.get("bytes")
    ):
        raise FalconPreviewError("isolated workspace candidate differs from preview plan")

    harness = _object(value.get("previewHarness"), "previewHarness")
    if set(harness) != {"project", "script"}:
        raise FalconPreviewError("preview harness field closure differs")
    project_file = _evidence_file(
        artifacts,
        _object(harness.get("project"), "previewHarness.project"),
        "previewHarness.project",
    )
    script_file = _evidence_file(
        artifacts,
        _object(harness.get("script"), "previewHarness.script"),
        "previewHarness.script",
    )
    if project_file.name != "project.godot" or script_file.name != "preview.gd":
        raise FalconPreviewError("preview harness filenames differ")

    processes = _object(value.get("processEvidence"), "processEvidence")
    if set(processes) != {"version", "import", "render"}:
        raise FalconPreviewError("processEvidence field closure differs")
    version_process = _validate_process_evidence(
        artifacts, processes.get("version"), "processEvidence.version"
    )
    _validate_process_evidence(
        artifacts, processes.get("import"), "processEvidence.import"
    )
    _validate_process_evidence(
        artifacts, processes.get("render"), "processEvidence.render"
    )
    version_stdout = _evidence_file(
        artifacts,
        _object(version_process.get("stdout"), "processEvidence.version.stdout"),
        "processEvidence.version.stdout",
        allow_empty=True,
    )
    version_stderr = _evidence_file(
        artifacts,
        _object(version_process.get("stderr"), "processEvidence.version.stderr"),
        "processEvidence.version.stderr",
        allow_empty=True,
    )
    version_text = (
        version_stdout.read_text(encoding="utf-8", errors="replace")
        + "\n"
        + version_stderr.read_text(encoding="utf-8", errors="replace")
    )
    observed = VERSION_SEARCH.search(version_text)
    if observed is None or observed.group("version") != godot.get("version"):
        raise FalconPreviewError("Godot version process evidence differs from receipt")

    imported = _object(value.get("import"), "import")
    loaded = _object(value.get("resourceLoad"), "resourceLoad")
    if imported != {"attempted": True, "passed": True}:
        raise FalconPreviewError("real Godot model import did not pass")
    if loaded != {"passed": True}:
        raise FalconPreviewError("Godot resource load did not pass")
    if value.get("processExitCode") != 0:
        raise FalconPreviewError("Godot preview process did not exit zero")

    result_item = _object(value.get("previewResult"), "previewResult")
    result_path = _evidence_file(artifacts, result_item, "previewResult")
    result = _read_json(result_path, "Godot preview result")
    expected_frame_names = [
        f"frame-{index:02d}.png" for index in range(MINIMUM_RENDERED_FRAMES)
    ]
    if (
        result.get("schemaVersion") != 1
        or result.get("status") != "passed"
        or result.get("resourceLoaded") is not True
        or result.get("frameCount") != MINIMUM_RENDERED_FRAMES
        or result.get("frames") != expected_frame_names
    ):
        raise FalconPreviewError("Godot preview result does not prove the expected real render")

    frames = value.get("renderedFrames")
    if not isinstance(frames, list) or len(frames) != MINIMUM_RENDERED_FRAMES:
        raise FalconPreviewError("Falcon preview requires exactly four rendered frames")
    paths: set[str] = set()
    observed_names: list[str] = []
    for index, raw in enumerate(frames):
        item = _object(raw, f"renderedFrames[{index}]")
        frame = _evidence_file(artifacts, item, f"renderedFrames[{index}]")
        if item["path"] in paths:
            raise FalconPreviewError("Falcon preview frame paths must be unique")
        paths.add(item["path"])
        observed_names.append(frame.name)
        if _png_dimensions(frame) != (RENDER_WIDTH, RENDER_HEIGHT):
            raise FalconPreviewError("Falcon preview frames must be 1024x1024 PNGs")
    if observed_names != expected_frame_names:
        raise FalconPreviewError("Falcon preview frame names/order differ")
    return True


def capabilities() -> dict[str, Any]:
    return {
        "schemaVersion": 2,
        "kind": CAPABILITIES_KIND,
        "assetId": ASSET_ID,
        "programId": PROGRAM_ID,
        "compilesHashBoundPlan": True,
        "validatesRallyIntakeBytes": True,
        "validatesManagedGodotEvidence": True,
        "validatesBoundedProcessEvidence": True,
        "validatesRealGodotPreviewReceipt": True,
        "executesGodot": False,
        "executorPath": EXECUTOR_PATH,
        "minimumGodotVersion": MINIMUM_GODOT_VERSION,
        "minimumRenderedFrames": MINIMUM_RENDERED_FRAMES,
        "authority": deepcopy(AUTHORITY),
    }


def _write_create_only(path: Path, value: Mapping[str, Any]) -> Path:
    destination = Path(os.path.abspath(path))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(
            value,
            handle,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        handle.write("\n")
    return destination


def _load(path: Path, label: str) -> Mapping[str, Any]:
    return _read_json(path, label)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="godot-lab-rally-falcon-preview-v2")
    commands = parser.add_subparsers(dest="command", required=True)
    compile_cmd = commands.add_parser("compile")
    compile_cmd.add_argument("--intake", type=Path, required=True)
    compile_cmd.add_argument("--evidence-root", type=Path, required=True)
    compile_cmd.add_argument("--rally-head", required=True)
    compile_cmd.add_argument("--lab-head", required=True)
    compile_cmd.add_argument("--output", type=Path, required=True)
    validate_plan_cmd = commands.add_parser("validate-plan")
    validate_plan_cmd.add_argument("plan", type=Path)
    validate_plan_cmd.add_argument("--evidence-root", type=Path, required=True)
    validate_receipt_cmd = commands.add_parser("validate-receipt")
    validate_receipt_cmd.add_argument("receipt", type=Path)
    validate_receipt_cmd.add_argument("--plan", type=Path, required=True)
    validate_receipt_cmd.add_argument("--evidence-root", type=Path, required=True)
    validate_receipt_cmd.add_argument("--artifact-root", type=Path, required=True)
    commands.add_parser("capabilities")
    args = parser.parse_args(argv)
    try:
        if args.command == "compile":
            result = compile_preview_plan(
                intake_path=args.intake,
                evidence_root=args.evidence_root,
                rally_head=args.rally_head,
                lab_head=args.lab_head,
            )
            _write_create_only(args.output, result)
            summary = {
                "ok": True,
                "planSha256": result["planSha256"],
                "output": str(args.output),
            }
        elif args.command == "validate-plan":
            plan = _load(args.plan, "Falcon preview plan")
            summary = {
                "valid": validate_preview_plan(plan, args.evidence_root),
                "planSha256": plan.get("planSha256"),
            }
        elif args.command == "validate-receipt":
            plan = _load(args.plan, "Falcon preview plan")
            receipt = _load(args.receipt, "Falcon preview receipt")
            summary = {
                "valid": validate_preview_receipt(
                    receipt,
                    plan,
                    args.evidence_root,
                    args.artifact_root,
                ),
                "receiptSha256": receipt.get("receiptSha256"),
                "runtimeAdmission": False,
                "canonicalImport": False,
            }
        else:
            summary = capabilities()
        print(json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False))
        return 0
    except (FalconPreviewError, OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
