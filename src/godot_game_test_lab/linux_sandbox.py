from __future__ import annotations

import json
import os
import platform
import re
import shutil
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .core import CommandResult, ProjectInventory, inspect_project, run_command

_ERROR_MARKERS = (
    "ERROR:",
    "SCRIPT ERROR:",
    "Parse Error",
    "Build FAILED",
    "Unhandled exception",
    "Failed to load script",
    "Cannot open file",
)
_EXCLUDED_NAMES = frozenset({".git", ".godot", ".qa", ".cache", "artifacts"})
_VERSION_RE = re.compile(r"(?P<major>\d+)\.(?P<minor>\d+)(?:\.(?P<patch>\d+))?")


@dataclass(slots=True)
class SandboxPhase:
    id: str
    status: str
    command: CommandResult | None = None
    findings: list[str] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)


@dataclass(slots=True)
class LinuxSandboxReport:
    schema_version: str
    generated_at: str
    status: str
    source_root: str
    working_root: str
    project_subpath: str
    project: ProjectInventory | None
    target_repository: str | None
    target_sha: str | None
    lab_sha: str | None
    environment: dict[str, Any]
    phases: list[SandboxPhase]
    findings: list[str]
    artifacts: list[str]

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, ensure_ascii=False)


def safe_project_subpath(value: str) -> Path:
    normalized = value.strip().replace("\\", "/")
    if normalized in ("", "."):
        return Path(".")
    candidate = Path(normalized)
    windows_drive = len(normalized) >= 3 and normalized[0].isalpha() and normalized[1:3] == ":/"
    if (
        windows_drive
        or candidate.is_absolute()
        or any(part in ("", ".", "..") for part in candidate.parts)
    ):
        raise ValueError("project_subpath must be a canonical relative path without traversal")
    return candidate


def _validate_source_symlinks(source_root: Path) -> None:
    root = source_root.resolve()
    for path in root.rglob("*"):
        if not path.is_symlink():
            continue
        raw_target = path.readlink()
        if raw_target.is_absolute():
            raise ValueError(f"absolute source symlink is not allowed: {path}")
        target = path.resolve(strict=False)
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"source symlink escapes repository: {path}") from exc


def prepare_ephemeral_copy(source_root: Path, working_root: Path) -> Path:
    source = source_root.expanduser().resolve()
    destination = working_root.expanduser().resolve()
    if not source.is_dir():
        raise FileNotFoundError(f"Linux sandbox source directory is missing: {source}")
    _validate_source_symlinks(source)
    if destination.exists():
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)

    def ignore(_directory: str, names: list[str]) -> set[str]:
        return {name for name in names if name in _EXCLUDED_NAMES}

    shutil.copytree(source, destination, symlinks=True, ignore=ignore)
    return destination


def _write_command_logs(phase: SandboxPhase, artifacts: Path) -> None:
    if phase.command is None:
        return
    logs = artifacts / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    stdout_path = logs / f"{phase.id}.stdout.log"
    stderr_path = logs / f"{phase.id}.stderr.log"
    stdout_path.write_text(phase.command.stdout, encoding="utf-8")
    stderr_path.write_text(phase.command.stderr, encoding="utf-8")
    phase.artifacts.extend(
        [
            stdout_path.relative_to(artifacts).as_posix(),
            stderr_path.relative_to(artifacts).as_posix(),
        ]
    )


def _phase_from_command(phase_id: str, result: CommandResult, artifacts: Path) -> SandboxPhase:
    findings: list[str] = []
    combined = f"{result.stdout}\n{result.stderr}".lower()
    for marker in _ERROR_MARKERS:
        if marker.lower() in combined:
            findings.append(f"output contains error marker: {marker}")
    if result.timed_out:
        findings.append(f"timed out after {result.duration_seconds} seconds")
    elif result.exit_code != 0:
        findings.append(f"exited with code {result.exit_code}")
    phase = SandboxPhase(
        id=phase_id,
        status="passed" if not findings else "failed",
        command=result,
        findings=findings,
    )
    _write_command_logs(phase, artifacts)
    return phase


def _command_exists(name: str) -> str | None:
    resolved = shutil.which(name)
    return str(Path(resolved).resolve()) if resolved else None


def _run_phase(
    phase_id: str,
    command: Sequence[str],
    cwd: Path,
    timeout_seconds: int,
    artifacts: Path,
) -> SandboxPhase:
    return _phase_from_command(
        phase_id,
        run_command(command, cwd, timeout_seconds),
        artifacts,
    )


def _version_tuple(value: str) -> tuple[int, int, int] | None:
    match = _VERSION_RE.search(value)
    if not match:
        return None
    return (
        int(match.group("major")),
        int(match.group("minor")),
        int(match.group("patch") or 0),
    )


def _enforce_godot_identity(
    phase: SandboxPhase,
    minimum_version: str,
    requires_dotnet_editor: bool,
    executable: Path,
) -> None:
    if phase.command is None:
        return
    combined = f"{phase.command.stdout}\n{phase.command.stderr}"
    actual = _version_tuple(combined)
    minimum = _version_tuple(minimum_version)
    if actual is None or minimum is None or actual < minimum:
        phase.status = "failed"
        phase.findings.append(
            f"Godot version {actual or 'unknown'} does not meet {minimum_version}"
        )
    identity = f"{executable.name}\n{combined}".lower()
    if requires_dotnet_editor and "mono" not in identity and ".net" not in identity:
        phase.status = "failed"
        phase.findings.append("C# project requires the .NET-enabled Godot editor")


def _collect_visual_artifacts(
    movie: Path, artifacts: Path, timeout_seconds: int
) -> list[SandboxPhase]:
    phases: list[SandboxPhase] = []
    ffprobe = _command_exists("ffprobe")
    ffmpeg = _command_exists("ffmpeg")
    if not movie.is_file():
        phases.append(SandboxPhase("visual-evidence", "failed", findings=["movie file is missing"]))
        return phases
    if ffprobe:
        probe_json = artifacts / "visual" / "ffprobe.json"
        phase = _run_phase(
            "visual-probe",
            [ffprobe, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(movie)],
            movie.parent,
            timeout_seconds,
            artifacts,
        )
        if phase.command and phase.status == "passed":
            probe_json.write_text(phase.command.stdout, encoding="utf-8")
            phase.artifacts.append(probe_json.relative_to(artifacts).as_posix())
        phases.append(phase)
    if ffmpeg:
        contact_sheet = artifacts / "visual" / "contact-sheet.png"
        phase = _run_phase(
            "visual-contact-sheet",
            [
                ffmpeg,
                "-y",
                "-i",
                str(movie),
                "-vf",
                "fps=2,scale=320:-1,tile=4x3",
                "-frames:v",
                "1",
                str(contact_sheet),
            ],
            movie.parent,
            timeout_seconds,
            artifacts,
        )
        if contact_sheet.is_file():
            phase.artifacts.append(contact_sheet.relative_to(artifacts).as_posix())
        phases.append(phase)
    return phases


def run_linux_sandbox(
    source_root: Path,
    *,
    working_root: Path,
    artifacts_root: Path,
    project_subpath: str = ".",
    godot_executable: Path,
    dotnet_executable: Path | None = None,
    minimum_godot_version: str = "4.6.2",
    timeout_seconds: int = 600,
    boot_frames: int = 30,
    visual_frames: int = 180,
    visual_fps: int = 30,
    visual_width: int = 1280,
    visual_height: int = 720,
    export_preset: str | None = None,
) -> LinuxSandboxReport:
    artifacts = artifacts_root.expanduser().resolve()
    artifacts.mkdir(parents=True, exist_ok=True)
    phases: list[SandboxPhase] = []
    findings: list[str] = []
    all_artifacts: list[str] = []
    project: ProjectInventory | None = None

    try:
        relative_project = safe_project_subpath(project_subpath)
        working_copy = prepare_ephemeral_copy(source_root, working_root)
        project_root = (working_copy / relative_project).resolve()
        project_root.relative_to(working_copy)
        project = inspect_project(project_root)
        if not project.scenes:
            findings.append("Project contains no .tscn scene files")
        if visual_frames > 0 and not project.configured_main_scene:
            findings.append("Visual capture requires run/main_scene")
    except (FileNotFoundError, OSError, ValueError) as exc:
        findings.append(str(exc))
        report = LinuxSandboxReport(
            schema_version="1.0",
            generated_at=datetime.now(UTC).isoformat(),
            status="blocked",
            source_root=str(source_root.expanduser().resolve()),
            working_root=str(working_root.expanduser().resolve()),
            project_subpath=project_subpath,
            project=None,
            target_repository=os.environ.get("EVAVO_TARGET_REPOSITORY"),
            target_sha=os.environ.get("EVAVO_TARGET_SHA"),
            lab_sha=os.environ.get("EVAVO_LAB_SHA"),
            environment={"platform": platform.platform(), "python": platform.python_version()},
            phases=phases,
            findings=findings,
            artifacts=all_artifacts,
        )
        (artifacts / "sandbox-report.json").write_text(f"{report.to_json()}\n", encoding="utf-8")
        return report

    godot = godot_executable.expanduser().resolve()
    dotnet = dotnet_executable.expanduser().resolve() if dotnet_executable else None
    if not godot.is_file():
        findings.append(f"Godot executable is missing: {godot}")
    if project.csharp_projects and (dotnet is None or not dotnet.is_file()):
        findings.append("C# project requires an available .NET SDK executable")
    missing_dotnet = bool(project.csharp_projects) and (dotnet is None or not dotnet.is_file())
    if not godot.is_file() or missing_dotnet:
        status = "blocked"
    else:
        status = "failed" if findings else "passed"

    if status != "blocked":
        version_phase = _run_phase(
            "godot-version", [str(godot), "--version"], project_root, 30, artifacts
        )
        _enforce_godot_identity(
            version_phase, minimum_godot_version, bool(project.csharp_projects), godot
        )
        phases.append(version_phase)
        if project.csharp_projects and dotnet is not None:
            phases.append(
                _run_phase(
                    "dotnet-version",
                    [str(dotnet), "--version"],
                    project_root,
                    30,
                    artifacts,
                )
            )
            for index, project_file in enumerate(project.csharp_projects, start=1):
                phases.append(
                    _run_phase(
                        f"dotnet-build-{index:02d}",
                        [str(dotnet), "build", project_file, "--nologo"],
                        project_root,
                        timeout_seconds,
                        artifacts,
                    )
                )

        phases.append(
            _run_phase(
                "godot-import",
                [str(godot), "--headless", "--path", str(project_root), "--editor", "--quit"],
                project_root,
                timeout_seconds,
                artifacts,
            )
        )
        if project.configured_main_scene and boot_frames > 0:
            phases.append(
                _run_phase(
                    "godot-headless-boot",
                    [
                        str(godot),
                        "--headless",
                        "--path",
                        str(project_root),
                        "--quit-after",
                        str(boot_frames),
                    ],
                    project_root,
                    timeout_seconds,
                    artifacts,
                )
            )

        prerequisite_failed = any(phase.status != "passed" for phase in phases)
        if visual_frames > 0 and project.configured_main_scene and not prerequisite_failed:
            xvfb_run = _command_exists("xvfb-run")
            if not xvfb_run:
                phases.append(
                    SandboxPhase(
                        "godot-windowed-movie",
                        "blocked",
                        findings=["xvfb-run is unavailable"],
                    )
                )
            else:
                visual_dir = artifacts / "visual"
                visual_dir.mkdir(parents=True, exist_ok=True)
                movie = visual_dir / "gameplay.avi"
                visual_command = [
                    "/usr/bin/env",
                    "LIBGL_ALWAYS_SOFTWARE=1",
                    "GALLIUM_DRIVER=llvmpipe",
                    xvfb_run,
                    "-a",
                    "-s",
                    f"-screen 0 {visual_width}x{visual_height}x24 -nolisten tcp",
                    str(godot),
                    "--path",
                    str(project_root),
                    "--windowed",
                    "--resolution",
                    f"{visual_width}x{visual_height}",
                    "--rendering-method",
                    "gl_compatibility",
                    "--audio-driver",
                    "Dummy",
                    "--write-movie",
                    str(movie),
                    "--fixed-fps",
                    str(visual_fps),
                    "--quit-after",
                    str(visual_frames),
                ]
                movie_phase = _run_phase(
                    "godot-windowed-movie",
                    visual_command,
                    project_root,
                    timeout_seconds,
                    artifacts,
                )
                if movie.is_file():
                    movie_phase.artifacts.append(movie.relative_to(artifacts).as_posix())
                else:
                    movie_phase.status = "failed"
                    movie_phase.findings.append("Godot Movie Maker did not produce gameplay.avi")
                phases.append(movie_phase)
                if movie.is_file():
                    phases.extend(_collect_visual_artifacts(movie, artifacts, timeout_seconds))

        if export_preset and not any(phase.status == "failed" for phase in phases):
            export_dir = artifacts / "export"
            export_dir.mkdir(parents=True, exist_ok=True)
            export_path = export_dir / "game.x86_64"
            phase = _run_phase(
                "godot-linux-export",
                [
                    str(godot),
                    "--headless",
                    "--path",
                    str(project_root),
                    "--export-release",
                    export_preset,
                    str(export_path),
                ],
                project_root,
                timeout_seconds,
                artifacts,
            )
            if export_path.is_file():
                phase.artifacts.append(export_path.relative_to(artifacts).as_posix())
            else:
                phase.status = "failed"
                phase.findings.append("declared Linux export was not created")
            phases.append(phase)

        if any(phase.status in ("failed", "blocked") for phase in phases):
            status = "failed"

    for phase in phases:
        findings.extend(f"{phase.id}: {finding}" for finding in phase.findings)
        all_artifacts.extend(phase.artifacts)

    report = LinuxSandboxReport(
        schema_version="1.0",
        generated_at=datetime.now(UTC).isoformat(),
        status=status,
        source_root=str(source_root.expanduser().resolve()),
        working_root=str(working_root.expanduser().resolve()),
        project_subpath=relative_project.as_posix(),
        project=project,
        target_repository=os.environ.get("EVAVO_TARGET_REPOSITORY"),
        target_sha=os.environ.get("EVAVO_TARGET_SHA"),
        lab_sha=os.environ.get("EVAVO_LAB_SHA"),
        environment={
            "platform": platform.platform(),
            "python": platform.python_version(),
            "softwareRendering": True,
            "display": "xvfb",
            "network": "disabled-by-container-contract",
        },
        phases=phases,
        findings=findings,
        artifacts=sorted(set(all_artifacts)),
    )
    report_path = artifacts / "sandbox-report.json"
    report_path.write_text(f"{report.to_json()}\n", encoding="utf-8")
    return report
