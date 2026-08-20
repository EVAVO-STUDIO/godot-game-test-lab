from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any

ATTESTATION_CONTRACT = (
    "evavo.godot-game-test-lab.attended-multiplayer-operator-attestation.v1"
)
RECEIPT_CONTRACT = "evavo.godot-game-test-lab.attended-multiplayer-receipt.v1"
PRODUCER_REPOSITORY = "EVAVO-STUDIO/godot-game-test-lab"
DESKTOP_LEASE_NAME = "Local\\EVAVO.GodotGameTestLab.NativeDesktop"
ATTESTATION_VALIDITY = timedelta(hours=4, minutes=15)
MAX_ATTESTATION_LAG = timedelta(minutes=30)
MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_ARTIFACT_FILES = 20_000
MAX_ARTIFACT_BYTES = 200 * 1024**3
MAX_DIRECTORY_ENTRIES = 100_000
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")


class AttendedMultiplayerError(ValueError):
    """Raised when attended multiplayer evidence is not admissible."""


def fail(code: str) -> None:
    raise AttendedMultiplayerError(code)


def is_record(value: object) -> bool:
    return isinstance(value, dict)


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def pretty_json(value: object) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_object(value: object) -> str:
    return sha256_bytes(canonical_json(value).encode("utf-8"))


def safe_id(value: object, code: str) -> str:
    if not isinstance(value, str) or SAFE_ID_RE.fullmatch(value) is None:
        fail(code)
    return value


def bounded_line(value: object, code: str, maximum_bytes: int = 256) -> str:
    if (
        not isinstance(value, str)
        or value != value.strip()
        or not value
        or len(value.encode("utf-8")) > maximum_bytes
        or any(character in value for character in ("\x00", "\r", "\n"))
    ):
        fail(code)
    return value


def exact_sha(value: object, code: str) -> str:
    if not isinstance(value, str) or SHA_RE.fullmatch(value) is None:
        fail(code)
    return value


def digest(value: object, code: str) -> str:
    if not isinstance(value, str) or DIGEST_RE.fullmatch(value) is None:
        fail(code)
    return value


def positive_int(value: object, code: str, maximum: int = 2**63 - 1) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 1
        or value > maximum
    ):
        fail(code)
    return value


def nonnegative_int(value: object, code: str, maximum: int = 2**63 - 1) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 0
        or value > maximum
    ):
        fail(code)
    return value


def exact_timestamp(value: object, code: str) -> tuple[str, datetime]:
    if not isinstance(value, str) or not 1 <= len(value) <= 64:
        fail(code)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        fail(code)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        fail(code)
    normalized = parsed.astimezone(UTC)
    if value != normalized.isoformat():
        fail(code)
    return value, normalized


def exact_fields(value: dict[str, Any], expected: set[str], code: str) -> None:
    if set(value) != expected:
        fail(code)


def safe_relative_path(value: object, code: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value.encode("utf-8")) > 1024
        or "\\" in value
        or "\x00" in value
    ):
        fail(code)
    pure = PurePosixPath(value)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        fail(code)
    return pure.as_posix()


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            fail("ATTENDED_MULTIPLAYER_DUPLICATE_JSON_KEY_REJECTED")
        value[key] = item
    return value


def reject_non_finite(value: str) -> None:
    fail("ATTENDED_MULTIPLAYER_NONFINITE_NUMBER_REJECTED")


def absolute_without_resolving(path: Path) -> Path:
    return Path(os.path.abspath(path.expanduser()))


def assert_no_symlink_chain(path: Path) -> Path:
    absolute = absolute_without_resolving(path)
    anchor = Path(absolute.anchor)
    current = anchor
    for part in absolute.parts[1:]:
        current = current / part
        if current.exists() and current.is_symlink():
            fail("ATTENDED_MULTIPLAYER_PATH_SYMLINK_REJECTED")
    return absolute


def load_json_bytes(path: Path, label: str) -> tuple[dict[str, Any], bytes, Path]:
    requested = assert_no_symlink_chain(path)
    resolved = requested.resolve(strict=True)
    if not resolved.is_file() or resolved.is_symlink():
        fail(f"ATTENDED_MULTIPLAYER_{label}_FILE_INVALID")
    size = resolved.stat().st_size
    if not 1 <= size <= MAX_JSON_BYTES:
        fail(f"ATTENDED_MULTIPLAYER_{label}_SIZE_INVALID")
    payload = resolved.read_bytes()
    if payload.startswith(b"\xef\xbb\xbf"):
        fail(f"ATTENDED_MULTIPLAYER_{label}_BOM_REJECTED")
    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_non_finite,
        )
    except (UnicodeError, json.JSONDecodeError):
        fail(f"ATTENDED_MULTIPLAYER_{label}_JSON_INVALID")
    if not isinstance(value, dict):
        fail(f"ATTENDED_MULTIPLAYER_{label}_ROOT_INVALID")
    return value, payload, resolved


def write_json_create_only(path: Path, value: dict[str, Any]) -> Path:
    destination = assert_no_symlink_chain(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.parent.is_symlink() or not destination.parent.is_dir():
        fail("ATTENDED_MULTIPLAYER_OUTPUT_PARENT_INVALID")
    encoded = pretty_json(value).encode("utf-8")
    if len(encoded) > MAX_JSON_BYTES:
        fail("ATTENDED_MULTIPLAYER_OUTPUT_TOO_LARGE")
    try:
        with destination.open("xb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        fail("ATTENDED_MULTIPLAYER_OUTPUT_ALREADY_EXISTS")
    return destination


def inventory_artifacts(root: Path) -> list[dict[str, Any]]:
    candidate = assert_no_symlink_chain(root)
    resolved = candidate.resolve(strict=True)
    if not resolved.is_dir() or resolved.is_symlink():
        fail("ATTENDED_MULTIPLAYER_ARTIFACT_ROOT_INVALID")

    records: list[dict[str, Any]] = []
    total_bytes = 0
    inspected = 0
    stack = [resolved]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as iterator:
                entries = sorted(iterator, key=lambda entry: entry.name.casefold())
        except OSError:
            fail("ATTENDED_MULTIPLAYER_ARTIFACT_SCAN_FAILED")
        for entry in reversed(entries):
            inspected += 1
            if inspected > MAX_DIRECTORY_ENTRIES:
                fail("ATTENDED_MULTIPLAYER_ARTIFACT_ENTRY_LIMIT_EXCEEDED")
            path = Path(entry.path)
            if entry.is_symlink():
                fail("ATTENDED_MULTIPLAYER_ARTIFACT_SYMLINK_REJECTED")
            if entry.is_dir(follow_symlinks=False):
                relative_dir = path.relative_to(resolved).as_posix()
                if relative_dir != "work" and not relative_dir.startswith("work/"):
                    stack.append(path)
                continue
            if not entry.is_file(follow_symlinks=False):
                fail("ATTENDED_MULTIPLAYER_ARTIFACT_SPECIAL_FILE_REJECTED")
            relative = path.relative_to(resolved).as_posix()
            if relative == "multiplayer-agent-summary.json":
                continue
            if len(records) >= MAX_ARTIFACT_FILES:
                fail("ATTENDED_MULTIPLAYER_ARTIFACT_FILE_LIMIT_EXCEEDED")
            size_before = entry.stat(follow_symlinks=False).st_size
            total_bytes += size_before
            if total_bytes > MAX_ARTIFACT_BYTES:
                fail("ATTENDED_MULTIPLAYER_ARTIFACT_BYTE_LIMIT_EXCEEDED")
            file_digest = sha256_file(path)
            size_after = path.stat().st_size
            if size_after != size_before:
                fail("ATTENDED_MULTIPLAYER_ARTIFACT_CHANGED_DURING_HASH")
            records.append(
                {"path": relative, "bytes": size_before, "sha256": file_digest}
            )
    return sorted(records, key=lambda record: str(record["path"]).casefold())


def ensure_output_outside_artifacts(output: Path, artifact_root: Path) -> None:
    output_path = absolute_without_resolving(output)
    root = assert_no_symlink_chain(artifact_root).resolve(strict=True)
    try:
        output_path.relative_to(root)
    except ValueError:
        return
    fail("ATTENDED_MULTIPLAYER_OUTPUT_INSIDE_ARTIFACT_ROOT")
