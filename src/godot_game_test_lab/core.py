from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Sequence

_VERSION_RE = re.compile(r"(?P<major>\d+)\.(?P<minor>\d+)(?:\.(?P<patch>\d+))?")
_ERROR_MARKERS = ("ERROR:", "SCRIPT ERROR:", "Parse Error", "Build FAILED", "Unhandled exception")


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


def find_project_root(candidate: Path) -> Path:
    candidate = candidate.expanduser().resolve()
    if candidate.is_file() and candidate.name == "project.godot":
        return candidate.parent
    direct = candidate / "project.godot"
    if direct.is_file():
        return candidate
    matches = sorted(candidate.rglob("project.godot")) if candidate.is_dir() else []
    if not matches:
        raise FileNotFoundError(f"No project.godot found beneath: {candidate}")
    if len(matches) > 1:
        rendered = ", ".join(str(path.parent) for path in matches[:8])
        raise ValueError(f"Multiple Godot projects found; specify one project root: {rendered}")
    return matches[0].parent


def _project_setting(text: str, key: str) -> str | None:
    match = re.search(rf'^{re.escape(key)}\s*=\s*"(.*)"\s*$', text, flags=re.MULTILINE)
    return match.group(1) if match else None


def inspect_project(candidate: Path) -> ProjectInventory:
    root = find_project_root(candidate)
    project_file = root / "project.godot"
    text = project_file.read_text(encoding="utf-8-sig", errors="replace")

    def relative_files(pattern: str) -> list[str]:
        return [path.relative_to(root).as_posix() for path in sorted(root.rglob(pattern))]

    addons_root = root / "addons"
    addons = []
    if addons_root.is_dir():
        addons = [path.name for path in sorted(addons_root.iterdir()) if path.is_dir()]

    return ProjectInventory(
        project_root=str(root),
        project_file=str(project_file),
        project_name=_project_setting(text, "config/name"),
        configured_main_scene=_project_setting(text, "run/main_scene"),
        scenes=relative_files("*.tscn"),
        gdscript_files=relative_files("*.gd"),
        csharp_projects=relative_files("*.csproj"),
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
        resolved = candidate.resolve()
        if resolved.is_file():
            return resolved
    return None


def run_command(command: Sequence[str], cwd: Path, timeout_seconds: int) -> CommandResult:
    started = time.monotonic()
    try:
        completed = subprocess.run(
            list(command),
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
        return CommandResult(
            command=list(command),
            exit_code=completed.returncode,
            duration_seconds=round(time.monotonic() - started, 3),
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return CommandResult(
            command=list(command),
            exit_code=None,
            duration_seconds=round(time.monotonic() - started, 3),
            stdout=stdout,
            stderr=stderr,
            timed_out=True,
        )


def _detect_version(executable: Path, root: Path) -> tuple[str | None, CommandResult]:
    result = run_command([str(executable), "--version"], root, timeout_seconds=30)
    combined = f"{result.stdout}\n{result.stderr}".strip()
    match = _VERSION_RE.search(combined)
    return (match.group(0) if match else None), result


def validate_project(
    candidate: Path,
    godot_executable: Path | None = None,
    timeout_seconds: int = 180,
) -> QaReport:
    project = inspect_project(candidate)
    root = Path(project.project_root)
    executable = discover_godot(godot_executable)
    findings: list[str] = []
    commands: list[CommandResult] = []

    if not project.configured_main_scene:
        findings.append("Project has no run/main_scene configured.")
    if not project.scenes:
        findings.append("Project contains no .tscn scene files.")
    if executable is None:
        findings.append("Godot executable was not found. Set GODOT_BIN or pass --godot.")
        return QaReport("1.0", "blocked", project, None, None, findings, commands)

    version, version_result = _detect_version(executable, root)
    commands.append(version_result)
    validation = run_command(
        [str(executable), "--headless", "--path", str(root), "--editor", "--quit"],
        root,
        timeout_seconds,
    )
    commands.append(validation)
    combined_output = f"{validation.stdout}\n{validation.stderr}"
    for marker in _ERROR_MARKERS:
        if marker.lower() in combined_output.lower():
            findings.append(f"Godot output contains error marker: {marker}")
    if validation.timed_out:
        findings.append(f"Godot validation exceeded {timeout_seconds} seconds.")
    elif validation.exit_code != 0:
        findings.append(f"Godot validation exited with code {validation.exit_code}.")

    status = "passed" if not findings else "failed"
    return QaReport(
        schema_version="1.0",
        status=status,
        project=project,
        godot_executable=str(executable),
        godot_version=version,
        findings=findings,
        commands=commands,
    )
