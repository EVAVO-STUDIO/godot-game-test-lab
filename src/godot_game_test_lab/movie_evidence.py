from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

from .native_qa_common import NativeQaError

_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_MAX_COMMAND_ARGUMENTS = 512
_MAX_ARGUMENT_LENGTH = 4096
_DEFAULT_MAX_MOVIE_BYTES = 8 * 1024 * 1024 * 1024
_MIN_AVI_BYTES = 64


@dataclass(frozen=True)
class MovieEvidence:
    path: Path
    relative_path: str
    size_bytes: int
    sha256: str
    container: str = "video/x-msvideo"


def _bounded_integer(
    value: Any,
    *,
    label: str,
    minimum: int,
    maximum: int,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise NativeQaError(f"{label} must be an integer between {minimum} and {maximum}")
    return value


def _bounded_text(value: Any, *, label: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise NativeQaError(f"{label} is required")
    if len(value) > maximum or "\0" in value or "\r" in value or "\n" in value:
        raise NativeQaError(f"{label} must be a bounded single-line string")
    return value.strip()


def _timestamp(value: Any, *, label: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise NativeQaError(f"{label} must be an ISO-compatible timestamp")
    candidate = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as error:
        raise NativeQaError(f"{label} must be an ISO-compatible timestamp") from error
    if parsed.tzinfo is None:
        raise NativeQaError(f"{label} must include a timezone")
    return parsed.astimezone(UTC)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative_inside(root: Path, candidate: Path, *, label: str) -> str:
    try:
        relative = candidate.relative_to(root)
    except ValueError as error:
        raise NativeQaError(f"{label} escapes the admitted artifact root") from error
    if relative == Path("."):
        raise NativeQaError(f"{label} may not be the artifact root itself")
    return relative.as_posix()


def _reject_symlink_components(root: Path, candidate: Path, *, label: str) -> None:
    if root.is_symlink() or not root.is_dir():
        raise NativeQaError("artifact root must be a non-symlink directory")
    relative = Path(_relative_inside(root, candidate, label=label))
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise NativeQaError(f"{label} may not traverse symbolic links")


def confined_regular_file(
    artifact_root: Path,
    candidate: Path,
    *,
    label: str,
    maximum_bytes: int,
) -> tuple[Path, str, int]:
    maximum = _bounded_integer(
        maximum_bytes,
        label="maximum_bytes",
        minimum=1,
        maximum=64 * 1024 * 1024 * 1024,
    )
    root_requested = artifact_root.expanduser().resolve(strict=True)
    candidate_requested = candidate.expanduser()
    if not candidate_requested.is_absolute():
        candidate_requested = root_requested / candidate_requested
    candidate_requested = candidate_requested.resolve(strict=False)
    _relative_inside(root_requested, candidate_requested, label=label)
    _reject_symlink_components(root_requested, candidate_requested, label=label)
    actual = candidate_requested.resolve(strict=True)
    relative = _relative_inside(root_requested, actual, label=label)
    if not actual.is_file():
        raise NativeQaError(f"{label} is not a regular file")
    size = actual.stat().st_size
    if not 1 <= size <= maximum:
        raise NativeQaError(f"{label} size is outside policy")
    return actual, relative, size


def normalize_movie_output_path(
    artifact_root: Path,
    output: Path,
) -> tuple[Path, str]:
    root = artifact_root.expanduser().resolve(strict=True)
    if root.is_symlink() or not root.is_dir():
        raise NativeQaError("artifact root must be a non-symlink directory")
    requested = output.expanduser()
    if not requested.is_absolute():
        requested = root / requested
    requested = requested.resolve(strict=False)
    relative = _relative_inside(root, requested, label="movie output")
    if requested.suffix.lower() != ".avi":
        raise NativeQaError("Godot native movie evidence must use a .avi output")
    requested.parent.mkdir(parents=True, exist_ok=True)
    _reject_symlink_components(root, requested.parent, label="movie output parent")
    if requested.exists():
        raise NativeQaError("refusing to overwrite existing Godot movie evidence")
    return requested, relative


def inject_movie_maker_arguments(
    command: Sequence[str],
    *,
    artifact_root: Path,
    output: Path,
    frames_per_second: int = 30,
) -> tuple[list[str], Path, str]:
    if not isinstance(command, Sequence) or isinstance(command, (str, bytes)):
        raise NativeQaError("Godot command must be a sequence of arguments")
    if not 1 <= len(command) <= _MAX_COMMAND_ARGUMENTS:
        raise NativeQaError(
            f"Godot command must contain between 1 and {_MAX_COMMAND_ARGUMENTS} arguments"
        )
    normalized: list[str] = []
    for index, argument in enumerate(command):
        if not isinstance(argument, str) or not argument:
            raise NativeQaError(f"Godot command argument {index} must be a non-empty string")
        if len(argument) > _MAX_ARGUMENT_LENGTH or "\0" in argument:
            raise NativeQaError(f"Godot command argument {index} is outside policy")
        normalized.append(argument)
    if any(argument in {"--headless", "--write-movie", "--fixed-fps"} for argument in normalized):
        raise NativeQaError(
            "Godot movie evidence requires a non-headless command without pre-existing movie flags"
        )
    fps = _bounded_integer(
        frames_per_second,
        label="frames_per_second",
        minimum=1,
        maximum=240,
    )
    movie_path, relative_path = normalize_movie_output_path(artifact_root, output)
    separator = normalized.index("--") if "--" in normalized else len(normalized)
    injected = [
        "--write-movie",
        str(movie_path),
        "--fixed-fps",
        str(fps),
        "--disable-vsync",
    ]
    return normalized[:separator] + injected + normalized[separator:], movie_path, relative_path


def validate_avi_movie(
    artifact_root: Path,
    movie: Path,
    *,
    maximum_bytes: int = _DEFAULT_MAX_MOVIE_BYTES,
) -> MovieEvidence:
    actual, relative, size = confined_regular_file(
        artifact_root,
        movie,
        label="Godot movie evidence",
        maximum_bytes=maximum_bytes,
    )
    if size < _MIN_AVI_BYTES:
        raise NativeQaError("Godot movie evidence is too small to be a valid AVI")
    with actual.open("rb") as stream:
        prefix = stream.read(min(size, 1024 * 1024))
    if len(prefix) < 12 or prefix[:4] != b"RIFF" or prefix[8:12] != b"AVI ":
        raise NativeQaError("Godot movie evidence is missing the RIFF/AVI signature")
    if b"avih" not in prefix or b"movi" not in prefix:
        raise NativeQaError("Godot movie evidence is missing AVI header or movie data chunks")
    return MovieEvidence(
        path=actual,
        relative_path=relative,
        size_bytes=size,
        sha256=_sha256_file(actual),
    )


def command_digest(command: Iterable[str]) -> str:
    values = list(command)
    if not values:
        raise NativeQaError("Godot command is required")
    encoded = json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_movie_adapter_receipt(
    *,
    evidence: MovieEvidence,
    journey_id: str,
    source_identity: str,
    command_sha256: str,
    started_at: str,
    completed_at: str,
    frames_per_second: int,
    worker_admitted: bool = False,
) -> dict[str, Any]:
    journey = _bounded_text(journey_id, label="journey_id", maximum=255)
    if _TOKEN.fullmatch(journey) is None:
        raise NativeQaError("journey_id must be a bounded stable token")
    for value, label in (
        (source_identity, "source_identity"),
        (command_sha256, "command_sha256"),
        (evidence.sha256, "evidence.sha256"),
    ):
        if _SHA256.fullmatch(value) is None:
            raise NativeQaError(f"{label} must be a lowercase SHA-256 digest")
    if not isinstance(worker_admitted, bool):
        raise NativeQaError("worker_admitted must be boolean")
    fps = _bounded_integer(
        frames_per_second,
        label="frames_per_second",
        minimum=1,
        maximum=240,
    )
    started = _timestamp(started_at, label="started_at")
    completed = _timestamp(completed_at, label="completed_at")
    if completed < started:
        raise NativeQaError("completed_at may not predate started_at")
    partial: dict[str, Any] = {
        "schema": "evavo.godot-movie-adapter-receipt.v1",
        "adapterId": "godot-game-test-lab.video-evidence",
        "sourceIdentity": source_identity,
        "issuedAt": completed.isoformat(),
        "status": "worker-admitted" if worker_admitted else "locally-verified",
        "ready": True,
        "workerAdmitted": worker_admitted,
        "journeyId": journey,
        "commandSha256": command_sha256,
        "movieRelativePath": evidence.relative_path,
        "movieSha256": evidence.sha256,
        "movieBytes": evidence.size_bytes,
        "container": evidence.container,
        "framesPerSecond": fps,
        "startedAt": started.isoformat(),
        "completedAt": completed.isoformat(),
        "capabilities": ["screen-recording", "native-godot-movie", "exact-movie-bytes"],
        "headless": False,
        "arbitraryShellAccepted": False,
        "sourceMutationPerformed": False,
        "truthBoundary": (
            "This receipt proves that a non-headless Godot Movie Maker invocation produced "
            "digest-bound AVI bytes for one journey command. It does not prove that every frame "
            "was visually correct, that audio was captured, or that a reviewer inspected the movie."
        ),
    }
    partial["receiptDigest"] = hashlib.sha256(
        json.dumps(partial, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return partial


def verify_movie_adapter_receipt(receipt: Any) -> bool:
    try:
        if not isinstance(receipt, dict):
            return False
        expected = receipt.get("receiptDigest")
        if not isinstance(expected, str) or _SHA256.fullmatch(expected) is None:
            return False
        partial = dict(receipt)
        partial.pop("receiptDigest", None)
        actual = hashlib.sha256(
            json.dumps(partial, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        if actual != expected:
            return False
        if receipt.get("schema") != "evavo.godot-movie-adapter-receipt.v1":
            return False
        if receipt.get("adapterId") != "godot-game-test-lab.video-evidence":
            return False
        if receipt.get("ready") is not True:
            return False
        if receipt.get("headless") is not False:
            return False
        if receipt.get("arbitraryShellAccepted") is not False:
            return False
        if receipt.get("sourceMutationPerformed") is not False:
            return False
        if receipt.get("container") != "video/x-msvideo":
            return False
        for field in ("sourceIdentity", "commandSha256", "movieSha256"):
            value = receipt.get(field)
            if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
                return False
        _bounded_integer(
            receipt.get("movieBytes"),
            label="movieBytes",
            minimum=_MIN_AVI_BYTES,
            maximum=_DEFAULT_MAX_MOVIE_BYTES,
        )
        _bounded_integer(
            receipt.get("framesPerSecond"),
            label="framesPerSecond",
            minimum=1,
            maximum=240,
        )
        if _TOKEN.fullmatch(str(receipt.get("journeyId", ""))) is None:
            return False
        started = _timestamp(receipt.get("startedAt"), label="startedAt")
        completed = _timestamp(receipt.get("completedAt"), label="completedAt")
        if completed < started:
            return False
        capabilities = receipt.get("capabilities")
        if not isinstance(capabilities, list):
            return False
        required = {"screen-recording", "native-godot-movie", "exact-movie-bytes"}
        return required.issubset({str(value) for value in capabilities})
    except (NativeQaError, OSError, TypeError, ValueError):
        return False
