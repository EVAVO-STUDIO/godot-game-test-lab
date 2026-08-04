from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import subprocess
import unicodedata
from pathlib import Path, PurePosixPath
from typing import Any

from .audio_analysis_types import (
    HEAD_PATTERN,
    MAXIMUM_JSON_BYTES,
    ORIGIN_PATTERN,
    RESERVED_PATTERN,
    SHA256_PATTERN,
    AudioAnalysisVerificationError,
)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(str(left)) == os.path.normcase(str(right))


def _is_within(candidate: Path, parent: Path) -> bool:
    try:
        candidate.relative_to(parent)
        return True
    except ValueError:
        return False


def _has_reparse_attribute(value: os.stat_result) -> bool:
    attributes = getattr(value, "st_file_attributes", 0)
    marker = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(marker and attributes & marker)


def _reject_link_components(value: Path, label: str) -> Path:
    requested = Path(os.path.abspath(os.fspath(value.expanduser())))
    for component in (requested, *requested.parents):
        try:
            if not component.exists() and not component.is_symlink():
                continue
            info = component.lstat()
        except OSError as error:
            raise AudioAnalysisVerificationError(
                f"Could not inspect {label}: {component}"
            ) from error
        if stat.S_ISLNK(info.st_mode) or _has_reparse_attribute(info):
            raise AudioAnalysisVerificationError(
                f"{label} may not traverse a link or reparse point: {component}"
            )
    return requested


def _canonical_directory(value: Path, label: str) -> Path:
    requested = _reject_link_components(value, label)
    try:
        resolved = requested.resolve(strict=True)
    except OSError as error:
        raise AudioAnalysisVerificationError(
            f"{label} does not exist: {requested}"
        ) from error
    if not resolved.is_dir() or not _same_path(requested, resolved):
        raise AudioAnalysisVerificationError(
            f"{label} must be a canonical non-link directory"
        )
    return resolved


def _stat_signature(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _read_regular(
    value: Path,
    label: str,
    maximum_bytes: int,
    *,
    retain_payload: bool,
) -> tuple[Path, int, str, bytes | None]:
    requested = _reject_link_components(value, label)
    try:
        resolved = requested.resolve(strict=True)
        path_before = requested.lstat()
    except OSError as error:
        raise AudioAnalysisVerificationError(
            f"{label} is unavailable: {requested}"
        ) from error
    if (
        not _same_path(requested, resolved)
        or not stat.S_ISREG(path_before.st_mode)
        or _has_reparse_attribute(path_before)
    ):
        raise AudioAnalysisVerificationError(
            f"{label} must be a canonical regular non-link file"
        )
    if path_before.st_size < 1 or path_before.st_size > maximum_bytes:
        raise AudioAnalysisVerificationError(
            f"{label} has an invalid byte length"
        )

    flags = os.O_RDONLY
    flags |= getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOINHERIT", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(resolved, flags)
    except OSError as error:
        raise AudioAnalysisVerificationError(
            f"{label} could not be opened"
        ) from error

    digest = hashlib.sha256()
    chunks: list[bytes] | None = [] if retain_payload else None
    bytes_read = 0
    try:
        opened_before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened_before.st_mode)
            or _has_reparse_attribute(opened_before)
            or not os.path.samestat(path_before, opened_before)
        ):
            raise AudioAnalysisVerificationError(
                f"{label} changed before it was opened"
            )
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            bytes_read += len(chunk)
            if bytes_read > maximum_bytes:
                raise AudioAnalysisVerificationError(
                    f"{label} exceeds the bounded byte limit"
                )
            digest.update(chunk)
            if chunks is not None:
                chunks.append(chunk)
        opened_after = os.fstat(descriptor)
    except OSError as error:
        raise AudioAnalysisVerificationError(
            f"{label} could not be read"
        ) from error
    finally:
        os.close(descriptor)

    try:
        path_after = requested.lstat()
    except OSError as error:
        raise AudioAnalysisVerificationError(
            f"{label} changed while it was read"
        ) from error
    if (
        not os.path.samestat(opened_before, opened_after)
        or not os.path.samestat(opened_after, path_after)
        or _stat_signature(path_before) != _stat_signature(path_after)
        or _stat_signature(opened_before) != _stat_signature(opened_after)
        or bytes_read != opened_after.st_size
    ):
        raise AudioAnalysisVerificationError(
            f"{label} changed while it was read"
        )
    payload = b"".join(chunks) if chunks is not None else None
    return resolved, bytes_read, digest.hexdigest(), payload


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise AudioAnalysisVerificationError(
                f"duplicate JSON property: {key}"
            )
        result[key] = value
    return result


def _parse_int(source: str) -> int:
    if source == "-0":
        raise AudioAnalysisVerificationError("negative zero is not accepted")
    return int(source)


def _parse_float(source: str) -> float:
    value = float(source)
    if not math.isfinite(value) or (
        value == 0.0 and math.copysign(1.0, value) < 0
    ):
        raise AudioAnalysisVerificationError(
            "non-finite or negative-zero JSON number is not accepted"
        )
    return value


def _reject_constant(source: str) -> None:
    raise AudioAnalysisVerificationError(
        f"non-standard JSON constant is not accepted: {source}"
    )


def _read_json(
    value: Path,
    label: str,
) -> tuple[Path, bytes, dict[str, Any], str]:
    resolved, _, digest, payload = _read_regular(
        value,
        label,
        MAXIMUM_JSON_BYTES,
        retain_payload=True,
    )
    assert payload is not None
    if payload.startswith(b"\xef\xbb\xbf"):
        raise AudioAnalysisVerificationError(f"{label} contains a UTF-8 BOM")
    try:
        text = payload.decode("utf-8", errors="strict")
        document = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_int=_parse_int,
            parse_float=_parse_float,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, json.JSONDecodeError) as error:
        raise AudioAnalysisVerificationError(
            f"{label} is invalid JSON: {error}"
        ) from error
    if not isinstance(document, dict):
        raise AudioAnalysisVerificationError(f"{label} root must be an object")
    return resolved, payload, document, digest


def _portable(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise AudioAnalysisVerificationError(f"{label} is not a portable path")
    normalized = unicodedata.normalize("NFC", value)
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
        raise AudioAnalysisVerificationError(
            f"{label} must be repository relative"
        )
    parts = PurePosixPath(normalized).parts
    if any(
        part in {"", ".", ".."}
        or re.search(r'[<>:"|?*]', part)
        or part.endswith((".", " "))
        or RESERVED_PATTERN.match(part)
        for part in parts
    ):
        raise AudioAnalysisVerificationError(
            f"{label} is not portable: {value}"
        )
    return PurePosixPath(*parts).as_posix()


def _sha_field(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SHA256_PATTERN.fullmatch(value):
        raise AudioAnalysisVerificationError(
            f"{label} must be a lowercase SHA-256"
        )
    return value


def _integer(value: Any, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise AudioAnalysisVerificationError(f"{label} must be an integer")
    return value


def _number(value: Any, label: str, *, allow_none: bool = False) -> float | None:
    if value is None and allow_none:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise AudioAnalysisVerificationError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise AudioAnalysisVerificationError(f"{label} must be finite")
    return result


def _strings(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise AudioAnalysisVerificationError(
            f"{label} must contain non-empty strings"
        )
    if len(value) != len(set(value)):
        raise AudioAnalysisVerificationError(f"{label} contains duplicates")
    return list(value)


def _run(
    command: list[str],
    *,
    binary: bool = False,
    timeout: int = 90,
) -> tuple[Any, Any]:
    try:
        result = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=not binary,
            encoding=None if binary else "utf-8",
            errors=None if binary else "replace",
            timeout=timeout,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise AudioAnalysisVerificationError(
            f"Command failed to start or timed out: {command[0]}"
        ) from error
    if result.returncode:
        diagnostic = (
            result.stderr
            if isinstance(result.stderr, str)
            else result.stderr.decode("utf-8", "replace")
        )
        raise AudioAnalysisVerificationError(
            f"Command failed ({result.returncode}): {command[0]}: {diagnostic[-2000:]}"
        )
    return result.stdout, result.stderr


def _git_text(repository: Path, *arguments: str) -> str:
    output, _ = _run(
        ["git", "-C", str(repository), *arguments],
        timeout=30,
    )
    return str(output).strip()


def _git_status(repository: Path) -> tuple[bytes, str]:
    output, _ = _run(
        [
            "git",
            "-C",
            str(repository),
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
        ],
        binary=True,
        timeout=30,
    )
    payload = bytes(output)
    return payload, _sha256(payload)


def _repository_state(repository: Path) -> dict[str, Any]:
    root = Path(_git_text(repository, "rev-parse", "--show-toplevel")).resolve()
    if not _same_path(root, repository):
        raise AudioAnalysisVerificationError(
            "Repository root must be the exact Git worktree root"
        )
    branch = _git_text(repository, "branch", "--show-current")
    head = _git_text(repository, "rev-parse", "HEAD").lower()
    origin = _git_text(repository, "remote", "get-url", "origin")
    if branch != "main" or not HEAD_PATTERN.fullmatch(head) or not ORIGIN_PATTERN.search(origin):
        raise AudioAnalysisVerificationError(
            "Brass & Brine repository identity is invalid"
        )
    status, status_sha = _git_status(repository)
    return {
        "branch": branch,
        "head": head,
        "origin": origin,
        "status": status,
        "statusSha256": status_sha,
    }
