from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .movie_evidence import (
    build_movie_adapter_receipt,
    validate_avi_movie,
    verify_movie_adapter_receipt,
)
from .native_qa_common import NativeQaError


def _json_object(path: Path, *, label: str, maximum_bytes: int = 1024 * 1024) -> dict[str, Any]:
    resolved = path.expanduser().resolve(strict=True)
    if not resolved.is_file():
        raise NativeQaError(f"{label} is not a regular file")
    size = resolved.stat().st_size
    if not 1 <= size <= maximum_bytes:
        raise NativeQaError(f"{label} size is outside policy")
    try:
        value = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise NativeQaError(f"{label} is not valid UTF-8 JSON") from error
    if not isinstance(value, dict):
        raise NativeQaError(f"{label} must contain a JSON object")
    return value


def _write_json(path: Path | None, value: dict[str, Any]) -> None:
    encoded = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if path is None:
        print(encoded, end="")
        return
    destination = path.expanduser().resolve(strict=False)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise NativeQaError("refusing to overwrite an existing movie evidence receipt")
    destination.write_text(encoded, encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="godot-lab-movie-evidence",
        description="Create or validate exact-byte Godot Movie Maker evidence receipts.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("receipt", help="Validate an AVI and issue a local adapter receipt.")
    create.add_argument("--artifact-root", type=Path, required=True)
    create.add_argument("--movie", type=Path, required=True)
    create.add_argument("--journey-id", required=True)
    create.add_argument("--source-identity", required=True)
    create.add_argument("--command-sha256", required=True)
    create.add_argument("--started-at", required=True)
    create.add_argument("--completed-at", required=True)
    create.add_argument("--frames-per-second", type=int, default=30)
    create.add_argument("--output", type=Path)

    doctor = subparsers.add_parser("doctor", help="Reopen a receipt and verify its exact AVI bytes.")
    doctor.add_argument("--artifact-root", type=Path, required=True)
    doctor.add_argument("--receipt", type=Path, required=True)
    doctor.add_argument("--expected-source-identity")
    return parser


def _create_receipt(args: argparse.Namespace) -> dict[str, Any]:
    evidence = validate_avi_movie(args.artifact_root, args.movie)
    receipt = build_movie_adapter_receipt(
        evidence=evidence,
        journey_id=args.journey_id,
        source_identity=args.source_identity,
        command_sha256=args.command_sha256,
        started_at=args.started_at,
        completed_at=args.completed_at,
        frames_per_second=args.frames_per_second,
        worker_admitted=False,
    )
    _write_json(args.output, receipt)
    return receipt


def _doctor(args: argparse.Namespace) -> dict[str, Any]:
    receipt = _json_object(args.receipt, label="movie evidence receipt")
    if not verify_movie_adapter_receipt(receipt):
        raise NativeQaError("movie evidence receipt failed its digest or schema validation")
    if (
        args.expected_source_identity is not None
        and receipt.get("sourceIdentity") != args.expected_source_identity
    ):
        raise NativeQaError("movie evidence receipt source identity does not match")
    evidence = validate_avi_movie(
        args.artifact_root,
        Path(str(receipt.get("movieRelativePath", ""))),
    )
    if evidence.sha256 != receipt.get("movieSha256"):
        raise NativeQaError("movie evidence bytes no longer match the receipt digest")
    if evidence.size_bytes != receipt.get("movieBytes"):
        raise NativeQaError("movie evidence bytes no longer match the receipt size")
    result = {
        "schema": "evavo.godot-movie-adapter-doctor.v1",
        "adapterId": "godot-game-test-lab.video-evidence",
        "status": receipt.get("status"),
        "ready": True,
        "workerAdmitted": receipt.get("workerAdmitted") is True,
        "sourceIdentity": receipt.get("sourceIdentity"),
        "journeyId": receipt.get("journeyId"),
        "movieRelativePath": evidence.relative_path,
        "movieSha256": evidence.sha256,
        "movieBytes": evidence.size_bytes,
        "container": evidence.container,
        "exactMovieBytesVerified": True,
        "capabilities": receipt.get("capabilities"),
        "truthBoundary": (
            "The doctor reopened and verified the exact AVI bytes and receipt identity. It does "
            "not claim that a reviewer inspected every frame or that the journey is defect-free."
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
        print(json.dumps({
            "schema": "evavo.godot-movie-adapter-doctor.v1",
            "status": "source-present",
            "ready": False,
            "error": str(error),
        }, sort_keys=True))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
