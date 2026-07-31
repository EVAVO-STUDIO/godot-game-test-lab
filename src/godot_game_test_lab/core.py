from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import threading
import time
from collections.abc import Iterator, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path

_VERSION_RE = re.compile(r"(?P<major>\d+)\.(?P<minor>\d+)(?:\.(?P<patch>\d+))?")
_ERROR_MARKERS = ("ERROR:", "SCRIPT ERROR:", "Parse Error", "Build FAILED", "Unhandled exception")
_DISCOVERY_IGNORED_DIRECTORIES = {
    ".git",
    ".godot",
    ".idea",
    ".mono",
    ".pytest_cache",
    ".qa",
    ".ruff_cache",
    ".vs",
    ".vscode",
    "artifacts",
    "bin",
    "node_modules",
    "obj",
    "reports",
    "test-results",
}
_MAX_DISCOVERY_ENTRIES = 500_000
_MAX_CAPTURE_BYTES = 16 * 1024 * 1024


@dataclass(slots=True)
class CommandResult:
    command: list[str]
    exit_code: int | None
    duration_seconds: float
    stdout: str
    stderr: str
    timed_out: bool = False


@dataclass(slots=True)
class ProjectInventory:
    project_root: str
    project_file: str
    project_name: str | None
    configured_main_scene: str | None
    scenes: list[str]
    gdscript_files: list[str]
    csharp_projects: list[str]
    addons: list[str]


@dataclass(slots=True)
class QaReport:
    schema_version: str
    status: str
    project: ProjectInventory
    godot_executable: str | None
    godot_version: str | None
    findings: list[str] = field(default_factory=list)
    commands: list[CommandResult] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, ensure_ascii=False)


def _regular_project_file(path: Path) -> bool:
    try:
        return path.is_file() and not path.is_symlink()
    except OSError:
        return False


def find_project_root(candidate: Path) -> Path:
    requested = candidate.expanduser()
    try:
        resolved = requested.resolve(strict=True)
    except FileNotFoundError as error:
        raise FileNotFoundError(f"Godot project path does not exist: {requested}") from error
    except OSError as error:
        raise OSError(f"Godot project path could not be resolved: {requested}") from error

    if resolved.is_file():
        if resolved.name != "project.godot":
            raise ValueError(f"Expected project.godot, received file: {resolved}")
        return resolved.parent
    if not resolved.is_dir():
        raise ValueError(f"Godot project candidate is not a directory: {resolved}")

    direct = resolved / "project.godot"
    if _regular_project_file(direct):
        return resolved

    matches: list[Path] = []
    inspected_entries = 0
    for current, directory_names, file_names in os.walk(resolved, topdown=True, followlinks=False):
        directory_names[:] = sorted(
            name
            for name in directory_names
            if name not in _DISCOVERY_IGNORED_DIRECTORIES
            and not (Path(current) / name).is_symlink()
        )
        file_names.sort()
        inspected_entries += len(directory_names) + len(file_names)
        if inspected_entries > _MAX_DISCOVERY_ENTRIES:
            raise ValueError(
                "Godot project discovery exceeded the bounded filesystem entry limit; "
                "specify the exact project directory."
            )
        if "project.godot" not in file_names:
            continue
        project_file = Path(current) / "project.godot"
        if _regular_project_file(project_file):
            matches.append(project_file)
            if len(matches) > 8:
                break

    if not matches:
        raise FileNotFoundError(f"No project.godot found beneath: {resolved}")
    if len(matches) > 1:
        rendered = ", ".join(str(path.parent) for path in matches[:8])
        suffix = ", …" if len(matches) > 8 else ""
        raise ValueError(
            f"Multiple Godot projects found; specify one project root: {rendered}{suffix}"
        )
    return matches[0].parent


def _project_setting(text: str, key: str) -> str | None:
    match = re.search(
        rf'^{re.escape(key)}\s*=\s*"(?P<value>(?:\\.|[^"\\])*)"\s*$',
        text,
        flags=re.MULTILINE,
    )
    if match is None:
        return None
    try:
        value = json.loads(f'"{match.group("value")}"')
    except json.JSONDecodeError:
        return match.group("value")
    return value if isinstance(value, str) else None


def _iter_project_files(root: Path) -> Iterator[Path]:
    stack = [root]
    inspected_entries = 0
    while stack:
        current = stack.pop()
        try:
            entries = sorted(os.scandir(current), key=lambda entry: entry.name.casefold())
        except OSError as error:
            raise OSError(f"Unable to inspect project directory: {current}") from error
        inspected_entries += len(entries)
        if inspected_entries > _MAX_DISCOVERY_ENTRIES:
            raise ValueError("Project inventory exceeded the bounded filesystem entry limit.")
        for entry in reversed(entries):
            path = Path(entry.path)
            try:
                if entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    if entry.name not in _DISCOVERY_IGNORED_DIRECTORIES:
                        stack.append(path)
                elif entry.is_file(follow_symlinks=False):
                    yield path
            except OSError:
                continue


def inspect_project(candidate: Path) -> ProjectInventory:
    root = find_project_root(candidate)
    project_file = root / "project.godot"
    try:
        text = project_file.read_text(encoding="utf-8-sig", errors="strict")
    except UnicodeDecodeError as error:
        raise ValueError(f"project.godot is not valid UTF-8: {project_file}") from error

    scenes: list[str] = []
    gdscript_files: list[str] = []
    csharp_projects: list[str] = []
    for path in _iter_project_files(root):
        suffix = path.suffix.casefold()
        relative = path.relative_to(root).as_posix()
        if suffix in {".escn", ".scn", ".tscn"}:
            scenes.append(relative)
        elif suffix == ".gd":
            gdscript_files.append(relative)
        elif suffix == ".csproj":
            csharp_projects.append(relative)

    addons_root = root / "addons"
    addons: list[str] = []
    if addons_root.is_dir() and not addons_root.is_symlink():
        try:
            addons = sorted(
                entry.name
                for entry in os.scandir(addons_root)
                if entry.is_dir(follow_symlinks=False) and not entry.is_symlink()
            )
        except OSError:
            addons = []

    return ProjectInventory(
        project_root=str(root),
        project_file=str(project_file),
        project_name=_project_setting(text, "config/name"),
        configured_main_scene=_project_setting(text, "run/main_scene"),
        scenes=sorted(scenes),
        gdscript_files=sorted(gdscript_files),
        csharp_projects=sorted(csharp_projects),
        addons=addons,
    )


def discover_godot(explicit: Path | None = None) -> Path | None:
    candidates: list[Path] = []
    if explicit:
        candidates.append(explicit.expanduser())
    env_path = os.environ.get("GODOT_BIN")
    if env_path:
        candidates.append(Path(env_path).expanduser())
    for executable_name in ("godot4", "godot", "Godot_v4.6.2-stable_win64_console.exe"):
        resolved = shutil.which(executable_name)
        if resolved:
            candidates.append(Path(resolved))
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        programs = Path(local_app_data) / "Programs"
        if programs.is_dir():
            candidates.extend(programs.glob("Godot*/Godot*_console.exe"))
            candidates.extend(programs.glob("Godot*/Godot*.exe"))
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved.is_file():
            return resolved
    return None


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


class _BoundedCollector:
    def __init__(self, stream, maximum_bytes: int = _MAX_CAPTURE_BYTES) -> None:
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
        payload = bytes(self.head + self.tail)
        if self.total_bytes > self.maximum_bytes:
            omitted = self.total_bytes - self.maximum_bytes
            payload = (
                bytes(self.head)
                + f"\n[godot-lab output truncated: {omitted} byte(s) omitted]\n".encode()
                + bytes(self.tail)
            )
        return payload.decode("utf-8", errors="replace")


def run_command(command: Sequence[str], cwd: Path, timeout_seconds: int) -> CommandResult:
    values = [str(part) for part in command]
    if not values or not values[0]:
        raise ValueError("command must contain an executable")
    if (
        not isinstance(timeout_seconds, int)
        or isinstance(timeout_seconds, bool)
        or timeout_seconds < 1
    ):
        raise ValueError("timeout_seconds must be a positive integer")
    working_directory = cwd.expanduser().resolve()
    if not working_directory.is_dir():
        raise FileNotFoundError(f"Command working directory does not exist: {working_directory}")

    started = time.monotonic()
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    try:
        process = subprocess.Popen(
            values,
            cwd=working_directory,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=creationflags,
            start_new_session=os.name != "nt",
        )
    except OSError as error:
        return CommandResult(
            command=values,
            exit_code=None,
            duration_seconds=round(time.monotonic() - started, 3),
            stdout="",
            stderr=f"Unable to start process: {type(error).__name__}: {error}",
        )

    if process.stdout is None or process.stderr is None:
        _terminate_process_tree(process)
        raise RuntimeError("Process output pipes were not created")
    stdout_collector = _BoundedCollector(process.stdout)
    stderr_collector = _BoundedCollector(process.stderr)
    stdout_collector.start()
    stderr_collector.start()

    timed_out = False
    try:
        process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        _terminate_process_tree(process)
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            pass

    stdout = stdout_collector.finish()
    stderr = stderr_collector.finish()
    return CommandResult(
        command=values,
        exit_code=None if timed_out else process.returncode,
        duration_seconds=round(time.monotonic() - started, 3),
        stdout=stdout,
        stderr=stderr,
        timed_out=timed_out,
    )
