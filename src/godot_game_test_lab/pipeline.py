from __future__ import annotations

import json
import os
import platform
import re
import shutil
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from .core import CommandResult, ProjectInventory, inspect_project, run_command
from .integrity import (
    IntegrityReport,
    audit_project,
    execution_blocking_findings,
)

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
    integrity: IntegrityReport | None = None
    diagnostics: list[str] = field(default_factory=list)
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


def _version_from_name(path: Path) -> tuple[int, int, int]:
    match = _VERSION_RE.search(path.name)
    if match is None:
        return (0, 0, 0)
    return (
        int(match.group("major")),
        int(match.group("minor")),
        int(match.group("patch") or 0),
    )


def _looks_like_godot_executable(path: Path, *, requires_mono: bool) -> bool:
    name = path.name.casefold()
    if not name.startswith("godot") or name.startswith("godot-lab"):
        return False
    if requires_mono and "mono" not in name and ".net" not in name:
        return False
    return name in {"godot", "godot4", "godot.exe", "godot4.exe"} or name.startswith(
        "godot_v"
    ) or (requires_mono and "mono" in name)


def _discovered_godot_candidates(*, requires_mono: bool) -> list[Path]:
    roots: list[Path] = []
    for raw in os.environ.get("PATH", "").split(os.pathsep):
        if raw.strip():
            roots.append(Path(raw.strip()).expanduser())
    managed_root = os.environ.get("EVAVO_GODOT_HOME")
    if managed_root:
        roots.append(Path(managed_root).expanduser())
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        roots.extend(
            [
                Path(local_app_data) / "Programs",
                Path(local_app_data) / "EVAVO" / "GodotGameTestLab" / "engines",
            ]
        )
    if os.name == "nt":
        roots.extend([Path("C:/Tools"), Path("C:/Godot")])

    candidates: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        try:
            resolved_root = root.resolve()
        except OSError:
            continue
        if not resolved_root.is_dir():
            continue
        patterns = ("Godot*", "godot*")
        for pattern in patterns:
            try:
                matches = [
                    *resolved_root.glob(pattern),
                    *resolved_root.glob(f"Godot*/{pattern}"),
                ]
            except OSError:
                continue
            for candidate in matches:
                try:
                    resolved = candidate.resolve()
                except OSError:
                    continue
                identity = os.path.normcase(str(resolved))
                if (
                    identity in seen
                    or not resolved.is_file()
                    or not os.access(resolved, os.X_OK)
                    or not _looks_like_godot_executable(
                        resolved, requires_mono=requires_mono
                    )
                ):
                    continue
                seen.add(identity)
                candidates.append(resolved)
    return sorted(
        candidates,
        key=lambda path: (
            _version_from_name(path),
            "console" in path.name.casefold(),
            str(path).casefold(),
        ),
        reverse=True,
    )


def discover_godot_binary(
    explicit: Path | None = None,
    *,
    requires_mono: bool = False,
) -> Path | None:
    for value in [
        str(explicit) if explicit else None,
        os.environ.get("GODOT_MONO_BIN") if requires_mono else None,
        os.environ.get("GODOT_BIN"),
    ]:
        candidate = _candidate_path(value)
        if candidate:
            return candidate

    discovered = _discovered_godot_candidates(requires_mono=requires_mono)
    if discovered:
        return discovered[0]

    executable_names = (
        ("godot-mono", "godot4-mono")
        if requires_mono
        else ("godot4", "godot")
    )
    for name in executable_names:
        candidate = _which(name)
        if candidate:
            return candidate
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


def _meets_minimum(
    actual: str | None,
    minimum: str,
    *,
    allow_major_upgrade: bool = False,
) -> bool:
    actual_tuple = _version_tuple(actual)
    minimum_tuple = _version_tuple(minimum)
    if actual_tuple is None or minimum_tuple is None or actual_tuple < minimum_tuple:
        return False
    return allow_major_upgrade or actual_tuple[0] == minimum_tuple[0]


def _required_godot_capabilities(*, recovery_diagnostic: bool) -> tuple[str, ...]:
    capabilities = ["--headless", "--import", "--path"]
    if recovery_diagnostic:
        capabilities.append("--recovery-mode")
    return tuple(capabilities)


def _missing_capabilities(help_result: CommandResult, required: Sequence[str]) -> list[str]:
    combined = f"{help_result.stdout}\n{help_result.stderr}"
    return [capability for capability in required if capability not in combined]


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
    run_integrity_audit: bool = True,
    warnings_as_errors: bool = False,
    recovery_diagnostic: bool = True,
    allow_major_upgrade: bool = False,
    log_directory: Path | None = None,
) -> PipelineReport:
    project = inspect_project(candidate)
    root = Path(project.project_root)
    requires_mono = bool(project.csharp_projects)
    workload = "godot-csharp" if requires_mono else "godot-gdscript"
    findings: list[str] = []
    diagnostics: list[str] = []
    commands: list[CommandResult] = []
    tools: list[ToolIdentity] = []
    artifacts: list[str] = []
    integrity = audit_project(root) if run_integrity_audit else None
    execution_blockers = execution_blocking_findings(integrity) if integrity else []
    if integrity is not None and integrity.errors:
        findings.append(
            f"Static integrity audit found {integrity.errors} error(s) "
            f"and {integrity.warnings} warning(s)."
        )
    elif integrity is not None and warnings_as_errors and integrity.warnings:
        findings.append(
            f"Static integrity audit found {integrity.warnings} warning(s); "
            "warnings-as-errors is enabled."
        )
    if execution_blockers:
        diagnostics.append(
            "Godot execution was withheld because the static audit found filesystem, "
            "path-escape, or bounded-scan safety blockers."
        )
    resolved_log_directory: Path | None = None
    if log_directory is not None:
        resolved_log_directory = log_directory.expanduser().resolve()
        resolved_log_directory.mkdir(parents=True, exist_ok=True)

    def engine_log(name: str) -> list[str]:
        if resolved_log_directory is None:
            return []
        path = resolved_log_directory / f"{name}.log"
        artifacts.append(str(path))
        return ["--log-file", str(path)]

    if not project.configured_main_scene:
        findings.append("Project has no run/main_scene configured.")
    if not project.scenes:
        findings.append("Project contains no Godot scene files.")

    godot = discover_godot_binary(godot_executable, requires_mono=requires_mono)
    godot_version: str | None = None
    godot_notes: list[str] = []
    if godot:
        version_result = run_command([str(godot), "--version"], root, 30)
        commands.append(version_result)
        godot_version = _version_from_result(version_result)
        if not command_succeeded(version_result):
            godot_notes.append("Godot --version failed.")
        if not _meets_minimum(
            godot_version,
            minimum_godot_version,
            allow_major_upgrade=allow_major_upgrade,
        ):
            policy = "or a later major version" if allow_major_upgrade else "within the same major"
            godot_notes.append(
                f"Godot {godot_version or 'unknown'} does not meet "
                f"{minimum_godot_version} {policy}."
            )
        help_result = run_command([str(godot), "--help"], root, 30)
        commands.append(help_result)
        if not command_succeeded(help_result):
            godot_notes.append("Godot --help failed; editor capabilities could not be verified.")
        else:
            missing = _missing_capabilities(
                help_result,
                _required_godot_capabilities(recovery_diagnostic=recovery_diagnostic),
            )
            if missing:
                godot_notes.append(
                    "Godot binary is missing required editor capabilities: "
                    + ", ".join(missing)
                    + "."
                )
        if requires_mono:
            version_text = f"{version_result.stdout}\n{version_result.stderr}".lower()
            name_text = godot.name.lower()
            if (
                "mono" not in version_text
                and ".net" not in version_text
                and "mono" not in name_text
            ):
                godot_notes.append("C# project requires a Godot .NET/Mono executable.")
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

    dotnet_notes_present = requires_mono and any(
        tool.id == "dotnet" and tool.notes for tool in tools
    )
    build_succeeded = True
    if godot and not godot_notes and not execution_blockers and not dotnet_notes_present:
        if requires_mono:
            if dotnet is None:
                build_succeeded = False
            else:
                for project_file in project.csharp_projects:
                    build = run_command(
                        [str(dotnet), "build", project_file, "--nologo"],
                        root,
                        timeout_seconds,
                    )
                    commands.append(build)
                    _command_failed(f"dotnet build {project_file}", build, findings)
                    if not command_succeeded(build):
                        build_succeeded = False
                if not build_succeeded:
                    diagnostics.append(
                        "Godot import was skipped because the C# build did not complete cleanly."
                    )

        if build_succeeded:
            import_command = [str(godot), "--headless", "--path", str(root)]
            import_command.extend(engine_log("godot-import"))
            import_command.append("--import")
            import_result = run_command(import_command, root, timeout_seconds)
            commands.append(import_result)
            _command_failed("Godot authoritative import", import_result, findings)
            import_succeeded = command_succeeded(import_result)

            if not import_succeeded and recovery_diagnostic:
                recovery_command = [
                    str(godot),
                    "--headless",
                    "--path",
                    str(root),
                    "--recovery-mode",
                ]
                recovery_command.extend(engine_log("godot-recovery-import"))
                recovery_command.append("--import")
                recovery = run_command(recovery_command, root, timeout_seconds)
                commands.append(recovery)
                if command_succeeded(recovery):
                    diagnostics.append(
                        "Recovery-mode import passed after the normal import failed; "
                        "an editor plugin, tool script, GDExtension, or other disabled "
                        "editor extension is suspected."
                    )
                else:
                    _command_failed("Godot recovery-mode import", recovery, findings)
                    diagnostics.append(
                        "Recovery-mode import also failed; project source, imported assets, "
                        "engine compatibility, or core project configuration remains suspect."
                    )

            if import_succeeded and project.configured_main_scene and boot_frames > 0:
                boot_command = [
                    str(godot),
                    "--headless",
                    "--path",
                    str(root),
                ]
                boot_command.extend(engine_log("godot-bounded-boot"))
                boot_command.extend(["--quit-after", str(boot_frames)])
                boot = run_command(boot_command, root, timeout_seconds)
                commands.append(boot)
                _command_failed("Godot bounded boot", boot, findings)

    if not godot or godot_notes:
        status = "blocked"
    elif requires_mono and (not dotnet or dotnet_notes_present):
        status = "blocked"
    else:
        status = "passed" if not findings else "failed"

    return PipelineReport(
        schema_version="2.1",
        run_id=_run_id(),
        generated_at=datetime.now(UTC).isoformat(),
        status=status,
        project=project,
        workload=workload,
        integrity=integrity,
        diagnostics=diagnostics,
        tools=tools,
        findings=findings,
        commands=commands,
        artifacts=artifacts,
    )


def write_report_bundle(report: PipelineReport, output_directory: Path) -> list[Path]:
    output_directory = output_directory.expanduser().resolve()
    output_directory.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []

    report_path = output_directory / "report.json"
    report_path.write_text(f"{report.to_json()}\n", encoding="utf-8")
    created.append(report_path)

    if report.integrity is not None:
        integrity_path = output_directory / "integrity-report.json"
        integrity_path.write_text(f"{report.integrity.to_json()}\n", encoding="utf-8")
        created.append(integrity_path)

    for index, command in enumerate(report.commands, start=1):
        prefix = output_directory / f"command-{index:02d}"
        stdout_path = prefix.with_suffix(".stdout.log")
        stderr_path = prefix.with_suffix(".stderr.log")
        stdout_path.write_text(command.stdout, encoding="utf-8")
        stderr_path.write_text(command.stderr, encoding="utf-8")
        created.extend([stdout_path, stderr_path])

    existing = [Path(path) for path in report.artifacts if Path(path).exists()]
    report.artifacts[:] = [str(path) for path in [*created, *existing]]
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

    def probe_godot(
        executable: Path | None,
        *,
        requires_mono: bool,
    ) -> dict[str, object]:
        if not executable:
            return {
                "path": None,
                "version": None,
                "editorCompatible": False,
                "flavorCompatible": False,
                "capabilities": [],
                "missingCapabilities": list(
                    _required_godot_capabilities(recovery_diagnostic=True)
                ),
            }
        version_result = run_command([str(executable), "--version"], working_directory, 30)
        help_result = run_command([str(executable), "--help"], working_directory, 30)
        required = _required_godot_capabilities(recovery_diagnostic=True)
        missing = (
            _missing_capabilities(help_result, required)
            if command_succeeded(help_result)
            else list(required)
        )
        combined_help = f"{help_result.stdout}\n{help_result.stderr}"
        optional = (
            "--export-debug",
            "--export-release",
            "--gpu-index",
            "--gpu-profile",
            "--gpu-validation",
            "--write-movie",
        )
        identity = f"{executable.name}\n{version_result.stdout}\n{version_result.stderr}".casefold()
        flavor_compatible = not requires_mono or "mono" in identity or ".net" in identity
        return {
            "path": str(executable),
            "version": _version_from_result(version_result),
            "editorCompatible": (
                command_succeeded(version_result) and not missing and flavor_compatible
            ),
            "flavorCompatible": flavor_compatible,
            "capabilities": [value for value in (*required, *optional) if value in combined_help],
            "missingCapabilities": missing,
        }

    def probe_tool(executable: Path | None, arguments: list[str]) -> dict[str, object]:
        if not executable:
            return {"path": None, "available": False, "exitCode": None, "output": ""}
        result = run_command([str(executable), *arguments], working_directory, 30)
        output = f"{result.stdout}\n{result.stderr}".strip()
        return {
            "path": str(executable),
            "available": command_succeeded(result),
            "exitCode": result.exit_code,
            "output": output,
        }

    dotnet_probe = probe_tool(dotnet, ["--version"])
    if dotnet_probe["available"]:
        dotnet_probe["version"] = str(dotnet_probe["output"]).splitlines()[0]
    else:
        dotnet_probe["version"] = None

    nvidia_smi = _which("nvidia-smi")
    nvcc = _which("nvcc")
    vulkaninfo = _which("vulkaninfo")
    return {
        "schemaVersion": "2.0",
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "godot": probe_godot(godot, requires_mono=False),
        "godotMono": probe_godot(godot_mono, requires_mono=True),
        "dotnet": dotnet_probe,
        "graphics": {
            "nvidiaSmi": probe_tool(nvidia_smi, ["-L"]),
            "cudaCompiler": probe_tool(nvcc, ["--version"]),
            "vulkan": probe_tool(vulkaninfo, ["--summary"]),
            "truthBoundary": (
                "CUDA availability is auxiliary compute evidence; Godot rendering uses its "
                "selected display and rendering drivers rather than CUDA."
            ),
        },
    }


def _require_safe_execution(candidate: Path) -> None:
    report = audit_project(candidate)
    blockers = execution_blocking_findings(report)
    if blockers:
        rendered = ", ".join(sorted({finding.code for finding in blockers}))
        raise ValueError(
            "Godot execution is blocked by incomplete or unsafe project integrity evidence: "
            f"{rendered}"
        )


def run_bounded_project(
    candidate: Path,
    *,
    godot_executable: Path | None = None,
    scene: str | None = None,
    frames: int = 120,
    headless: bool = False,
    timeout_seconds: int = 300,
) -> CommandResult:
    _require_safe_execution(candidate)
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
    _require_safe_execution(candidate)
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
    _require_safe_execution(candidate)
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
