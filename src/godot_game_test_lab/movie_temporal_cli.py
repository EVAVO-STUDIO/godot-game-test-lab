from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .movie_evidence import (
    confined_regular_file,
    validate_avi_movie,
    verify_movie_adapter_receipt,
)
from .movie_temporal import (
    analyse_movie_frame_sequence,
    build_movie_frame_sequence_manifest,
    build_temporal_adapter_receipt,
    load_verified_movie_frame_sequence,
    verify_temporal_adapter_receipt,
)
from .native_qa_common import NativeQaError

_MAX_JSON_BYTES = 8 * 1024 * 1024
_MAX_FRAME_BYTES = 25 * 1024 * 1024
_PNG_SIGNATURE = bytes((137, 80, 78, 71, 13, 10, 26, 10))


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _artifact_root(value: Path) -> Path:
    root = value.expanduser().resolve(strict=True)
    if not root.is_dir() or root.is_symlink():
        raise NativeQaError("artifact root must be a non-symlink directory")
    return root


def _relative_inside(root: Path, candidate: Path, *, label: str) -> str:
    try:
        relative = candidate.relative_to(root)
    except ValueError as error:
        raise NativeQaError(f"{label} escapes the admitted artifact root") from error
    if relative == Path("."):
        raise NativeQaError(f"{label} may not be the artifact root itself")
    return relative.as_posix()


def _reject_symlink_components(root: Path, candidate: Path, *, label: str) -> None:
    relative = Path(_relative_inside(root, candidate, label=label))
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise NativeQaError(f"{label} may not traverse symbolic links")


def _output_path(root: Path, value: Path, *, label: str) -> tuple[Path, str]:
    requested = value.expanduser()
    if not requested.is_absolute():
        requested = root / requested
    requested = requested.resolve(strict=False)
    relative = _relative_inside(root, requested, label=label)
    requested.parent.mkdir(parents=True, exist_ok=True)
    _reject_symlink_components(root, requested.parent, label=f"{label} parent")
    if requested.exists():
        raise NativeQaError(f"refusing to overwrite an existing {label}")
    return requested, relative


def _read_json(
    root: Path,
    value: Path,
    *,
    label: str,
    maximum_bytes: int = _MAX_JSON_BYTES,
) -> tuple[dict[str, Any], Path, str, bytes]:
    actual, relative, _ = confined_regular_file(
        root,
        value,
        label=label,
        maximum_bytes=maximum_bytes,
    )
    raw = actual.read_bytes()
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise NativeQaError(f"{label} is not valid UTF-8 JSON") from error
    if not isinstance(parsed, dict):
        raise NativeQaError(f"{label} must contain a JSON object")
    return parsed, actual, relative, raw


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def _write_create_once(path: Path, payload: bytes) -> None:
    try:
        with path.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as error:
        raise NativeQaError(f"refusing to overwrite existing output: {path}") from error


def _boolean(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise argparse.ArgumentTypeError("boolean values must be true or false")


def _frame_records(root: Path, descriptor: Mapping[str, Any]) -> list[dict[str, Any]]:
    if descriptor.get("schema") != "evavo.godot-sampled-frame-input.v1":
        raise NativeQaError("sampled frame descriptor schema is unsupported")
    unknown = sorted(set(descriptor) - {"schema", "frames"})
    if unknown:
        raise NativeQaError(
            "sampled frame descriptor contains unsupported fields: " + ", ".join(unknown)
        )
    raw_frames = descriptor.get("frames")
    if not isinstance(raw_frames, list) or not 1 <= len(raw_frames) <= 10_000:
        raise NativeQaError("sampled frame descriptor must contain between 1 and 10000 frames")
    records: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_frames):
        if not isinstance(raw, dict):
            raise NativeQaError(f"frames[{index}] must be an object")
        unknown_frame = sorted(set(raw) - {"id", "timestampMs", "relativePath"})
        if unknown_frame:
            raise NativeQaError(
                f"frames[{index}] contains unsupported fields: {', '.join(unknown_frame)}"
            )
        frame_id = raw.get("id")
        if not isinstance(frame_id, str) or not frame_id or len(frame_id) > 255:
            raise NativeQaError(f"frames[{index}].id must be a bounded stable token")
        timestamp_ms = raw.get("timestampMs")
        if (
            isinstance(timestamp_ms, bool)
            or not isinstance(timestamp_ms, int)
            or not 0 <= timestamp_ms <= 24 * 60 * 60 * 1000
        ):
            raise NativeQaError(f"frames[{index}].timestampMs is outside policy")
        relative_path = raw.get("relativePath")
        if not isinstance(relative_path, str):
            raise NativeQaError(f"frames[{index}].relativePath is required")
        actual, canonical, size = confined_regular_file(
            root,
            Path(relative_path),
            label=f"sampled frame {frame_id}",
            maximum_bytes=_MAX_FRAME_BYTES,
        )
        with actual.open("rb") as stream:
            if stream.read(len(_PNG_SIGNATURE)) != _PNG_SIGNATURE:
                raise NativeQaError(f"sampled frame {frame_id} is not a PNG file")
        records.append(
            {
                "id": frame_id,
                "timestampMs": timestamp_ms,
                "relativePath": canonical,
                "sha256": hashlib.sha256(actual.read_bytes()).hexdigest(),
                "bytes": size,
            }
        )
    return records


def _manifest(args: argparse.Namespace) -> dict[str, Any]:
    root = _artifact_root(args.artifact_root)
    capture, _, _, _ = _read_json(
        root,
        args.movie_receipt,
        label="Godot movie capture receipt",
        maximum_bytes=1024 * 1024,
    )
    if not verify_movie_adapter_receipt(capture):
        raise NativeQaError("Godot movie capture receipt failed validation")
    movie = validate_avi_movie(root, Path(str(capture.get("movieRelativePath", ""))))
    if movie.sha256 != capture.get("movieSha256"):
        raise NativeQaError("Godot movie bytes no longer match the capture receipt digest")
    if movie.size_bytes != capture.get("movieBytes"):
        raise NativeQaError("Godot movie bytes no longer match the capture receipt size")
    descriptor, _, _, _ = _read_json(
        root,
        args.frames,
        label="sampled frame descriptor",
    )
    value = build_movie_frame_sequence_manifest(
        movie_sha256=movie.sha256,
        movie_bytes=movie.size_bytes,
        extraction_source_identity=args.extraction_source_identity,
        extraction_command_sha256=args.extraction_command_sha256,
        created_at=datetime.now(UTC).isoformat(),
        duration_ms=args.duration_ms,
        frames_per_second=args.frames_per_second,
        frames=_frame_records(root, descriptor),
    )
    output, _ = _output_path(root, args.output, label="movie frame sequence manifest")
    _write_create_once(output, _json_bytes(value))
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))
    return value


def _analyse(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    root = _artifact_root(args.artifact_root)
    sequence = load_verified_movie_frame_sequence(root, args.sequence)
    report = analyse_movie_frame_sequence(
        sequence,
        expected_change=args.expected_change,
        minimum_samples=args.minimum_samples,
        maximum_gap_ms=args.maximum_gap_ms,
        maximum_frozen_duration_ms=args.maximum_frozen_duration_ms,
        boundary_tolerance_ms=args.boundary_tolerance_ms,
    )
    report_path, report_relative = _output_path(
        root,
        args.report_output,
        label="temporal report",
    )
    receipt_path, _ = _output_path(
        root,
        args.receipt_output,
        label="temporal adapter receipt",
    )
    report_bytes = _json_bytes(report)
    receipt = build_temporal_adapter_receipt(
        sequence=sequence,
        report=report,
        source_identity=args.source_identity,
        issued_at=datetime.now(UTC).isoformat(),
        worker_admitted=False,
    )
    receipt_partial = dict(receipt)
    receipt_partial.pop("receiptDigest", None)
    receipt_partial["temporalReportRelativePath"] = report_relative
    receipt_partial["temporalReportFileSha256"] = _sha256_bytes(report_bytes)
    receipt = {
        **receipt_partial,
        "receiptDigest": _canonical_digest(receipt_partial),
    }
    receipt_bytes = _json_bytes(receipt)
    report_created = False
    try:
        _write_create_once(report_path, report_bytes)
        report_created = True
        _write_create_once(receipt_path, receipt_bytes)
    except Exception:
        if report_created:
            report_path.unlink(missing_ok=True)
        raise
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return report, receipt


def _doctor(args: argparse.Namespace) -> dict[str, Any]:
    root = _artifact_root(args.artifact_root)
    receipt, _, _, _ = _read_json(
        root,
        args.receipt,
        label="temporal adapter receipt",
        maximum_bytes=1024 * 1024,
    )
    if not verify_temporal_adapter_receipt(receipt):
        raise NativeQaError("temporal adapter receipt failed digest, schema or expiry validation")
    if (
        args.expected_source_identity is not None
        and receipt.get("sourceIdentity") != args.expected_source_identity
    ):
        raise NativeQaError("temporal adapter receipt source identity does not match")
    sequence = load_verified_movie_frame_sequence(
        root,
        Path(str(receipt.get("sequenceManifestRelativePath", ""))),
        expected_movie_sha256=str(receipt.get("inputMovieSha256", "")),
        expected_extraction_source_identity=str(
            receipt.get("extractionSourceIdentity", "")
        ),
    )
    report_relative = receipt.get("temporalReportRelativePath")
    report_file_sha256 = receipt.get("temporalReportFileSha256")
    if not isinstance(report_relative, str) or not isinstance(report_file_sha256, str):
        raise NativeQaError("temporal adapter receipt is missing its report file binding")
    report, _, canonical_report_path, report_bytes = _read_json(
        root,
        Path(report_relative),
        label="temporal report",
        maximum_bytes=1024 * 1024,
    )
    if canonical_report_path != report_relative:
        raise NativeQaError("temporal report path is not canonical")
    if _sha256_bytes(report_bytes) != report_file_sha256:
        raise NativeQaError("temporal report file digest does not match the receipt")
    policy = report.get("policy")
    if not isinstance(policy, dict):
        raise NativeQaError("temporal report policy is invalid")
    expected = analyse_movie_frame_sequence(
        sequence,
        expected_change=policy.get("expectedChange"),
        minimum_samples=policy.get("minimumSamples"),
        maximum_gap_ms=policy.get("maximumGapMs"),
        maximum_frozen_duration_ms=policy.get("maximumFrozenDurationMs"),
        boundary_tolerance_ms=policy.get("boundaryToleranceMs"),
    )
    if expected != report:
        raise NativeQaError("temporal report no longer matches the exact sampled frame bytes")
    if receipt.get("temporalAnalysisSha256") != report.get("reportDigest"):
        raise NativeQaError("temporal analysis digest does not match the receipt")
    if receipt.get("sampledFrameCount") != len(sequence.frames):
        raise NativeQaError("temporal adapter receipt frame count does not match")
    if receipt.get("observedChange") != report.get("observedChange"):
        raise NativeQaError("temporal adapter receipt change result does not match")
    if receipt.get("temporalVerdict") != report.get("temporalVerdict"):
        raise NativeQaError("temporal adapter receipt verdict does not match")
    result = {
        "schema": "evavo.godot-movie-temporal-doctor.v1",
        "adapterId": "godot-game-test-lab.movie-temporal",
        "status": receipt.get("status"),
        "ready": True,
        "workerAdmitted": receipt.get("workerAdmitted") is True,
        "sourceIdentity": receipt.get("sourceIdentity"),
        "inputMovieSha256": sequence.movie_sha256,
        "sequenceManifestRelativePath": sequence.manifest_relative_path,
        "sequenceManifestSha256": sequence.manifest_sha256,
        "temporalReportRelativePath": report_relative,
        "temporalReportFileSha256": report_file_sha256,
        "temporalAnalysisSha256": report.get("reportDigest"),
        "sampledFrameCount": len(sequence.frames),
        "observedChange": report.get("observedChange"),
        "temporalVerdict": report.get("temporalVerdict"),
        "exactFrameBytesVerified": True,
        "truthBoundary": (
            "The doctor reopened every sampled PNG, recomputed the temporal report and verified "
            "the report file binding. It does not prove unsampled frames or human visual approval."
        ),
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="godot-lab-movie-temporal",
        description="Build and verify digest-bound temporal evidence for Godot Movie Maker AVI files.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    manifest = commands.add_parser("manifest", help="Bind sampled PNG frames to a movie receipt.")
    manifest.add_argument("--artifact-root", type=Path, required=True)
    manifest.add_argument("--movie-receipt", type=Path, required=True)
    manifest.add_argument("--frames", type=Path, required=True)
    manifest.add_argument("--duration-ms", type=int, required=True)
    manifest.add_argument("--frames-per-second", type=float, required=True)
    manifest.add_argument("--extraction-source-identity", required=True)
    manifest.add_argument("--extraction-command-sha256", required=True)
    manifest.add_argument("--output", type=Path, required=True)

    analyse = commands.add_parser("analyse", help="Analyse one verified sampled frame sequence.")
    analyse.add_argument("--artifact-root", type=Path, required=True)
    analyse.add_argument("--sequence", type=Path, required=True)
    analyse.add_argument("--source-identity", required=True)
    analyse.add_argument("--expected-change", type=_boolean, required=True)
    analyse.add_argument("--minimum-samples", type=int, default=3)
    analyse.add_argument("--maximum-gap-ms", type=int, default=2000)
    analyse.add_argument("--maximum-frozen-duration-ms", type=int, default=2000)
    analyse.add_argument("--boundary-tolerance-ms", type=int, default=1000)
    analyse.add_argument("--report-output", type=Path, required=True)
    analyse.add_argument("--receipt-output", type=Path, required=True)

    doctor = commands.add_parser("doctor", help="Reopen and independently verify temporal evidence.")
    doctor.add_argument("--artifact-root", type=Path, required=True)
    doctor.add_argument("--receipt", type=Path, required=True)
    doctor.add_argument("--expected-source-identity")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        if args.command == "manifest":
            _manifest(args)
        elif args.command == "analyse":
            _analyse(args)
        else:
            _doctor(args)
    except (NativeQaError, FileNotFoundError, OSError, TypeError, ValueError) as error:
        print(
            json.dumps(
                {
                    "schema": "evavo.godot-movie-temporal-doctor.v1",
                    "status": "source-present",
                    "ready": False,
                    "error": str(error),
                },
                sort_keys=True,
            )
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
