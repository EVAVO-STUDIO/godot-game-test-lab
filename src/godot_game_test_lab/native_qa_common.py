from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import subprocess
import tarfile
import time
from collections.abc import Iterable, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_VERSION_RE = re.compile(r"^4\.[0-9]+\.[0-9]+$")
_RENDERING_METHODS = {"forward_plus", "gl_compatibility", "mobile"}
_RENDERING_DRIVERS = {"d3d12", "opengl3", "vulkan"}
_ERROR_MARKERS = (
    "ERROR:",
    "SCRIPT ERROR:",
    "Parse Error",
    "Build FAILED",
    "Unhandled exception",
    "Failed to load script",
    "Cannot open file",
    "ASSERTION FAILED",
)
_WORKER_ARGUMENT_PREFIXES = (
    "--audio-driver",
    "--display-driver",
    "--fixed-fps",
    "--gpu-index",
    "--headless",
    "--path",
    "--position",
    "--quit-after",
    "--rendering-driver",
    "--rendering-method",
    "--resolution",
    "--scene",
    "--script",
    "--windowed",
    "--write-movie",
)
_MAX_ARCHIVE_FILES = 500_000
_MAX_ARCHIVE_BYTES = 64 * 1024 * 1024 * 1024
_MAX_OUTPUT_BYTES = 16 * 1024 * 1024


class NativeQaError(ValueError):
    pass


def _reject_duplicate_keys(pairs: Iterable[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise NativeQaError(f"Duplicate JSON key is not allowed: {key!r}")
        result[key] = value
    return result


def _reject_non_finite(value: str) -> None:
    raise NativeQaError(f"Non-finite JSON number is not allowed: {value}")


def _load_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite,
        )
    except NativeQaError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise NativeQaError(f"Could not read {label} {path}: {error}") from error
    if not isinstance(value, dict):
        raise NativeQaError(f"{label} root must be an object")
    return value


def _canonical_json(value: object) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_relative_path(value: str, label: str) -> Path:
    text = value.strip().replace("\\", "/")
    pure = PurePosixPath(text)
    if (
        not text
        or pure.is_absolute()
        or ":" in text
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        if text == ".":
            return Path(".")
        raise NativeQaError(f"{label} must be a bounded relative path without traversal")
    if len(text.encode("utf-8")) > 512:
        raise NativeQaError(f"{label} is too long")
    return Path(*pure.parts)


def _resolve_child(root: Path, relative: Path, label: str, *, must_exist: bool = True) -> Path:
    candidate = root / relative
    try:
        resolved = candidate.resolve(strict=must_exist)
        resolved.relative_to(root)
    except (FileNotFoundError, OSError, ValueError) as error:
        raise NativeQaError(f"{label} must remain beneath {root}: {relative}") from error
    return resolved


def _is_within(candidate: Path, parent: Path) -> bool:
    try:
        candidate.relative_to(parent)
        return True
    except ValueError:
        return False


def _git_text(root: Path, arguments: Sequence[str], timeout: int = 30) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *arguments],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise NativeQaError(
            f"Git command failed to start or finish: {arguments}: {error}"
        ) from error
    if completed.returncode != 0:
        output = (completed.stderr or completed.stdout).strip()
        raise NativeQaError(f"Git command failed: {' '.join(arguments)}: {output}")
    return completed.stdout.strip()


def _validate_sha(value: str, label: str) -> str:
    if _SHA_RE.fullmatch(value) is None:
        raise NativeQaError(f"{label} must be an exact lowercase 40-character commit SHA")
    return value


def _validate_exact_checkout(root: Path, expected_sha: str, label: str) -> None:
    observed = _git_text(root, ["rev-parse", "HEAD"])
    if observed != expected_sha:
        raise NativeQaError(f"{label} HEAD {observed} does not match {expected_sha}")


def _require_tracked_file(git_root: Path, path: Path, label: str) -> str:
    try:
        relative = path.relative_to(git_root).as_posix()
    except ValueError as error:
        raise NativeQaError(f"{label} must remain inside the target repository") from error
    _git_text(git_root, ["ls-files", "--error-unmatch", "--", relative])
    return relative


def _terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
            check=False,
        )
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=3)
    except (OSError, subprocess.TimeoutExpired):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            process.kill()


def _bounded_text(data: bytes) -> str:
    if len(data) <= _MAX_OUTPUT_BYTES:
        return data.decode("utf-8", errors="replace")
    half = _MAX_OUTPUT_BYTES // 2
    omitted = len(data) - _MAX_OUTPUT_BYTES
    return (
        data[:half].decode("utf-8", errors="replace")
        + f"\n[godot-lab output truncated: {omitted} byte(s) omitted]\n"
        + data[-half:].decode("utf-8", errors="replace")
    )


def _run_process(
    command: Sequence[str],
    cwd: Path,
    timeout: int,
    *,
    environment: dict[str, str] | None = None,
) -> dict[str, Any]:
    values = [str(value) for value in command]
    started = time.monotonic()
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    try:
        process = subprocess.Popen(
            values,
            cwd=cwd,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=creationflags,
            start_new_session=os.name != "nt",
        )
    except OSError as error:
        return {
            "command": values,
            "exitCode": None,
            "durationSeconds": round(time.monotonic() - started, 3),
            "stdout": "",
            "stderr": f"Unable to start process: {type(error).__name__}: {error}",
            "timedOut": False,
        }
    timed_out = False
    try:
        stdout, stderr = process.communicate(timeout=max(1, timeout))
    except subprocess.TimeoutExpired:
        timed_out = True
        _terminate_process_tree(process)
        try:
            stdout, stderr = process.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            stdout, stderr = b"", b"Process did not exit after termination."
    return {
        "command": values,
        "exitCode": None if timed_out else process.returncode,
        "durationSeconds": round(time.monotonic() - started, 3),
        "stdout": _bounded_text(stdout),
        "stderr": _bounded_text(stderr),
        "timedOut": timed_out,
    }


def _process_findings(result: dict[str, Any], label: str) -> list[str]:
    findings: list[str] = []
    if result.get("timedOut") is True:
        findings.append(f"{label} exceeded its bounded timeout")
    elif result.get("exitCode") != 0:
        findings.append(f"{label} exited with code {result.get('exitCode')}")
    combined = f"{result.get('stdout', '')}\n{result.get('stderr', '')}".casefold()
    for marker in _ERROR_MARKERS:
        if marker.casefold() in combined:
            findings.append(f"{label} output contains error marker: {marker}")
    return sorted(set(findings))


def _write_process_evidence(
    result: dict[str, Any], artifacts: Path, stem: str
) -> list[str]:
    logs = artifacts / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    stdout_path = logs / f"{stem}.stdout.log"
    stderr_path = logs / f"{stem}.stderr.log"
    stdout_path.write_text(str(result.get("stdout", "")), encoding="utf-8")
    stderr_path.write_text(str(result.get("stderr", "")), encoding="utf-8")
    return [
        stdout_path.relative_to(artifacts).as_posix(),
        stderr_path.relative_to(artifacts).as_posix(),
    ]


def _archive_checkout(git_root: Path, sha: str, destination: Path, timeout: int) -> None:
    archive = destination.parent / "target-source.tar"
    destination.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    with archive.open("wb") as output:
        process = subprocess.Popen(
            ["git", "-C", str(git_root), "archive", "--format=tar", sha],
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.PIPE,
            start_new_session=os.name != "nt",
            creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0),
        )
        try:
            _, stderr = process.communicate(timeout=max(1, timeout))
        except subprocess.TimeoutExpired as error:
            _terminate_process_tree(process)
            raise NativeQaError("git archive exceeded its bounded timeout") from error
    if process.returncode != 0:
        raise NativeQaError(
            "git archive failed: " + _bounded_text(stderr).strip()
        )
    if time.monotonic() - started > timeout:
        raise NativeQaError("git archive exceeded its bounded timeout")

    file_count = 0
    total_bytes = 0
    try:
        with tarfile.open(archive, mode="r:") as handle:
            members = handle.getmembers()
            for member in members:
                file_count += 1
                total_bytes += max(0, member.size)
                pure = PurePosixPath(member.name)
                if (
                    file_count > _MAX_ARCHIVE_FILES
                    or total_bytes > _MAX_ARCHIVE_BYTES
                    or pure.is_absolute()
                    or any(part in {"", ".", ".."} for part in pure.parts)
                    or member.issym()
                    or member.islnk()
                    or member.isdev()
                ):
                    raise NativeQaError(
                        f"Target archive contains an unsafe or unbounded member: {member.name}"
                    )
                target = destination.joinpath(*pure.parts)
                resolved_parent = target.parent.resolve(strict=False)
                if not _is_within(resolved_parent, destination):
                    raise NativeQaError(
                        "Target archive member escapes extraction root: " + member.name
                    )
            handle.extractall(destination, filter="data")
    finally:
        archive.unlink(missing_ok=True)
