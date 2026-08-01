from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
import signal
import subprocess
import tarfile
import threading
import time
import unicodedata
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO

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
_MAX_JSON_BYTES = 4 * 1024 * 1024
_MAX_DIRECTORY_ENTRIES = 750_000
_DESKTOP_MUTEX_NAME = "Local\\EVAVO.GodotGameTestLab.NativeDesktop"
_WINDOWS_RESERVED_NAMES = {
    "aux",
    "clock$",
    "com1",
    "com2",
    "com3",
    "com4",
    "com5",
    "com6",
    "com7",
    "com8",
    "com9",
    "con",
    "lpt1",
    "lpt2",
    "lpt3",
    "lpt4",
    "lpt5",
    "lpt6",
    "lpt7",
    "lpt8",
    "lpt9",
    "nul",
    "prn",
}


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


def _load_json_object(
    path: Path,
    label: str,
    *,
    maximum_bytes: int = _MAX_JSON_BYTES,
) -> dict[str, Any]:
    try:
        requested = path.expanduser()
        if requested.is_symlink():
            raise NativeQaError(f"{label} may not be a symbolic link: {path}")
        resolved = requested.resolve(strict=True)
        if not resolved.is_file():
            raise NativeQaError(f"{label} must be a regular file: {path}")
        size = resolved.stat().st_size
        if size > maximum_bytes:
            raise NativeQaError(
                f"{label} exceeds the bounded JSON size limit of {maximum_bytes} bytes"
            )
        value = json.loads(
            resolved.read_text(encoding="utf-8"),
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


def _read_bounded_text(path: Path, maximum_bytes: int = _MAX_OUTPUT_BYTES) -> str:
    if maximum_bytes < 1024:
        raise NativeQaError("maximum text evidence size must be at least 1024 bytes")
    try:
        if path.is_symlink() or not path.is_file():
            raise NativeQaError(f"text evidence must be a regular file: {path}")
        size = path.stat().st_size
        with path.open("rb") as handle:
            if size <= maximum_bytes:
                payload = handle.read(maximum_bytes + 1)
            else:
                head = maximum_bytes // 2
                tail = maximum_bytes - head
                first = handle.read(head)
                handle.seek(max(0, size - tail))
                last = handle.read(tail)
                omitted = max(0, size - len(first) - len(last))
                payload = (
                    first
                    + f"\n[godot-lab evidence truncated: {omitted} byte(s) omitted]\n".encode()
                    + last
                )
    except NativeQaError:
        raise
    except OSError as error:
        raise NativeQaError(f"Could not read bounded text evidence {path}: {error}") from error
    return payload.decode("utf-8", errors="replace")


def _safe_relative_path(value: str, label: str) -> Path:
    text = value.strip().replace("\\", "/")
    if text == ".":
        return Path(".")
    pure = PurePosixPath(text)
    if (
        not text
        or pure.is_absolute()
        or ":" in text
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise NativeQaError(f"{label} must be a bounded relative path without traversal")
    if len(text.encode("utf-8")) > 512:
        raise NativeQaError(f"{label} is too long")
    return Path(*pure.parts)


def _resolve_child(root: Path, relative: Path, label: str, *, must_exist: bool = True) -> Path:
    candidate = root / relative
    try:
        resolved_root = root.resolve(strict=True)
        resolved = candidate.resolve(strict=must_exist)
        resolved.relative_to(resolved_root)
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
    resolved = root.expanduser().resolve(strict=True)
    top_level = Path(_git_text(resolved, ["rev-parse", "--show-toplevel"])).resolve()
    if top_level != resolved:
        raise NativeQaError(f"{label} path must be the Git repository root: {resolved}")
    observed = _git_text(resolved, ["rev-parse", "HEAD"])
    if observed != expected_sha:
        raise NativeQaError(f"{label} HEAD {observed} does not match {expected_sha}")


def _require_clean_checkout(root: Path, label: str) -> None:
    status = _git_text(root, ["status", "--porcelain=v1", "--untracked-files=all"])
    if status:
        lines = status.splitlines()
        sample = "; ".join(lines[:12])
        suffix = "; …" if len(lines) > 12 else ""
        raise NativeQaError(
            f"{label} must be clean so the exact SHA matches executed source: {sample}{suffix}"
        )
    staged = _git_text(root, ["ls-files", "--stage"])
    gitlinks = [line for line in staged.splitlines() if line.startswith("160000 ")]
    if gitlinks:
        paths = [line.split("\t", 1)[1] for line in gitlinks[:12] if "\t" in line]
        suffix = ", …" if len(gitlinks) > 12 else ""
        raise NativeQaError(
            "Exact native QA does not yet materialize Git submodules; "
            f"remove or separately materialize gitlinks: {', '.join(paths)}{suffix}"
        )


def _require_tracked_file(git_root: Path, path: Path, label: str) -> str:
    try:
        relative = path.relative_to(git_root).as_posix()
    except ValueError as error:
        raise NativeQaError(f"{label} must remain inside the target repository") from error
    _git_text(git_root, ["ls-files", "--error-unmatch", "--", relative])
    return relative


class _BoundedCollector:
    def __init__(self, stream: BinaryIO, maximum_bytes: int) -> None:
        self.stream = stream
        self.maximum_bytes = maximum_bytes
        self.head_limit = maximum_bytes // 2
        self.tail_limit = maximum_bytes - self.head_limit
        self.head = bytearray()
        self.tail = bytearray()
        self.total_bytes = 0
        self.thread = threading.Thread(target=self._drain, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def _drain(self) -> None:
        try:
            while True:
                chunk = self.stream.read(64 * 1024)
                if not chunk:
                    return
                self.total_bytes += len(chunk)
                if len(self.head) < self.head_limit:
                    available = self.head_limit - len(self.head)
                    self.head.extend(chunk[:available])
                    chunk = chunk[available:]
                if chunk:
                    self.tail.extend(chunk)
                    overflow = len(self.tail) - self.tail_limit
                    if overflow > 0:
                        del self.tail[:overflow]
        except (OSError, ValueError):
            return

    def finish(self) -> str:
        self.thread.join(timeout=15)
        if self.thread.is_alive():
            try:
                self.stream.close()
            except OSError:
                pass
            self.thread.join(timeout=2)
        if self.total_bytes <= self.maximum_bytes:
            payload = bytes(self.head + self.tail)
        else:
            omitted = self.total_bytes - self.maximum_bytes
            payload = (
                bytes(self.head)
                + f"\n[godot-lab output truncated: {omitted} byte(s) omitted]\n".encode()
                + bytes(self.tail)
            )
        return payload.decode("utf-8", errors="replace")


def _terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
        if process.poll() is None:
            try:
                process.kill()
            except OSError:
                pass
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except OSError:
        try:
            process.terminate()
        except OSError:
            return
    try:
        process.wait(timeout=3)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except OSError:
        try:
            process.kill()
        except OSError:
            pass


def _directory_usage(root: Path) -> tuple[int, int, bool]:
    if not root.exists():
        return (0, 0, True)
    total_bytes = 0
    files = 0
    inspected = 0
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    inspected += 1
                    if inspected > _MAX_DIRECTORY_ENTRIES:
                        return (total_bytes, files, False)
                    try:
                        if entry.is_symlink():
                            return (total_bytes, files, False)
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            files += 1
                            total_bytes += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        return (total_bytes, files, False)
        except OSError:
            return (total_bytes, files, False)
    return (total_bytes, files, True)


def _run_process(
    command: Sequence[str],
    cwd: Path,
    timeout: int,
    *,
    environment: dict[str, str] | None = None,
    maximum_output_bytes: int = _MAX_OUTPUT_BYTES,
    artifact_budget_root: Path | None = None,
    maximum_artifact_bytes: int | None = None,
) -> dict[str, Any]:
    values = [str(value) for value in command]
    if not values or not values[0]:
        raise NativeQaError("process command must contain an executable")
    if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout < 1:
        raise NativeQaError("process timeout must be a positive integer")
    if maximum_output_bytes < 1024:
        raise NativeQaError("maximum_output_bytes must be at least 1024")
    working = cwd.expanduser().resolve(strict=True)
    if not working.is_dir():
        raise NativeQaError(f"process working directory is not a directory: {working}")
    budget_root = (
        artifact_budget_root.expanduser().resolve(strict=False)
        if artifact_budget_root is not None
        else None
    )
    if maximum_artifact_bytes is not None and maximum_artifact_bytes < 1:
        raise NativeQaError("maximum_artifact_bytes must be positive")

    started = time.monotonic()
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    try:
        process = subprocess.Popen(
            values,
            cwd=working,
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
            "artifactBudgetExceeded": False,
        }
    if process.stdout is None or process.stderr is None:
        _terminate_process_tree(process)
        raise NativeQaError("process output pipes were not created")

    stdout_collector = _BoundedCollector(process.stdout, maximum_output_bytes)
    stderr_collector = _BoundedCollector(process.stderr, maximum_output_bytes)
    stdout_collector.start()
    stderr_collector.start()

    timed_out = False
    artifact_budget_exceeded = False
    next_budget_check = time.monotonic()
    while process.poll() is None:
        now = time.monotonic()
        if now - started >= timeout:
            timed_out = True
            _terminate_process_tree(process)
            break
        if (
            budget_root is not None
            and maximum_artifact_bytes is not None
            and now >= next_budget_check
        ):
            used, _files, complete = _directory_usage(budget_root)
            if not complete or used > maximum_artifact_bytes:
                artifact_budget_exceeded = True
                _terminate_process_tree(process)
                break
            next_budget_check = now + 1.0
        time.sleep(0.05)

    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        _terminate_process_tree(process)

    stdout = stdout_collector.finish()
    stderr = stderr_collector.finish()
    if artifact_budget_exceeded:
        stderr += "\nGodot Lab terminated the process because its artifact budget was exceeded.\n"
    return {
        "command": values,
        "exitCode": None if timed_out or artifact_budget_exceeded else process.returncode,
        "durationSeconds": round(time.monotonic() - started, 3),
        "stdout": stdout,
        "stderr": stderr,
        "timedOut": timed_out,
        "artifactBudgetExceeded": artifact_budget_exceeded,
    }


def _process_findings(result: dict[str, Any], label: str) -> list[str]:
    findings: list[str] = []
    if result.get("artifactBudgetExceeded") is True:
        findings.append(f"{label} exceeded its bounded artifact budget")
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


def _safe_archive_parts(name: str) -> tuple[str, ...]:
    if "\\" in name:
        raise NativeQaError(f"Target archive member uses a backslash path: {name}")
    pure = PurePosixPath(name)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise NativeQaError(f"Target archive member has an unsafe path: {name}")
    for part in pure.parts:
        invalid = any(ord(character) < 32 or character in '<>:"|?*' for character in part)
        if invalid or part.endswith((" ", ".")):
            raise NativeQaError(f"Target archive member is not Windows-portable: {name}")
        stem = part.split(".", 1)[0].casefold()
        if stem in _WINDOWS_RESERVED_NAMES:
            raise NativeQaError(f"Target archive member uses a Windows reserved name: {name}")
    return pure.parts


def _portable_path_identity(parts: Sequence[str]) -> str:
    return "/".join(unicodedata.normalize("NFC", part).casefold() for part in parts)


def _copy_archive_member(source: BinaryIO, destination: Path, expected_size: int) -> None:
    copied = 0
    with destination.open("xb") as output:
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            copied += len(chunk)
            if copied > expected_size:
                raise NativeQaError(
                    f"Target archive member exceeded its declared size: {destination.name}"
                )
            output.write(chunk)
    if copied != expected_size:
        raise NativeQaError(
            f"Target archive member size changed during extraction: {destination.name}"
        )


def _archive_checkout(git_root: Path, sha: str, destination: Path, timeout: int) -> dict[str, int]:
    destination = destination.expanduser().resolve(strict=False)
    if destination.exists():
        raise NativeQaError(f"archive destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    archive = destination.parent / "target-source.tar"
    destination.mkdir(parents=False, exist_ok=False)
    started = time.monotonic()
    try:
        with archive.open("xb") as output:
            process = subprocess.Popen(
                ["git", "-C", str(git_root), "archive", "--format=tar", sha],
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.PIPE,
                start_new_session=os.name != "nt",
                creationflags=(
                    subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
                ),
            )
            if process.stderr is None:
                _terminate_process_tree(process)
                raise NativeQaError("git archive stderr pipe was not created")
            stderr_collector = _BoundedCollector(process.stderr, _MAX_OUTPUT_BYTES)
            stderr_collector.start()
            timed_out = False
            try:
                process.wait(timeout=max(1, timeout))
            except subprocess.TimeoutExpired:
                timed_out = True
                _terminate_process_tree(process)
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    pass
            stderr = stderr_collector.finish()
        if timed_out:
            raise NativeQaError("git archive exceeded its bounded timeout")
        if process.returncode != 0:
            raise NativeQaError("git archive failed: " + stderr.strip())
        if time.monotonic() - started > timeout:
            raise NativeQaError("git archive exceeded its bounded timeout")

        member_count = 0
        file_count = 0
        total_bytes = 0
        seen: set[str] = set()
        with tarfile.open(archive, mode="r:") as handle:
            for member in handle:
                member_count += 1
                if member_count > _MAX_ARCHIVE_FILES * 2:
                    raise NativeQaError(
                        "Target archive exceeds its bounded member-count limit"
                    )
                parts = _safe_archive_parts(member.name)
                key = _portable_path_identity(parts)
                if key in seen:
                    raise NativeQaError(
                        f"Target archive contains a duplicate case-insensitive path: {member.name}"
                    )
                seen.add(key)
                if member.isdir():
                    target = destination.joinpath(*parts)
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                if not member.isfile():
                    raise NativeQaError(
                        f"Target archive contains a link or special member: {member.name}"
                    )
                file_count += 1
                total_bytes += max(0, member.size)
                if file_count > _MAX_ARCHIVE_FILES or total_bytes > _MAX_ARCHIVE_BYTES:
                    raise NativeQaError(
                        f"Target archive exceeds bounded extraction limits: {member.name}"
                    )
                target = destination.joinpath(*parts)
                resolved_parent = target.parent.resolve(strict=False)
                if not _is_within(resolved_parent, destination):
                    raise NativeQaError(
                        "Target archive member escapes extraction root: " + member.name
                    )
                target.parent.mkdir(parents=True, exist_ok=True)
                source = handle.extractfile(member)
                if source is None:
                    raise NativeQaError(
                        f"Target archive member could not be read: {member.name}"
                    )
                with source:
                    _copy_archive_member(source, target, member.size)
                try:
                    target.chmod(member.mode & 0o777)
                except OSError:
                    pass
        return {
            "members": member_count,
            "files": file_count,
            "bytes": total_bytes,
        }
    except Exception:
        import shutil

        shutil.rmtree(destination, ignore_errors=True)
        raise
    finally:
        archive.unlink(missing_ok=True)


@contextmanager
def _native_desktop_lease(enabled: bool = True) -> Iterator[dict[str, Any]]:
    if not enabled or os.name != "nt":
        yield {"acquired": False, "name": _DESKTOP_MUTEX_NAME}
        return

    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.ReleaseMutex.argtypes = [wintypes.HANDLE]
    kernel32.ReleaseMutex.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.CreateMutexW(None, False, _DESKTOP_MUTEX_NAME)
    if not handle:
        raise NativeQaError(
            f"Could not create native desktop lease: Windows error {ctypes.get_last_error()}"
        )
    wait_result = kernel32.WaitForSingleObject(handle, 0)
    wait_object_0 = 0x00000000
    wait_abandoned = 0x00000080
    try:
        if wait_result not in {wait_object_0, wait_abandoned}:
            raise NativeQaError(
                "Another Godot Lab process already owns the interactive desktop lease"
            )
        yield {
            "acquired": True,
            "abandonedPreviousOwner": wait_result == wait_abandoned,
            "name": _DESKTOP_MUTEX_NAME,
            "ownerPid": os.getpid(),
        }
    finally:
        if wait_result in {wait_object_0, wait_abandoned}:
            kernel32.ReleaseMutex(handle)
        kernel32.CloseHandle(handle)
