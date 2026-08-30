from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .movie_evidence import (
    build_movie_adapter_receipt,
    confined_regular_file,
    validate_avi_movie,
    verify_movie_adapter_receipt,
)
from .movie_source_identity import capture_movie_source_identity
from .native_qa_common import NativeQaError


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
    if candidate == root:
        return
    relative = Path(_relative_inside(root, candidate, label=label))
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise NativeQaError(f"{label} may not traverse symbolic links")


def _json_object(
    root: Path,
    path: Path,
    *,
    label: str,
    maximum_bytes: int = 1024 * 1024,
) -> dict[str, Any]:
    resolved, _, _ = confined_regular_file(
        root,
        path,
        label=label,
        maximum_bytes=maximum_bytes,
    )
    try:
        value = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise NativeQaError(f"{label} is not valid UTF-8 JSON") from error
    if not isinstance(value, dict):
        raise NativeQaError(f"{label} must contain a JSON object")
    return value


def _write_json(root: Path, path: Path | None, value: dict[str, Any]) -> None:
    encoded = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    if path is None:
        print(encoded.decode("utf-8"), end="")
        return
    destination = path.expanduser()
    if not destination.is_absolute():
        destination = root / destination
    destination = destination.resolve(strict=False)
    _relative_inside(root, destination, label="movie evidence receipt output")
    destination.parent.mkdir(parents=True, exist_ok=True)
    _reject_symlink_components(
        root,
        destination.parent,
        label="movie evidence receipt output parent",
    )
    try:
        with destination.open("xb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as error:
        raise NativeQaError(
            "refusing to overwrite an existing movie evidence receipt"
        ) from error


def _current_source_identity(requested: str | None) -> str:
    actual = capture_movie_source_identity()
    if requested is not None and requested != actual:
        raise NativeQaError(
            "requested movie capture source identity does not match the current implementation"
        )
    return actual


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="godot-lab-movie-evidence",
        description="Create or validate exact-byte Godot Movie Maker evidence receipts.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser(
        "receipt",
        help="Validate an AVI and issue a source-bound local adapter receipt.",
    )
    create.add_argument("--artifact-root", type=Path, required=True)
    create.add_argument("--movie", type=Path, required=True)
    create.add_argument("--journey-id", required=True)
    create.add_argument(
        "--source-identity",
        help="Optional assertion; it must equal the current capture-provider source identity.",
    )
    create.add_argument("--command-sha256", required=True)
    create.add_argument("--started-at", required=True)
    create.add_argument("--completed-at", required=True)
    create.add_argument("--frames-per-second", type=int, default=30)
    create.add_argument("--output", type=Path)

    doctor = subparsers.add_parser(
        "doctor",
        help="Reopen a receipt and verify its current source and exact AVI bytes.",
    )
    doctor.add_argument("--artifact-root", type=Path, required=True)
    doctor.add_argument("--receipt", type=Path, required=True)
    doctor.add_argument(
        "--expected-source-identity",
        help="Optional assertion; it must equal the current capture-provider source identity.",
    )
    return parser


def _create_receipt(args: argparse.Namespace) -> dict[str, Any]:
    root = _artifact_root(args.artifact_root)
    source_identity = _current_source_identity(args.source_identity)
    evidence = validate_avi_movie(root, args.movie)
    receipt = build_movie_adapter_receipt(
        evidence=evidence,
        journey_id=args.journey_id,
        source_identity=source_identity,
        command_sha256=args.command_sha256,
        started_at=args.started_at,
        completed_at=args.completed_at,
        frames_per_second=args.frames_per_second,
        worker_admitted=False,
    )
    _write_json(root, args.output, receipt)
    return receipt


def _doctor(args: argparse.Namespace) -> dict[str, Any]:
    root = _artifact_root(args.artifact_root)
    source_identity = _current_source_identity(args.expected_source_identity)
    receipt = _json_object(root, args.receipt, label="movie evidence receipt")
    if not verify_movie_adapter_receipt(
        receipt,
        expected_source_identity=source_identity,
    ):
        raise NativeQaError(
            "movie evidence receipt failed its digest, source, schema or expiry validation"
        )
    evidence = validate_avi_movie(
        root,
        Path(str(receipt.get("movieRelativePath", ""))),
    )
    if not (
        evidence.sha256
        == receipt.get("movieSha256")
        == receipt.get("videoSha256")
        == receipt.get("evidenceSha256")
    ):
        raise NativeQaError("movie evidence bytes no longer match the receipt digest")
    if evidence.size_bytes != receipt.get("movieBytes") or evidence.size_bytes != receipt.get(
        "videoBytes"
    ):
        raise NativeQaError("movie evidence bytes no longer match the receipt size")
    result = {
        "schema": "evavo.godot-movie-adapter-doctor.v2",
        "adapterId": "godot-game-test-lab.video-evidence",
        "status": receipt.get("status"),
        "ready": True,
        "workerAdmitted": receipt.get("workerAdmitted") is True,
        "sourceIdentity": source_identity,
        "journeyId": receipt.get("journeyId"),
        "movieRelativePath": evidence.relative_path,
        "movieSha256": evidence.sha256,
        "videoSha256": evidence.sha256,
        "evidenceSha256": evidence.sha256,
        "movieBytes": evidence.size_bytes,
        "videoBytes": evidence.size_bytes,
        "container": evidence.container,
        "mediaType": evidence.container,
        "captureElapsedSeconds": receipt.get("captureElapsedSeconds"),
        "exactMovieBytesVerified": True,
        "currentSourceIdentityVerified": True,
        "capabilities": receipt.get("capabilities"),
        "truthBoundary": (
            "The doctor reopened and verified the exact AVI bytes, expiring receipt and current "
            "capture-provider source identity. Capture elapsed time is not asserted playback "
            "duration. It does not claim that a reviewer inspected every frame or that the "
            "journey is defect-free."
        ),
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        if args.command == "receipt":
            _create_receipt(args)
        else:
            _doctor(args)
    except (NativeQaError, FileNotFoundError, OSError, TypeError, ValueError) as error:
        print(
            json.dumps(
                {
                    "schema": "evavo.godot-movie-adapter-doctor.v2",
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
