from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .movie_evidence import confined_regular_file
from .native_qa_common import NativeQaError

_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_PNG_SIGNATURE = bytes((137, 80, 78, 71, 13, 10, 26, 10))
_SEQUENCE_SCHEMA = "evavo.godot-movie-frame-sequence.v1"
_ADAPTER_SCHEMA = "evavo.visual-qa-adapter-receipt.v1"
_ADAPTER_ID = "godot-game-test-lab.movie-temporal"
_MAX_SEQUENCE_BYTES = 8 * 1024 * 1024
_MAX_FRAME_BYTES = 25 * 1024 * 1024
_MAX_FRAMES = 10_000
_MAX_DURATION_MS = 24 * 60 * 60 * 1000
_MAX_FINDINGS = 1024
_RECEIPT_LIFETIME = timedelta(minutes=30)
_MAX_FUTURE_SKEW = timedelta(minutes=5)
_REQUIRED_CAPABILITIES = {
    "temporal-analysis",
    "sampled-frame-sequence",
    "exact-frame-bytes",
}
_BASE_RECEIPT_KEYS = {
    "schema",
    "adapterId",
    "sourceIdentity",
    "issuedAt",
    "expiresAt",
    "status",
    "ready",
    "workerAdmitted",
    "capabilities",
    "inputMovieSha256",
    "sequenceManifestRelativePath",
    "sequenceManifestSha256",
    "sequenceDigest",
    "extractionSourceIdentity",
    "extractionCommandSha256",
    "sampledFrameCount",
    "observedChange",
    "temporalVerdict",
    "temporalAnalysisSha256",
    "evidenceSha256",
    "findings",
    "arbitraryShellAccepted",
    "sourceMutationPerformed",
    "truthBoundary",
    "receiptDigest",
}
_REPORT_BINDING_KEYS = {
    "temporalReportRelativePath",
    "temporalReportFileSha256",
}
_FINDING_KEYS = {"code", "severity", "detail", "frameIds"}


@dataclass(frozen=True)
class VerifiedMovieFrame:
    frame_id: str
    timestamp_ms: int
    relative_path: str
    sha256: str
    size_bytes: int
    absolute_path: Path


@dataclass(frozen=True)
class VerifiedMovieFrameSequence:
    manifest_path: Path
    manifest_relative_path: str
    manifest_sha256: str
    sequence_digest: str
    movie_sha256: str
    movie_bytes: int
    extraction_source_identity: str
    extraction_command_sha256: str
    created_at: str
    duration_ms: int
    frames_per_second: float
    frames: tuple[VerifiedMovieFrame, ...]


@dataclass(frozen=True)
class TemporalFinding:
    code: str
    severity: str
    detail: str
    frame_ids: tuple[str, ...]


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _sha256_file(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def _object(value: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise NativeQaError(f"{label} must be an object")
    return value


def _allowed_keys(value: Mapping[str, Any], allowed: set[str], *, label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise NativeQaError(f"{label} contains unsupported fields: {', '.join(unknown)}")


def _exact_keys(value: Mapping[str, Any], expected: set[str], *, label: str) -> None:
    actual = set(value)
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    if missing or unknown:
        detail = []
        if missing:
            detail.append(f"missing: {', '.join(missing)}")
        if unknown:
            detail.append(f"unsupported: {', '.join(unknown)}")
        raise NativeQaError(f"{label} fields are invalid ({'; '.join(detail)})")


def _token(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or _TOKEN.fullmatch(value) is None:
        raise NativeQaError(f"{label} must be a bounded stable token")
    return value


def _sha256(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise NativeQaError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _integer(
    value: Any,
    *,
    label: str,
    minimum: int,
    maximum: int,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise NativeQaError(f"{label} must be an integer between {minimum} and {maximum}")
    return value


def _number(
    value: Any,
    *,
    label: str,
    minimum: float,
    maximum: float,
) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise NativeQaError(f"{label} must be a finite number")
    resolved = float(value)
    if not minimum <= resolved <= maximum or resolved in (float("inf"), float("-inf")):
        raise NativeQaError(f"{label} must be between {minimum} and {maximum}")
    return resolved


def _boolean(value: Any, *, label: str) -> bool:
    if not isinstance(value, bool):
        raise NativeQaError(f"{label} must be boolean")
    return value


def _timestamp(value: Any, *, label: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise NativeQaError(f"{label} must be an ISO-compatible timestamp")
    try:
        result = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as error:
        raise NativeQaError(f"{label} must be an ISO-compatible timestamp") from error
    if result.tzinfo is None:
        raise NativeQaError(f"{label} must include a timezone")
    return result.astimezone(UTC)


def _safe_relative_path(value: Any, *, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 1024
        or "\\" in value
        or value.startswith("/")
        or re.match(r"^[A-Za-z]:", value)
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        raise NativeQaError(f"{label} must be a safe forward-slash relative path")
    return value


def _read_json_object(path: Path, *, maximum_bytes: int, label: str) -> tuple[dict[str, Any], bytes]:
    if not path.is_file():
        raise NativeQaError(f"{label} is not a regular file")
    size = path.stat().st_size
    if not 1 <= size <= maximum_bytes:
        raise NativeQaError(f"{label} size is outside policy")
    raw = path.read_bytes()
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise NativeQaError(f"{label} is not valid UTF-8 JSON") from error
    return _object(value, label=label), raw


def _verify_png(path: Path, *, expected_bytes: int, expected_sha256: str, label: str) -> None:
    if path.stat().st_size != expected_bytes:
        raise NativeQaError(f"{label} byte count does not match the sequence manifest")
    with path.open("rb") as stream:
        signature = stream.read(len(_PNG_SIGNATURE))
    if signature != _PNG_SIGNATURE:
        raise NativeQaError(f"{label} is not a PNG file")
    if _sha256_file(path) != expected_sha256:
        raise NativeQaError(f"{label} digest does not match the sequence manifest")


def _validated_findings(value: Any, *, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > _MAX_FINDINGS:
        raise NativeQaError(f"{label} must be an array of at most {_MAX_FINDINGS} findings")
    result: list[dict[str, Any]] = []
    for index, raw in enumerate(value):
        finding = _object(raw, label=f"{label}[{index}]")
        _exact_keys(finding, _FINDING_KEYS, label=f"{label}[{index}]")
        code = _token(finding.get("code"), label=f"{label}[{index}].code")
        severity = finding.get("severity")
        if severity not in {"warning", "error"}:
            raise NativeQaError(f"{label}[{index}].severity is unsupported")
        detail = finding.get("detail")
        if (
            not isinstance(detail, str)
            or not detail.strip()
            or len(detail) > 4096
            or "\0" in detail
            or "\r" in detail
            or "\n" in detail
        ):
            raise NativeQaError(f"{label}[{index}].detail must be bounded single-line text")
        raw_frame_ids = finding.get("frameIds")
        if (
            not isinstance(raw_frame_ids, list)
            or not 1 <= len(raw_frame_ids) <= _MAX_FRAMES
        ):
            raise NativeQaError(f"{label}[{index}].frameIds is outside policy")
        frame_ids = [
            _token(item, label=f"{label}[{index}].frameIds[{item_index}]")
            for item_index, item in enumerate(raw_frame_ids)
        ]
        if len(frame_ids) != len(set(frame_ids)):
            raise NativeQaError(f"{label}[{index}].frameIds contains duplicates")
        result.append(
            {
                "code": code,
                "severity": severity,
                "detail": detail.strip(),
                "frameIds": frame_ids,
            }
        )
    return result


def _verdict_for_findings(findings: Sequence[Mapping[str, Any]]) -> str:
    if any(finding.get("severity") == "error" for finding in findings):
        return "fail"
    return "needs-review" if findings else "pass"


def load_verified_movie_frame_sequence(
    artifact_root: Path,
    manifest: Path,
    *,
    expected_movie_sha256: str | None = None,
    expected_extraction_source_identity: str | None = None,
    maximum_frames: int = _MAX_FRAMES,
) -> VerifiedMovieFrameSequence:
    maximum = _integer(
        maximum_frames,
        label="maximum_frames",
        minimum=1,
        maximum=_MAX_FRAMES,
    )
    manifest_path, relative_path, _ = confined_regular_file(
        artifact_root,
        manifest,
        label="Godot movie frame sequence manifest",
        maximum_bytes=_MAX_SEQUENCE_BYTES,
    )
    value, raw = _read_json_object(
        manifest_path,
        maximum_bytes=_MAX_SEQUENCE_BYTES,
        label="Godot movie frame sequence manifest",
    )
    _allowed_keys(
        value,
        {
            "schema",
            "movieSha256",
            "movieBytes",
            "extractionSourceIdentity",
            "extractionCommandSha256",
            "createdAt",
            "durationMs",
            "framesPerSecond",
            "frames",
            "sequenceDigest",
        },
        label="Godot movie frame sequence manifest",
    )
    if value.get("schema") != _SEQUENCE_SCHEMA:
        raise NativeQaError("Godot movie frame sequence schema is unsupported")
    sequence_digest = _sha256(value.get("sequenceDigest"), label="sequenceDigest")
    partial = dict(value)
    partial.pop("sequenceDigest", None)
    if _digest(partial) != sequence_digest:
        raise NativeQaError("Godot movie frame sequence digest does not match its content")
    movie_sha256 = _sha256(value.get("movieSha256"), label="movieSha256")
    if expected_movie_sha256 is not None and movie_sha256 != _sha256(
        expected_movie_sha256,
        label="expected_movie_sha256",
    ):
        raise NativeQaError("Godot movie frame sequence is bound to a different movie")
    movie_bytes = _integer(
        value.get("movieBytes"),
        label="movieBytes",
        minimum=64,
        maximum=64 * 1024 * 1024 * 1024,
    )
    extraction_source_identity = _sha256(
        value.get("extractionSourceIdentity"),
        label="extractionSourceIdentity",
    )
    if (
        expected_extraction_source_identity is not None
        and extraction_source_identity != _sha256(
            expected_extraction_source_identity,
            label="expected_extraction_source_identity",
        )
    ):
        raise NativeQaError("Godot frame extraction source identity does not match")
    extraction_command_sha256 = _sha256(
        value.get("extractionCommandSha256"),
        label="extractionCommandSha256",
    )
    created_at = _timestamp(value.get("createdAt"), label="createdAt").isoformat()
    duration_ms = _integer(
        value.get("durationMs"),
        label="durationMs",
        minimum=0,
        maximum=_MAX_DURATION_MS,
    )
    frames_per_second = _number(
        value.get("framesPerSecond"),
        label="framesPerSecond",
        minimum=0.1,
        maximum=240.0,
    )
    raw_frames = value.get("frames")
    if not isinstance(raw_frames, list) or not 1 <= len(raw_frames) <= maximum:
        raise NativeQaError(f"frames must contain between 1 and {maximum} records")

    frame_ids: set[str] = set()
    timestamps: set[int] = set()
    verified: list[VerifiedMovieFrame] = []
    previous_timestamp = -1
    for index, raw_frame in enumerate(raw_frames):
        frame = _object(raw_frame, label=f"frames[{index}]")
        _allowed_keys(
            frame,
            {"id", "timestampMs", "relativePath", "sha256", "bytes"},
            label=f"frames[{index}]",
        )
        frame_id = _token(frame.get("id"), label=f"frames[{index}].id")
        if frame_id in frame_ids:
            raise NativeQaError(f"frame id is duplicated: {frame_id}")
        frame_ids.add(frame_id)
        timestamp_ms = _integer(
            frame.get("timestampMs"),
            label=f"frames[{index}].timestampMs",
            minimum=0,
            maximum=duration_ms,
        )
        if timestamp_ms in timestamps:
            raise NativeQaError(f"frame timestamp is duplicated: {timestamp_ms}")
        timestamps.add(timestamp_ms)
        if timestamp_ms <= previous_timestamp:
            raise NativeQaError("Godot movie frames must be strictly chronological")
        previous_timestamp = timestamp_ms
        frame_relative_path = _safe_relative_path(
            frame.get("relativePath"),
            label=f"frames[{index}].relativePath",
        )
        frame_sha256 = _sha256(
            frame.get("sha256"),
            label=f"frames[{index}].sha256",
        )
        frame_bytes = _integer(
            frame.get("bytes"),
            label=f"frames[{index}].bytes",
            minimum=len(_PNG_SIGNATURE),
            maximum=_MAX_FRAME_BYTES,
        )
        absolute, actual_relative, _ = confined_regular_file(
            artifact_root,
            Path(frame_relative_path),
            label=f"Godot sampled frame {frame_id}",
            maximum_bytes=_MAX_FRAME_BYTES,
        )
        if actual_relative != frame_relative_path:
            raise NativeQaError(f"sampled frame path is not canonical: {frame_id}")
        _verify_png(
            absolute,
            expected_bytes=frame_bytes,
            expected_sha256=frame_sha256,
            label=f"Godot sampled frame {frame_id}",
        )
        verified.append(
            VerifiedMovieFrame(
                frame_id=frame_id,
                timestamp_ms=timestamp_ms,
                relative_path=actual_relative,
                sha256=frame_sha256,
                size_bytes=frame_bytes,
                absolute_path=absolute,
            )
        )

    return VerifiedMovieFrameSequence(
        manifest_path=manifest_path,
        manifest_relative_path=relative_path,
        manifest_sha256=hashlib.sha256(raw).hexdigest(),
        sequence_digest=sequence_digest,
        movie_sha256=movie_sha256,
        movie_bytes=movie_bytes,
        extraction_source_identity=extraction_source_identity,
        extraction_command_sha256=extraction_command_sha256,
        created_at=created_at,
        duration_ms=duration_ms,
        frames_per_second=frames_per_second,
        frames=tuple(verified),
    )


def build_movie_frame_sequence_manifest(
    *,
    movie_sha256: str,
    movie_bytes: int,
    extraction_source_identity: str,
    extraction_command_sha256: str,
    created_at: str,
    duration_ms: int,
    frames_per_second: float,
    frames: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    partial: dict[str, Any] = {
        "schema": _SEQUENCE_SCHEMA,
        "movieSha256": _sha256(movie_sha256, label="movie_sha256"),
        "movieBytes": _integer(
            movie_bytes,
            label="movie_bytes",
            minimum=64,
            maximum=64 * 1024 * 1024 * 1024,
        ),
        "extractionSourceIdentity": _sha256(
            extraction_source_identity,
            label="extraction_source_identity",
        ),
        "extractionCommandSha256": _sha256(
            extraction_command_sha256,
            label="extraction_command_sha256",
        ),
        "createdAt": _timestamp(created_at, label="created_at").isoformat(),
        "durationMs": _integer(
            duration_ms,
            label="duration_ms",
            minimum=0,
            maximum=_MAX_DURATION_MS,
        ),
        "framesPerSecond": _number(
            frames_per_second,
            label="frames_per_second",
            minimum=0.1,
            maximum=240.0,
        ),
        "frames": [dict(frame) for frame in frames],
    }
    if not 1 <= len(partial["frames"]) <= _MAX_FRAMES:
        raise NativeQaError(f"frames must contain between 1 and {_MAX_FRAMES} records")
    return {**partial, "sequenceDigest": _digest(partial)}


def analyse_movie_frame_sequence(
    sequence: VerifiedMovieFrameSequence,
    *,
    expected_change: bool,
    minimum_samples: int = 3,
    maximum_gap_ms: int = 2000,
    maximum_frozen_duration_ms: int = 2000,
    boundary_tolerance_ms: int = 1000,
) -> dict[str, Any]:
    if not isinstance(sequence, VerifiedMovieFrameSequence):
        raise NativeQaError("sequence must be verified before temporal analysis")
    if not isinstance(expected_change, bool):
        raise NativeQaError("expected_change must be boolean")
    minimum = _integer(
        minimum_samples,
        label="minimum_samples",
        minimum=2,
        maximum=_MAX_FRAMES,
    )
    gap_limit = _integer(
        maximum_gap_ms,
        label="maximum_gap_ms",
        minimum=0,
        maximum=_MAX_DURATION_MS,
    )
    frozen_limit = _integer(
        maximum_frozen_duration_ms,
        label="maximum_frozen_duration_ms",
        minimum=0,
        maximum=_MAX_DURATION_MS,
    )
    boundary_tolerance = _integer(
        boundary_tolerance_ms,
        label="boundary_tolerance_ms",
        minimum=0,
        maximum=_MAX_DURATION_MS,
    )
    frames = sequence.frames
    findings: list[TemporalFinding] = []
    if len(frames) < minimum:
        findings.append(
            TemporalFinding(
                code="insufficient-samples",
                severity="error",
                detail=f"Temporal analysis requires at least {minimum} sampled frames.",
                frame_ids=tuple(frame.frame_id for frame in frames),
            )
        )
    if frames and frames[0].timestamp_ms > boundary_tolerance:
        findings.append(
            TemporalFinding(
                code="missing-start-boundary",
                severity="error",
                detail=(
                    f"The first sampled frame begins at {frames[0].timestamp_ms}ms; "
                    f"policy allows at most {boundary_tolerance}ms."
                ),
                frame_ids=(frames[0].frame_id,),
            )
        )
    if frames and sequence.duration_ms - frames[-1].timestamp_ms > boundary_tolerance:
        findings.append(
            TemporalFinding(
                code="missing-end-boundary",
                severity="error",
                detail=(
                    f"The final sampled frame ends {sequence.duration_ms - frames[-1].timestamp_ms}ms "
                    "before the movie boundary."
                ),
                frame_ids=(frames[-1].frame_id,),
            )
        )

    for previous, current in zip(frames, frames[1:], strict=False):
        gap = current.timestamp_ms - previous.timestamp_ms
        if gap > gap_limit:
            findings.append(
                TemporalFinding(
                    code="sample-gap",
                    severity="warning",
                    detail=f"Sample gap was {gap}ms; policy allows {gap_limit}ms.",
                    frame_ids=(previous.frame_id, current.frame_id),
                )
            )

    if expected_change:
        start = 0
        while start < len(frames) - 1:
            end = start + 1
            while end < len(frames) and frames[end].sha256 == frames[start].sha256:
                end += 1
            duration = frames[end - 1].timestamp_ms - frames[start].timestamp_ms
            if end - start >= 2 and duration > frozen_limit:
                findings.append(
                    TemporalFinding(
                        code="unexpected-freeze",
                        severity="error",
                        detail=(
                            f"Rendered sampled pixels remained unchanged for {duration}ms while "
                            "change was expected."
                        ),
                        frame_ids=tuple(frame.frame_id for frame in frames[start:end]),
                    )
                )
            start = end
    elif len({frame.sha256 for frame in frames}) > 1:
        findings.append(
            TemporalFinding(
                code="unexpected-change",
                severity="warning",
                detail="Sampled pixels changed although the state was declared static.",
                frame_ids=tuple(frame.frame_id for frame in frames),
            )
        )

    for first, middle, last in zip(frames, frames[1:], frames[2:], strict=False):
        if first.sha256 == last.sha256 and first.sha256 != middle.sha256:
            findings.append(
                TemporalFinding(
                    code="two-frame-flicker",
                    severity="warning",
                    detail="The sampled image changed once and immediately returned.",
                    frame_ids=(first.frame_id, middle.frame_id, last.frame_id),
                )
            )

    observed_change = len({frame.sha256 for frame in frames}) > 1
    severities = {finding.severity for finding in findings}
    verdict = "fail" if "error" in severities else "needs-review" if findings else "pass"
    findings_payload = [
        {
            "code": finding.code,
            "severity": finding.severity,
            "detail": finding.detail,
            "frameIds": list(finding.frame_ids),
        }
        for finding in findings
    ]
    policy = {
        "expectedChange": expected_change,
        "minimumSamples": minimum,
        "maximumGapMs": gap_limit,
        "maximumFrozenDurationMs": frozen_limit,
        "boundaryToleranceMs": boundary_tolerance,
    }
    report_partial = {
        "schema": "evavo.godot-movie-temporal-report.v1",
        "inputMovieSha256": sequence.movie_sha256,
        "sequenceDigest": sequence.sequence_digest,
        "sequenceManifestSha256": sequence.manifest_sha256,
        "sampledFrameCount": len(frames),
        "observedChange": observed_change,
        "temporalVerdict": verdict,
        "policy": policy,
        "findings": findings_payload,
    }
    return {**report_partial, "reportDigest": _digest(report_partial)}


def build_temporal_adapter_receipt(
    *,
    sequence: VerifiedMovieFrameSequence,
    report: Mapping[str, Any],
    source_identity: str,
    issued_at: str,
    worker_admitted: bool = False,
) -> dict[str, Any]:
    if not isinstance(sequence, VerifiedMovieFrameSequence):
        raise NativeQaError("sequence must be verified before receipt creation")
    source = _sha256(source_identity, label="source_identity")
    issued = _timestamp(issued_at, label="issued_at")
    admitted = _boolean(worker_admitted, label="worker_admitted")
    if not isinstance(report, Mapping):
        raise NativeQaError("report must be an object")
    report_digest = _sha256(report.get("reportDigest"), label="report.reportDigest")
    report_partial = dict(report)
    report_partial.pop("reportDigest", None)
    if _digest(report_partial) != report_digest:
        raise NativeQaError("temporal report digest does not match its content")
    if report.get("schema") != "evavo.godot-movie-temporal-report.v1":
        raise NativeQaError("temporal report schema is unsupported")
    if report.get("inputMovieSha256") != sequence.movie_sha256:
        raise NativeQaError("temporal report is bound to a different movie")
    if report.get("sequenceDigest") != sequence.sequence_digest:
        raise NativeQaError("temporal report is bound to a different frame sequence")
    if report.get("sequenceManifestSha256") != sequence.manifest_sha256:
        raise NativeQaError("temporal report manifest digest does not match")
    if report.get("sampledFrameCount") != len(sequence.frames):
        raise NativeQaError("temporal report frame count does not match")
    observed_change = _boolean(
        report.get("observedChange"),
        label="report.observedChange",
    )
    findings = _validated_findings(report.get("findings"), label="report.findings")
    frame_ids = {frame.frame_id for frame in sequence.frames}
    for finding in findings:
        if any(frame_id not in frame_ids for frame_id in finding["frameIds"]):
            raise NativeQaError("temporal report finding references an unknown sampled frame")
    verdict = report.get("temporalVerdict")
    if verdict != _verdict_for_findings(findings):
        raise NativeQaError("temporal report verdict is inconsistent with its findings")

    partial: dict[str, Any] = {
        "schema": _ADAPTER_SCHEMA,
        "adapterId": _ADAPTER_ID,
        "sourceIdentity": source,
        "issuedAt": issued.isoformat(),
        "expiresAt": (issued + _RECEIPT_LIFETIME).isoformat(),
        "status": "worker-admitted" if admitted else "locally-verified",
        "ready": True,
        "workerAdmitted": admitted,
        "capabilities": sorted(_REQUIRED_CAPABILITIES),
        "inputMovieSha256": sequence.movie_sha256,
        "sequenceManifestRelativePath": sequence.manifest_relative_path,
        "sequenceManifestSha256": sequence.manifest_sha256,
        "sequenceDigest": sequence.sequence_digest,
        "extractionSourceIdentity": sequence.extraction_source_identity,
        "extractionCommandSha256": sequence.extraction_command_sha256,
        "sampledFrameCount": len(sequence.frames),
        "observedChange": observed_change,
        "temporalVerdict": verdict,
        "temporalAnalysisSha256": report_digest,
        "evidenceSha256": report_digest,
        "findings": findings,
        "arbitraryShellAccepted": False,
        "sourceMutationPerformed": False,
        "truthBoundary": (
            "This receipt proves that exact PNG bytes from a digest-bound sampled sequence were "
            "analysed against temporal gap, boundary, freeze and flicker policies and were bound "
            "to the captured movie hash. It does not prove the extractor was truthful beyond its "
            "source identity, that unsampled frames were clean, or that a human reviewed the movie."
        ),
    }
    partial["receiptDigest"] = _digest(partial)
    return partial


def verify_temporal_adapter_receipt(
    receipt: Any,
    *,
    now: datetime | None = None,
    expected_source_identity: str | None = None,
) -> bool:
    try:
        value = _object(receipt, label="temporal adapter receipt")
        keys = frozenset(value)
        if keys not in {
            frozenset(_BASE_RECEIPT_KEYS),
            frozenset(_BASE_RECEIPT_KEYS | _REPORT_BINDING_KEYS),
        }:
            return False
        expected = _sha256(value.get("receiptDigest"), label="receiptDigest")
        partial = dict(value)
        partial.pop("receiptDigest", None)
        if _digest(partial) != expected:
            return False
        if value.get("schema") != _ADAPTER_SCHEMA or value.get("adapterId") != _ADAPTER_ID:
            return False
        if value.get("ready") is not True:
            return False
        admitted = _boolean(value.get("workerAdmitted"), label="workerAdmitted")
        expected_status = "worker-admitted" if admitted else "locally-verified"
        if value.get("status") != expected_status:
            return False
        source = _sha256(value.get("sourceIdentity"), label="sourceIdentity")
        if expected_source_identity is not None:
            if source != _sha256(
                expected_source_identity,
                label="expected_source_identity",
            ):
                return False
        for field in (
            "inputMovieSha256",
            "sequenceManifestSha256",
            "sequenceDigest",
            "extractionSourceIdentity",
            "extractionCommandSha256",
            "temporalAnalysisSha256",
            "evidenceSha256",
        ):
            _sha256(value.get(field), label=field)
        if value.get("evidenceSha256") != value.get("temporalAnalysisSha256"):
            return False
        _safe_relative_path(
            value.get("sequenceManifestRelativePath"),
            label="sequenceManifestRelativePath",
        )
        if _REPORT_BINDING_KEYS.issubset(keys):
            _safe_relative_path(
                value.get("temporalReportRelativePath"),
                label="temporalReportRelativePath",
            )
            _sha256(
                value.get("temporalReportFileSha256"),
                label="temporalReportFileSha256",
            )
        _integer(
            value.get("sampledFrameCount"),
            label="sampledFrameCount",
            minimum=1,
            maximum=_MAX_FRAMES,
        )
        _boolean(value.get("observedChange"), label="observedChange")
        findings = _validated_findings(value.get("findings"), label="findings")
        if value.get("temporalVerdict") != _verdict_for_findings(findings):
            return False
        issued = _timestamp(value.get("issuedAt"), label="issuedAt")
        expires = _timestamp(value.get("expiresAt"), label="expiresAt")
        if expires <= issued or expires - issued > _RECEIPT_LIFETIME:
            return False
        current = (now or datetime.now(UTC)).astimezone(UTC)
        if issued > current + _MAX_FUTURE_SKEW or expires <= current:
            return False
        capabilities = value.get("capabilities")
        if (
            not isinstance(capabilities, list)
            or len(capabilities) != len(set(capabilities))
            or set(capabilities) != _REQUIRED_CAPABILITIES
        ):
            return False
        if value.get("arbitraryShellAccepted") is not False:
            return False
        if value.get("sourceMutationPerformed") is not False:
            return False
        truth_boundary = value.get("truthBoundary")
        if (
            not isinstance(truth_boundary, str)
            or not truth_boundary.strip()
            or len(truth_boundary) > 4096
            or "\0" in truth_boundary
        ):
            return False
        return True
    except (NativeQaError, OSError, TypeError, ValueError):
        return False


def source_identity(paths: Iterable[Path], *, root: Path) -> str:
    values = tuple(paths)
    if not 1 <= len(values) <= 256:
        raise NativeQaError("temporal source path list is outside policy")
    verified: dict[str, Path] = {}
    for raw_path in values:
        actual, relative, _ = confined_regular_file(
            root,
            raw_path,
            label="temporal source file",
            maximum_bytes=8 * 1024 * 1024,
        )
        if relative in verified:
            raise NativeQaError("temporal source path list contains duplicates")
        verified[relative] = actual
    digest = hashlib.sha256()
    for relative in sorted(verified):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        with verified[relative].open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()
