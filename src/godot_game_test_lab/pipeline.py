from __future__ import annotations

import json
import os
import platform
import re
import shutil
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Sequence

from .core import CommandResult, ProjectInventory, inspect_project, run_command

_VERSION_RE = re.compile(r"(?P<major>\d+)\.(?P<minor>\d+)(?:\.(?P<patch>\d+))?")
_ERROR_MARKERS = (
    "ERROR:",
    "SCRIPT ERROR:",
    "Parse Error",
    "Build FAILED",
    "Unhandled exception",
    "Unhandled Exception",
)


@dataclass(slots=True)
class ToolIdentity:
    id: str
    executable: str | None
    version: str | None
    available: bool
    required: bool
    compatible: bool
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PipelineReport:
    schema_version: str
    run_id: str
    generated_at: str
    status: str
    project: ProjectInventory
    workload: str
    tools: list[ToolIdentity] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)
    commands: list[CommandResult] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)


def _run_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")


def _candidate_path(value: str | None) -> Path | None:
    if not value or not value.strip():
        return None
    path = Path(value.strip()).expanduser()
    try:
        resolved = path.resolve()
    except OSError:
        return None
    return resolved if resolved.is_file() else None


def _which(name: str) -> Path | None:
    resolved = shutil.which(name)
    return Path(resolved).resolve() if resolved else None


def discover_godot_binary(
    explicit: Path | None = None,
    *,
    requires_mono: bool = False,
) -> Path | None:
    candidates: list[Path] = []
    for value in [
        str(explicit) if explicit else None,
        os.environ.get("GODOT_MONO_BIN") if requires_mono else None,
        os.environ.get("GODOT_BIN"),
    ]:
        candidate = _candidate_path(value)
        if candidate:
            candidates.append(candidate)

    executable_names = (
        (
            "Godot_v4.6.2-stable_mono_win64_console.exe",
            "Godot_v4.6.2-stable_mono_win64.exe",
            "godot-mono",
            "godot4-mono",
        )
        if requires_mono
        else (
            "Godot_v4.6.2-stable_win64_console.exe",
            "Godot_v4.6.2-stable_win64.exe",
            "godot4",
            "godot",
        )
    )
    for name in executable_names:
        candidate = _which(name)
        if candidate:
            candidates.append(candidate)

    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        programs = Path(local_app_data) / "Programs"
        if programs.is_dir():
            patterns = (
                ("Godot*mono*/Godot*_console.exe", "Godot*mono*/Godot*.exe")
                if requires_mono
                else ("Godot*/Godot*_console.exe", "Godot*/Godot*.exe")
            )
            for pattern in patterns:
                candidates.extend(sorted(programs.glob(pattern)))

    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved.is_file():
            return resolved
    return None


def discover_dotnet(explicit: Path | None = None) -> Path | None:
    for value in [str(explicit) if explicit else None, os.environ.get("DOTNET_BIN")]:
        candidate = _candidate_path(value)
        if candidate:
            return candidate
    return _which("dotnet")


def _version_from_result(result: CommandResult) -> str | None:
    combined = f"{result.stdout}\n{result.stderr}"
    match = _VERSION_RE.search(combined)
    return match.group(0) if match else None


def _version_tuple(value: str | None) -> tuple[int, int, int] | None:
    if not value:
        return None
    match = _VERSION_RE.search(value)
    if not match:
        return None
    return (
        int(match.group("major")),
        int(match.group("minor")),
        int(match.group("patch") or 0),
    )


def _meets_minimum(actual: str | None, minimum: str) -> bool:
    actual_tuple = _version_tuple(actual)
    minimum_tuple = _version_tuple(minimum)
    return bool(actual_tuple and minimum_tuple and actual_tuple >= minimum_tuple)


def _contains_error_marker(result: CommandResult) -> list[str]:
    combined = f"{result.stdout}\n{result.stderr}".lower()
    return [marker for marker in _ERROR_MARKERS if marker.lower() in combined]


def _command_failed(label: str, result: CommandResult, findings: list[str]) -> None:
    for marker in _contains_error_marker(result):
        findings.append(f"{label} output contains error marker: {marker}")
    if result.timed_out:
        findings.append(f"{label} timed out after {result.duration_seconds} seconds.")
    elif result.exit_code != 0:
        findings.append(f"{label} exited with code {result.exit_code}.")


def validate_project_pipeline(
    candidate: Path,
    *,
    godot_executable: Path | None = None,
    dotnet_executable: Path | None = None,
    minimum_godot_version: str = "4.6.2",
    timeout_seconds: int = 300,
    boot_frames: int = 5,
) -> PipelineReport:
    project = inspect_project(candidate)
    root = Path(project.project_root)
    requires_mono = bool(project.csharp_projects)
    workload = "godot-csharp" if requires_mono else "godot-gdscript"
    findings: list[str] = []
    commands: list[CommandResult] = []
    tools: list[ToolIdentity] = []

    if not project.configured_main_scene:
        findings.append("Project has no run/main_scene configured.")
    if not project.scenes:
        findings.append("Project contains no .tscn scene files.")

    godot = discover_godot_binary(godot_executable, requires_mono=requires_mono)
    godot_version: str | None = None
    godot_notes: list[str] = []
    if godot:
        version_result = run_command([str(godot), "--version"], root, 30)
        commands.append(version_result)
        godot_version = _version_from_result(version_result)
        if version_result.exit_code != 0:
            godot_notes.append("Godot --version failed.")
        if not _meets_minimum(godot_version, minimum_godot_version):
            godot_notes.append(
                f"Godot {godot_version or 'unknown'} does not meet {minimum_godot_version}."
            )
        if requires_mono:
            version_text = f"{version_result.stdout}\n{version_result.stderr}".lower()
            name_text = godot.name.lower()
            if "mono" not in version_text and "mono" not in name_text:
                godot_notes.append("C# project requires a Godot Mono executable.")
    else:
        godot_notes.append(
            "Godot executable was not found. Set GODOT_BIN/GODOT_MONO_BIN or pass --godot."
        )

    tools.append(
        ToolIdentity(
            id="godot-mono" if requires_mono else "godot",
            executable=str(godot) if godot else None,
            version=godot_version,
            available=godot is not None,
            required=True,
            compatible=godot is not None and not godot_notes,
            notes=godot_notes,
        )
    )
    findings.extend(godot_notes)

    dotnet: Path | None = None
    if requires_mono:
        dotnet = discover_dotnet(dotnet_executable)
        dotnet_version: str | None = None
        dotnet_notes: list[str] = []
        if dotnet:
            version_result = run_command([str(dotnet), "--version"], root, 30)
            commands.append(version_result)
            dotnet_version = _version_from_result(version_result)
            if version_result.exit_code != 0:
                dotnet_notes.append("dotnet --version failed.")
        else:
            dotnet_notes.append("dotnet executable was not found. Set DOTNET_BIN or pass --dotnet.")
        tools.append(
            ToolIdentity(
                id="dotnet",
                executable=str(dotnet) if dotnet else None,
                version=dotnet_version,
                available=dotnet is not None,
                required=True,
                compatible=dotnet is not None and not dotnet_notes,
                notes=dotnet_notes,
            )
        )
        findings.extend(dotnet_notes)

    if godot and not godot_notes:
        if requires_mono and dotnet:
            for project_file in project.csharp_projects:
                build = run_command(
                    [str(dotnet), "build", project_file, "--nologo"],
                    root,
                    timeout_seconds,
                )
                commands.append(build)
                _command_failed(f"dotnet build {project_file}", build, findings)

        import_result = run_command(
            [str(godot), "--headless", "--path", str(root), "--editor", "--quit"],
            root,
            timeout_seconds,
        )
        commands.append(import_result)
        _command_failed("Godot headless import", import_result, findings)

        if project.configured_main_scene and boot_frames > 0:
            boot = run_command(
                [
                    str(godot),
                    "--headless",
                    "--path",
                    str(root),
                    "--quit-after",
                    str(boot_frames),
                ],
                root,
                timeout_seconds,
            )
            commands.append(boot)
            _command_failed("Godot bounded boot", boot, findings)

    if not godot:
        status = "blocked"
    elif requires_mono and not dotnet:
        status = "blocked"
    else:
        status = "passed" if not findings else "failed"

    return PipelineReport(
        schema_version="2.0",
        run_id=_run_id(),
        generated_at=datetime.now(UTC).isoformat(),
        status=status,
        project=project,
        workload=workload,
        tools=tools,
        findings=findings,
        commands=commands,
    )


def write_report_bundle(report: PipelineReport, output_directory: Path) -> list[Path]:
    output_directory = output_directory.expanduser().resolve()
    output_directory.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []

    report_path = output_directory / "report.json"
    report_path.write_text(f"{report.to_json()}\n", encoding="utf-8")
    created.append(report_path)

    for index, command in enumerate(report.commands, start=1):
        prefix = output_directory / f"command-{index:02d}"
        stdout_path = prefix.with_suffix(".stdout.log")
        stderr_path = prefix.with_suffix(".stderr.log")
        stdout_path.write_text(command.stdout, encoding="utf-8")
        stderr_path.write_text(command.stderr, encoding="utf-8")
        created.extend([stdout_path, stderr_path])

    report.artifacts[:] = [str(path) for path in created]
    report_path.write_text(f"{report.to_json()}\n", encoding="utf-8")
    return created


def doctor_payload(
    *,
    godot_executable: Path | None = None,
    dotnet_executable: Path | None = None,
) -> dict[str, object]:
    working_directory = Path.cwd()
    godot = discover_godot_binary(godot_executable, requires_mono=False)
    godot_mono = discover_godot_binary(godot_executable, requires_mono=True)
    dotnet = discover_dotnet(dotnet_executable)

    def version(executable: Path | None) -> str | None:
        if not executable:
            return None
        result = run_command(
            [str(executable), "--version"], working_directory, 30
        )
        return _version_from_result(result)

    return {
        "schemaVersion": "1.0",
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "godot": {"path": str(godot) if godot else None, "version": version(godot)},
        "godotMono": {
            "path": str(godot_mono) if godot_mono else None,
            "version": version(godot_mono),
        },
        "dotnet": {"path": str(dotnet) if dotnet else None, "version": version(dotnet)},
    }


def run_bounded_project(
    candidate: Path,
    *,
    godot_executable: Path | None = None,
    scene: str | None = None,
    frames: int = 120,
    headless: bool = False,
    timeout_seconds: int = 300,
) -> CommandResult:
    project = inspect_project(candidate)
    root = Path(project.project_root)
    godot = discover_godot_binary(
        godot_executable,
        requires_mono=bool(project.csharp_projects),
    )
    if not godot:
        raise FileNotFoundError("Compatible Godot executable was not found.")
    command: list[str] = [str(godot)]
    if headless:
        command.append("--headless")
    command.extend(["--path", str(root), "--quit-after", str(max(1, frames))])
    if scene:
        command.extend(["--scene", scene])
    return run_command(command, root, timeout_seconds)


def record_project_movie(
    candidate: Path,
    output: Path,
    *,
    godot_executable: Path | None = None,
    scene: str | None = None,
    frames: int = 300,
    fps: int = 30,
    timeout_seconds: int = 900,
) -> CommandResult:
    project = inspect_project(candidate)
    root = Path(project.project_root)
    godot = discover_godot_binary(
        godot_executable,
        requires_mono=bool(project.csharp_projects),
    )
    if not godot:
        raise FileNotFoundError("Compatible Godot executable was not found.")
    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    command: list[str] = [
        str(godot),
        "--path",
        str(root),
        "--write-movie",
        str(output),
        "--fixed-fps",
        str(max(1, fps)),
        "--quit-after",
        str(max(1, frames)),
    ]
    if scene:
        command.extend(["--scene", scene])
    return run_command(command, root, timeout_seconds)


def export_project(
    candidate: Path,
    preset: str,
    output: Path,
    *,
    godot_executable: Path | None = None,
    debug: bool = False,
    timeout_seconds: int = 1_800,
) -> CommandResult:
    project = inspect_project(candidate)
    root = Path(project.project_root)
    godot = discover_godot_binary(
        godot_executable,
        requires_mono=bool(project.csharp_projects),
    )
    if not godot:
        raise FileNotFoundError("Compatible Godot executable was not found.")
    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    flag = "--export-debug" if debug else "--export-release"
    return run_command(
        [str(godot), "--headless", "--path", str(root), flag, preset, str(output)],
        root,
        timeout_seconds,
    )


def command_result_payload(result: CommandResult) -> dict[str, object]:
    return asdict(result)


def command_succeeded(result: CommandResult) -> bool:
    return not result.timed_out and result.exit_code == 0 and not _contains_error_marker(result)


def render_json(value: object) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False)


def normalized_command(command: Sequence[str]) -> list[str]:
    return [str(part) for part in command]
