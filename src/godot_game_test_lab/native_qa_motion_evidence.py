from __future__ import annotations

import json
import os
import re
from argparse import Namespace
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from math import isfinite
from pathlib import Path
from typing import Any
from uuid import uuid4

from .native_qa_common import (
    NativeQaError,
    _canonical_json,
    _directory_usage,
    _sha256_file,
)
from .native_qa_evidence import _artifact_inventory, _validate_png

_ADAPTER_ID = "godot-game-test-lab.video-evidence"
_GIT_SHA_RE = re.compile(r"^[a-f0-9]{40}$")
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_OBSERVATION_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,127}$")
_SOURCE_PATHS = (
    "pyproject.toml",
    "scripts/godot_input_journey.gd",
    "src/godot_game_test_lab/native_qa.py",
    "src/godot_game_test_lab/native_qa_evidence.py",
    "src/godot_game_test_lab/native_qa_motion_evidence.py",
    "src/godot_game_test_lab/native_qa_profile.py",
    "src/godot_game_test_lab/native_qa_runner.py",
    "src/godot_game_test_lab/native_qa_visual_review.py",
    "src/godot_game_test_lab/ui_layout_analysis.py",
)


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise NativeQaError(f"Could not canonicalize visual motion evidence: {error}") from error


def canonical_sha256(value: object) -> str:
    return sha256(_canonical_bytes(value)).hexdigest()


def _regular_confined_file(root: Path, relative_path: str, label: str) -> Path:
    requested = root / Path(relative_path)
    if requested.is_symlink():
        raise NativeQaError(f"{label} may not be a symbolic link: {relative_path}")
    try:
        resolved = requested.resolve(strict=True)
    except OSError as error:
        raise NativeQaError(f"{label} is missing: {relative_path}") from error
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise NativeQaError(f"{label} is outside the admitted root: {relative_path}")
    return resolved


def visual_motion_source_identity(lab_root: Path, lab_sha: str) -> str:
    root = lab_root.expanduser().resolve(strict=True)
    if not root.is_dir() or root.is_symlink():
        raise NativeQaError("Godot lab source root must be a non-symlink directory")
    if _GIT_SHA_RE.fullmatch(lab_sha) is None:
        raise NativeQaError("Godot lab source identity requires a full lowercase Git SHA")
    digest = sha256()
    digest.update(b"labSha\0")
    digest.update(lab_sha.encode("ascii"))
    digest.update(b"\0")
    for relative_path in _SOURCE_PATHS:
        path = _regular_confined_file(root, relative_path, "Godot visual source file")
        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def _safe_journey_root(artifacts: Path, journey_id: str) -> Path:
    if _ID_RE.fullmatch(journey_id) is None:
        raise NativeQaError(f"Journey summary contains an unsafe id: {journey_id!r}")
    requested = artifacts / "journeys" / journey_id
    if requested.is_symlink():
        raise NativeQaError(f"Journey motion evidence root may not be a symbolic link: {requested}")
    resolved = requested.resolve(strict=True)
    if not resolved.is_dir() or not resolved.is_relative_to(artifacts):
        raise NativeQaError(f"Journey motion evidence root is invalid: {requested}")
    return resolved


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _string_list(value: object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _timestamp(value: object, fallback: datetime) -> datetime:
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.astimezone(UTC)
        except ValueError:
            pass
    return fallback


def _duration_seconds(diagnostics: Mapping[str, Any]) -> int | float:
    probe = diagnostics.get("ffprobe")
    if not isinstance(probe, Mapping):
        return 0
    candidates: list[float] = []
    format_data = probe.get("format")
    if isinstance(format_data, Mapping):
        try:
            value = float(format_data.get("duration"))
            if isfinite(value) and value >= 0:
                candidates.append(value)
        except (TypeError, ValueError):
            pass
    streams = probe.get("streams")
    if isinstance(streams, Sequence) and not isinstance(streams, (str, bytes)):
        for stream in streams:
            if not isinstance(stream, Mapping):
                continue
            try:
                value = float(stream.get("duration"))
                if isfinite(value) and value >= 0:
                    candidates.append(value)
            except (TypeError, ValueError):
                pass
    if not candidates:
        return 0
    rounded = round(max(candidates), 3)
    return int(rounded) if rounded.is_integer() else rounded


def _frame_records(artifacts: Path, journey_root: Path) -> list[dict[str, Any]]:
    screenshots = journey_root / "screenshots"
    if screenshots.is_symlink() or not screenshots.is_dir():
        return []
    records: list[dict[str, Any]] = []
    for index, path in enumerate(sorted(screenshots.glob("frame-*.png"))):
        if not _validate_png(path):
            continue
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(artifacts):
            raise NativeQaError("Godot motion screenshot escapes the artifact root")
        records.append(
            {
                "index": index,
                "path": resolved.relative_to(artifacts).as_posix(),
                "bytes": resolved.stat().st_size,
                "sha256": _sha256_file(resolved),
                "mediaType": "image/png",
            }
        )
    return records


def _write_create_once(path: Path, value: object) -> None:
    if path.exists() or path.is_symlink():
        raise NativeQaError(f"Refusing to overwrite retained motion evidence: {path}")
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(_canonical_json(value), encoding="utf-8")
        try:
            os.link(temporary, path, follow_symlinks=False)
        except FileExistsError as error:
            raise NativeQaError(
                f"Refusing to overwrite retained motion evidence: {path}"
            ) from error
        except OSError as error:
            raise NativeQaError(
                f"Could not atomically retain motion evidence: {path}"
            ) from error
    finally:
        temporary.unlink(missing_ok=True)


def _motion_observation_id(
    *,
    run_id: str,
    journey_id: str,
    scene: str,
    movie_sha256: str,
    source_identity: str,
) -> str:
    if not run_id or len(run_id) > 256 or "\x00" in run_id:
        raise NativeQaError("Native QA summary runId is missing or outside policy")
    token = re.sub(r"[^a-z0-9._-]+", "-", journey_id.casefold()).strip("-._")
    token = token[:40] or "journey"
    suffix = canonical_sha256(
        {
            "journeyId": journey_id,
            "movieSha256": movie_sha256,
            "runId": run_id,
            "scene": scene,
            "sourceIdentity": source_identity,
        }
    )[:24]
    value = f"godot:{token}:{suffix}"
    if _OBSERVATION_ID_RE.fullmatch(value) is None:
        raise NativeQaError("Could not derive a safe Godot motion observation id")
    return value


def _journey_analysis(
    *,
    artifacts: Path,
    journey: Mapping[str, Any],
    journey_root: Path,
    source_identity: str,
    captured_at: datetime,
    run_id: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    movie = journey_root / "gameplay.avi"
    if movie.is_symlink() or not movie.is_file() or movie.stat().st_size <= 0:
        return (None, None)
    resolved_movie = movie.resolve(strict=True)
    if not resolved_movie.is_relative_to(artifacts):
        raise NativeQaError("Godot motion movie escapes the artifact root")
    visual = _mapping(journey.get("visual"))
    diagnostics = _mapping(visual.get("diagnostics"))
    frames = _frame_records(artifacts, journey_root)
    unique_frame_digests = sorted({str(frame["sha256"]) for frame in frames})
    journey_id = str(journey.get("id", ""))
    scene = str(journey.get("scene", "configured-main-scene"))
    movie_sha256 = _sha256_file(resolved_movie)
    observation_id = _motion_observation_id(
        run_id=run_id,
        journey_id=journey_id,
        scene=scene,
        movie_sha256=movie_sha256,
        source_identity=source_identity,
    )
    temporal_verdict = "pass" if frames and visual.get("status") == "passed" else "needs-review"
    analysis = {
        "schema": "evavo.godot-motion-analysis.v1",
        "observationId": observation_id,
        "capturedAt": captured_at.isoformat(),
        "sourceIdentity": source_identity,
        "runId": run_id,
        "journeyId": journey_id,
        "scene": scene,
        "movie": {
            "path": resolved_movie.relative_to(artifacts).as_posix(),
            "mediaType": "video/x-msvideo",
            "bytes": resolved_movie.stat().st_size,
            "sha256": movie_sha256,
        },
        "durationSeconds": _duration_seconds(diagnostics),
        "sampledFrames": frames,
        "sampledFrameCount": len(frames),
        "uniqueFrameDigestCount": len(unique_frame_digests),
        "observedChange": len(unique_frame_digests) > 1,
        "blackSegments": diagnostics.get("blackSegments", []),
        "freezeSegments": diagnostics.get("freezeSegments", []),
        "temporalVerdict": temporal_verdict,
        "truthBoundary": (
            "This deterministic analysis proves the retained Godot movie, sampled PNG frames, "
            "frame diversity and FFmpeg diagnostics. It does not certify game feel, input latency, "
            "animation quality or human visual approval."
        ),
    }
    analysis_path = journey_root / "motion-analysis.json"
    _write_create_once(analysis_path, analysis)

    sequence = None
    if frames:
        sequence = {
            "schema": "evavo.visual-frame-sequence.v1",
            "observationId": observation_id,
            "capturedAt": captured_at.isoformat(),
            "sourceIdentity": source_identity,
            "runId": run_id,
            "journeyId": journey_id,
            "frameCount": len(frames),
            "frames": frames,
        }
        sequence_path = journey_root / "motion-frame-sequence.json"
        _write_create_once(sequence_path, sequence)
    return (analysis, sequence)


def _adapter_receipt(
    *,
    summary: Mapping[str, Any],
    source_identity: str,
    issued_at: datetime,
    analyses: Sequence[Mapping[str, Any]],
    sequences: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    capabilities = ["layout-analysis", "native-control-tree"]
    if analyses:
        capabilities.extend(["screen-recording", "temporal-analysis"])
    if sequences:
        capabilities.append("screenshot-sequence")
    ready = bool(summary.get("nativeDesktopEvidence") is True and analyses)
    partial = {
        "schema": "evavo.visual-qa-adapter-receipt.v1",
        "adapterId": _ADAPTER_ID,
        "sourceIdentity": source_identity,
        "issuedAt": issued_at.isoformat(),
        "expiresAt": (issued_at + timedelta(minutes=30)).isoformat(),
        "status": "locally-verified" if ready else "source-present",
        "ready": ready,
        "capabilities": sorted(set(capabilities)),
        "nativeDesktopEvidence": summary.get("nativeDesktopEvidence") is True,
        "runId": summary.get("runId"),
        "labSha": summary.get("labSha"),
        "journeyMotionAnalysisCount": len(analyses),
        "journeyFrameSequenceCount": len(sequences),
        "truthBoundary": (
            "This receipt admits only the exact Godot visual source and retained native journey "
            "evidence in this run. It is not worker promotion and does not prove any separate "
            "application campaign state."
        ),
    }
    return {**partial, "receiptDigest": canonical_sha256(partial)}


def augment_native_qa_motion_evidence(
    args: Namespace, summary: dict[str, Any]
) -> dict[str, Any]:
    artifacts = Path(args.artifacts).expanduser().resolve(strict=True)
    maximum_artifact_bytes = int(args.max_artifact_bytes)
    lab_root = Path(args.lab_root).expanduser().resolve(strict=True)
    source_identity = visual_motion_source_identity(lab_root, str(args.expected_lab_sha))
    issued_at = datetime.now(UTC)
    captured_at = _timestamp(summary.get("generatedAt"), issued_at)
    run_id = summary.get("runId")
    if not isinstance(run_id, str) or not run_id or len(run_id) > 256 or "\x00" in run_id:
        raise NativeQaError("Native QA summary runId is missing or outside policy")
    journeys_raw = summary.get("journeys", [])
    if not isinstance(journeys_raw, list):
        raise NativeQaError("Native QA summary journeys must be an array")

    analyses: list[dict[str, Any]] = []
    sequences: list[dict[str, Any]] = []
    staged: list[tuple[dict[str, Any], Path, dict[str, Any], dict[str, Any] | None]] = []
    for raw in journeys_raw:
        if not isinstance(raw, dict):
            raise NativeQaError("Native QA summary contains a non-object journey")
        journey_id = raw.get("id")
        if not isinstance(journey_id, str):
            raise NativeQaError("Native QA journey is missing its id")
        journey_root = _safe_journey_root(artifacts, journey_id)
        analysis, sequence = _journey_analysis(
            artifacts=artifacts,
            journey=raw,
            journey_root=journey_root,
            source_identity=source_identity,
            captured_at=captured_at,
            run_id=run_id,
        )
        if analysis is None:
            continue
        analyses.append(analysis)
        if sequence is not None:
            sequences.append(sequence)
        staged.append((raw, journey_root, analysis, sequence))

    receipt = _adapter_receipt(
        summary=summary,
        source_identity=source_identity,
        issued_at=issued_at,
        analyses=analyses,
        sequences=sequences,
    )
    receipt_path = artifacts / "godot-visual-adapter-receipt.json"
    _write_create_once(receipt_path, receipt)
    receipt_reference_sha256 = canonical_sha256(receipt)

    for journey, journey_root, analysis, sequence in staged:
        movie = analysis["movie"]
        assert isinstance(movie, Mapping)
        analysis_path = journey_root / "motion-analysis.json"
        partial = {
            "schema": "evavo.visual-motion-evidence.v1",
            "captureAdapterId": _ADAPTER_ID,
            "analysisAdapterId": _ADAPTER_ID,
            "captureReceiptSha256": receipt_reference_sha256,
            "analysisReceiptSha256": receipt_reference_sha256,
            "capturedAt": analysis["capturedAt"],
            "mediaType": movie["mediaType"],
            "videoSha256": movie["sha256"],
            "videoBytes": movie["bytes"],
            "temporalAnalysisSha256": _sha256_file(analysis_path),
            "durationSeconds": analysis["durationSeconds"],
            "sampledFrameCount": analysis["sampledFrameCount"],
            "observationIds": [analysis["observationId"]],
            "temporalVerdict": analysis["temporalVerdict"],
            "observedChange": analysis["observedChange"],
        }
        motion_evidence = {
            **partial,
            "motionEvidenceDigest": canonical_sha256(partial),
        }
        destination = journey_root / "motion-evidence.json"
        _write_create_once(destination, motion_evidence)
        evidence = _string_list(journey.get("evidence"))
        evidence.extend(
            [
                analysis_path.relative_to(artifacts).as_posix(),
                destination.relative_to(artifacts).as_posix(),
            ]
        )
        if sequence is not None:
            evidence.append(
                (journey_root / "motion-frame-sequence.json")
                .relative_to(artifacts)
                .as_posix()
            )
        journey["evidence"] = sorted(set(evidence))
        journey["motionObservationId"] = analysis["observationId"]
        journey["motionEvidence"] = motion_evidence
        journey["motionAnalysis"] = analysis

    summary["visualAdapterReceipt"] = receipt
    summary["visualAdapterReceiptPath"] = receipt_path.relative_to(artifacts).as_posix()
    summary["visualAdapterReceiptSha256"] = receipt_reference_sha256
    boundary = str(summary.get("truthBoundary", "")).strip()
    motion_boundary = (
        "Digest-bound motion evidence proves only the retained Godot movie and deterministic "
        "sample analysis; publication still requires a matching task observation and review policy."
    )
    if motion_boundary not in boundary:
        summary["truthBoundary"] = f"{boundary} {motion_boundary}".strip()

    used_bytes, used_files, complete = _directory_usage(artifacts)
    if not complete or used_bytes > maximum_artifact_bytes:
        raise NativeQaError("Motion evidence exceeded the native QA artifact budget")
    execution_budget = summary.get("executionBudget")
    if isinstance(execution_budget, dict):
        execution_budget["retainedArtifactBytes"] = used_bytes
        execution_budget["retainedArtifactFiles"] = used_files
        execution_budget["measurementComplete"] = complete
    summary["artifacts"] = _artifact_inventory(
        artifacts,
        maximum_total_bytes=maximum_artifact_bytes,
    )
    (artifacts / "native-agent-summary.json").write_text(
        _canonical_json(summary), encoding="utf-8"
    )
    return summary
