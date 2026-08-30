from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Sequence

from .native_qa_common import NativeQaError
from .visual_path_security import (
    confined_output_file,
)
from .visual_path_security import (
    confined_regular_file as _secure_confined_regular_file,
)

_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_MAX_COMMAND_ARGUMENTS = 512
_MAX_ARGUMENT_LENGTH = 4096
_DEFAULT_MAX_MOVIE_BYTES = 20 * 1024 * 1024 * 1024
_MIN_AVI_BYTES = 64
_RECEIPT_LIFETIME = timedelta(minutes=30)
_MAX_FUTURE_SKEW = timedelta(minutes=5)
_REQUIRED_CAPABILITIES = {
    "screen-recording",
    "native-godot-movie",
    "exact-movie-bytes",
}
_RECEIPT_KEYS = {
    "schema",
    "adapterId",
    "sourceIdentity",
    "issuedAt",
    "expiresAt",
    "capturedAt",
    "status",
    "ready",
    "workerAdmitted",
    "journeyId",
    "commandSha256",
    "movieRelativePath",
    "movieSha256",
    "movieBytes",
    "videoSha256",
    "videoBytes",
    "evidenceSha256",
    "container",
    "mediaType",
    "captureElapsedSeconds",
    "framesPerSecond",
    "startedAt",
    "completedAt",
    "capabilities",
    "headless",
    "arbitraryShellAccepted",
    "sourceMutationPerformed",
    "truthBoundary",
    "receiptDigest",
}


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


def _bounded_number(
    value: Any,
    *,
    label: str,
    minimum: float,
    maximum: float,
) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise NativeQaError(f"{label} must be a finite number")
    candidate = float(value)
    if not math.isfinite(candidate) or not minimum <= candidate <= maximum:
        raise NativeQaError(f"{label} must be between {minimum} and {maximum}")
    return candidate


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


def _receipt_digest(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


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
    return _secure_confined_regular_file(
        artifact_root,
        candidate,
        label=label,
        minimum_bytes=1,
        maximum_bytes=maximum,
    )


def normalize_movie_output_path(
    artifact_root: Path,
    output: Path,
) -> tuple[Path, str]:
    return confined_output_file(
        artifact_root,
        output,
        label="Godot movie evidence",
        required_suffix=".avi",
    )


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
    if not isinstance(evidence, MovieEvidence):
        raise NativeQaError("evidence must be validated MovieEvidence")
    journey = _bounded_text(journey_id, label="journey_id", maximum=255)
    if _TOKEN.fullmatch(journey) is None:
        raise NativeQaError("journey_id must be a bounded stable token")
    for value, label in (
        (source_identity, "source_identity"),
        (command_sha256, "command_sha256"),
        (evidence.sha256, "evidence.sha256"),
    ):
        if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
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
    capture_elapsed_seconds = (completed - started).total_seconds()
    _bounded_number(
        capture_elapsed_seconds,
        label="capture_elapsed_seconds",
        minimum=0.0,
        maximum=24 * 60 * 60,
    )
    partial: dict[str, Any] = {
        "schema": "evavo.godot-movie-adapter-receipt.v1",
        "adapterId": "godot-game-test-lab.video-evidence",
        "sourceIdentity": source_identity,
        "issuedAt": completed.isoformat(),
        "expiresAt": (completed + _RECEIPT_LIFETIME).isoformat(),
        "capturedAt": completed.isoformat(),
        "status": "worker-admitted" if worker_admitted else "locally-verified",
        "ready": True,
        "workerAdmitted": worker_admitted,
        "journeyId": journey,
        "commandSha256": command_sha256,
        "movieRelativePath": evidence.relative_path,
        "movieSha256": evidence.sha256,
        "movieBytes": evidence.size_bytes,
        "videoSha256": evidence.sha256,
        "videoBytes": evidence.size_bytes,
        "evidenceSha256": evidence.sha256,
        "container": evidence.container,
        "mediaType": evidence.container,
        "captureElapsedSeconds": capture_elapsed_seconds,
        "framesPerSecond": fps,
        "startedAt": started.isoformat(),
        "completedAt": completed.isoformat(),
        "capabilities": sorted(_REQUIRED_CAPABILITIES),
        "headless": False,
        "arbitraryShellAccepted": False,
        "sourceMutationPerformed": False,
        "truthBoundary": (
            "This receipt proves that a non-headless Godot Movie Maker invocation produced "
            "digest-bound AVI bytes for one journey command. Capture elapsed time is wall-clock "
            "runtime, not asserted playback duration. It does not prove that every frame was "
            "visually correct, that audio was captured, or that a reviewer inspected the movie."
        ),
    }
    return {**partial, "receiptDigest": _receipt_digest(partial)}


def verify_movie_adapter_receipt(
    receipt: Any,
    *,
    now: datetime | None = None,
    expected_source_identity: str | None = None,
) -> bool:
    try:
        if not isinstance(receipt, dict):
            return False
        if set(receipt) != _RECEIPT_KEYS:
            return False
        expected = receipt.get("receiptDigest")
        if not isinstance(expected, str) or _SHA256.fullmatch(expected) is None:
            return False
        partial = dict(receipt)
        partial.pop("receiptDigest", None)
        if _receipt_digest(partial) != expected:
            return False
        if receipt.get("schema") != "evavo.godot-movie-adapter-receipt.v1":
            return False
        if receipt.get("adapterId") != "godot-game-test-lab.video-evidence":
            return False
        if receipt.get("ready") is not True:
            return False
        if not isinstance(receipt.get("workerAdmitted"), bool):
            return False
        expected_status = "worker-admitted" if receipt["workerAdmitted"] else "locally-verified"
        if receipt.get("status") != expected_status:
            return False
        if receipt.get("headless") is not False:
            return False
        if receipt.get("arbitraryShellAccepted") is not False:
            return False
        if receipt.get("sourceMutationPerformed") is not False:
            return False
        if receipt.get("container") != "video/x-msvideo":
            return False
        if receipt.get("mediaType") != receipt.get("container"):
            return False
        for field in (
            "sourceIdentity",
            "commandSha256",
            "movieSha256",
            "videoSha256",
            "evidenceSha256",
        ):
            value = receipt.get(field)
            if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
                return False
        if expected_source_identity is not None:
            if _SHA256.fullmatch(expected_source_identity) is None:
                return False
            if receipt.get("sourceIdentity") != expected_source_identity:
                return False
        if not (
            receipt.get("movieSha256")
            == receipt.get("videoSha256")
            == receipt.get("evidenceSha256")
        ):
            return False
        movie_bytes = _bounded_integer(
            receipt.get("movieBytes"),
            label="movieBytes",
            minimum=_MIN_AVI_BYTES,
            maximum=_DEFAULT_MAX_MOVIE_BYTES,
        )
        if receipt.get("videoBytes") != movie_bytes:
            return False
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
        issued = _timestamp(receipt.get("issuedAt"), label="issuedAt")
        captured = _timestamp(receipt.get("capturedAt"), label="capturedAt")
        expires = _timestamp(receipt.get("expiresAt"), label="expiresAt")
        if completed < started or issued != completed or captured != completed:
            return False
        if expires <= issued or expires - issued > _RECEIPT_LIFETIME:
            return False
        current = (now or datetime.now(UTC)).astimezone(UTC)
        if issued > current + _MAX_FUTURE_SKEW or expires <= current:
            return False
        elapsed = _bounded_number(
            receipt.get("captureElapsedSeconds"),
            label="captureElapsedSeconds",
            minimum=0.0,
            maximum=24 * 60 * 60,
        )
        if elapsed != (completed - started).total_seconds():
            return False
        capabilities = receipt.get("capabilities")
        if not isinstance(capabilities, list) or len(capabilities) != len(set(capabilities)):
            return False
        if set(capabilities) != _REQUIRED_CAPABILITIES:
            return False
        return True
    except (NativeQaError, OSError, TypeError, ValueError):
        return False
