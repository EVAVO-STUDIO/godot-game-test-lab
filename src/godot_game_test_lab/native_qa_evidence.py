from __future__ import annotations

import ctypes
import json
import os
import re
import shutil
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .native_qa_common import (
    NativeQaError,
    _directory_usage,
    _process_findings,
    _run_process,
    _sha256_file,
    _write_process_evidence,
)

_BLACK_RE = re.compile(
    r"black_start:(?P<start>[0-9.]+)\s+black_end:(?P<end>[0-9.]+)\s+"
    r"black_duration:(?P<duration>[0-9.]+)"
)
_FREEZE_START_RE = re.compile(r"freeze_start:\s*(?P<start>[0-9.]+)")
_FREEZE_END_RE = re.compile(
    r"freeze_end:\s*(?P<end>[0-9.]+)\s*\|\s*freeze_duration:\s*(?P<duration>[0-9.]+)"
)
_MAX_ARTIFACT_FILES = 20_000


def _powershell_executable() -> str | None:
    return shutil.which("powershell") or shutil.which("pwsh")


def _explorer_session_ids(cwd: Path) -> tuple[list[int], str | None]:
    executable = _powershell_executable()
    if executable is None:
        return ([], "PowerShell is unavailable")
    result = _run_process(
        [
            executable,
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "@(Get-Process -Name explorer -ErrorAction SilentlyContinue | "
            "Select-Object -ExpandProperty SessionId | Sort-Object -Unique) | "
            "ConvertTo-Json -Compress",
        ],
        cwd,
        30,
    )
    findings = _process_findings(result, "Explorer session probe")
    if findings:
        return ([], "; ".join(findings))
    text = str(result.get("stdout", "")).strip()
    if not text:
        return ([], None)
    try:
        value = json.loads(text)
    except json.JSONDecodeError as error:
        return ([], f"Explorer session output was invalid JSON: {error}")
    if isinstance(value, int):
        return ([value], None)
    if isinstance(value, list) and all(isinstance(item, int) for item in value):
        return (sorted(set(value)), None)
    return ([], "Explorer session output had an unexpected shape")


def _interactive_session(cwd: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "platform": os.name,
        "sessionName": os.environ.get("SESSIONNAME", ""),
        "sessionId": None,
        "explorerSessionIds": [],
        "explorerInSameSession": False,
        "interactive": False,
        "probeError": None,
    }
    if os.name != "nt":
        result["probeError"] = "Native Windows desktop evidence requires Windows"
        return result
    session_id = ctypes.c_uint32()
    ok = ctypes.windll.kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(session_id))
    if ok:
        result["sessionId"] = int(session_id.value)
    explorer_ids, error = _explorer_session_ids(cwd)
    result["explorerSessionIds"] = explorer_ids
    result["probeError"] = error
    same_session = bool(ok and int(session_id.value) in explorer_ids)
    result["explorerInSameSession"] = same_session
    name = str(result["sessionName"]).casefold()
    result["interactive"] = bool(
        ok and session_id.value != 0 and name != "services" and same_session
    )
    return result


def _probe(command: Sequence[str], cwd: Path, timeout: int = 30) -> dict[str, Any]:
    executable = shutil.which(str(command[0]))
    if executable is None:
        return {"available": False, "command": list(command), "output": ""}
    result = _run_process([executable, *command[1:]], cwd, timeout)
    return {
        "available": not _process_findings(result, str(command[0])),
        "command": result["command"],
        "exitCode": result["exitCode"],
        "output": f"{result['stdout']}\n{result['stderr']}".strip(),
    }


def _hardware_evidence(cwd: Path) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "session": _interactive_session(cwd),
        "nvidia": _probe(
            [
                "nvidia-smi",
                "--query-gpu=index,name,driver_version,memory.total",
                "--format=csv,noheader",
            ],
            cwd,
        ),
        "vulkan": _probe(["vulkaninfo", "--summary"], cwd),
        "cudaCompiler": _probe(["nvcc", "--version"], cwd),
        "ffmpeg": _probe(["ffmpeg", "-version"], cwd),
        "ffprobe": _probe(["ffprobe", "-version"], cwd),
        "truthBoundary": (
            "Adapter, Vulkan, NVIDIA and CUDA probes are environment evidence. They do not "
            "prove that a particular Godot frame rendered on a selected adapter."
        ),
    }
    if os.name == "nt":
        powershell = _powershell_executable() or "powershell"
        evidence["windowsVideoControllers"] = _probe(
            [
                powershell,
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "Get-CimInstance Win32_VideoController | "
                "Select-Object Name,DriverVersion,AdapterRAM,PNPDeviceID | ConvertTo-Json",
            ],
            cwd,
        )
    return evidence


def _required_visual_capabilities(help_text: str, journey: dict[str, Any]) -> list[str]:
    required = [
        "--fixed-fps",
        "--log-file",
        "--path",
        "--position",
        "--quit-after",
        "--resolution",
        "--script",
        "--windowed",
        "--verbose",
        "--write-movie",
    ]
    if journey["renderingDriver"]:
        required.append("--rendering-driver")
    if journey["renderingMethod"]:
        required.append("--rendering-method")
    if journey["renderingMethod"] != "gl_compatibility":
        required.append("--gpu-index")
    return sorted(option for option in required if option not in help_text)


def _parse_black_segments(text: str) -> list[dict[str, float]]:
    return [
        {
            "startSeconds": float(match.group("start")),
            "endSeconds": float(match.group("end")),
            "durationSeconds": float(match.group("duration")),
        }
        for match in _BLACK_RE.finditer(text)
    ]


def _parse_freeze_segments(text: str) -> list[dict[str, float | None]]:
    starts = [float(match.group("start")) for match in _FREEZE_START_RE.finditer(text)]
    ends = [
        {
            "endSeconds": float(match.group("end")),
            "durationSeconds": float(match.group("duration")),
        }
        for match in _FREEZE_END_RE.finditer(text)
    ]
    result: list[dict[str, float | None]] = []
    for index, start in enumerate(starts):
        end = ends[index] if index < len(ends) else None
        result.append(
            {
                "startSeconds": start,
                "endSeconds": end["endSeconds"] if end else None,
                "durationSeconds": end["durationSeconds"] if end else None,
            }
        )
    return result


def _validate_png(path: Path) -> bool:
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size <= 8:
            return False
        with path.open("rb") as handle:
            return handle.read(8) == b"\x89PNG\r\n\x1a\n"
    except OSError:
        return False


def _extract_video_evidence(
    movie: Path,
    root: Path,
    timeout: int,
    ux: dict[str, Any],
    *,
    maximum_artifact_bytes: int,
) -> dict[str, Any]:
    findings: list[str] = []
    evidence: list[str] = []
    diagnostics: dict[str, Any] = {"blackSegments": [], "freezeSegments": []}
    if not movie.is_file() or movie.stat().st_size <= 0:
        return {
            "status": "failed",
            "findings": ["Godot Movie Maker did not produce a non-empty movie"],
            "evidence": [],
            "diagnostics": diagnostics,
        }
    evidence.append(movie.relative_to(root).as_posix())
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        findings.append("ffmpeg and ffprobe are required for native visual evidence extraction")
        return {
            "status": "blocked",
            "findings": findings,
            "evidence": evidence,
            "diagnostics": diagnostics,
        }

    probe = _run_process(
        [ffprobe, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(movie)],
        movie.parent,
        timeout,
        artifact_budget_root=movie.parent,
        maximum_artifact_bytes=maximum_artifact_bytes,
    )
    evidence.extend(_write_process_evidence(probe, root, f"{movie.parent.name}-ffprobe"))
    findings.extend(_process_findings(probe, "ffprobe"))
    if not _process_findings(probe, "ffprobe"):
        try:
            parsed_probe = json.loads(str(probe["stdout"]))
            if not isinstance(parsed_probe, dict):
                raise ValueError("ffprobe root is not an object")
            probe_path = movie.parent / "ffprobe.json"
            probe_path.write_text(
                json.dumps(parsed_probe, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            evidence.append(probe_path.relative_to(root).as_posix())
            diagnostics["ffprobe"] = parsed_probe
        except (ValueError, json.JSONDecodeError) as error:
            findings.append(f"ffprobe produced invalid JSON: {error}")

    black = _run_process(
        [
            ffmpeg,
            "-hide_banner",
            "-nostdin",
            "-i",
            str(movie),
            "-vf",
            f"blackdetect=d={ux['blackDurationSeconds']}:pix_th=0.10",
            "-an",
            "-f",
            "null",
            "-",
        ],
        movie.parent,
        timeout,
        artifact_budget_root=movie.parent,
        maximum_artifact_bytes=maximum_artifact_bytes,
    )
    evidence.extend(_write_process_evidence(black, root, f"{movie.parent.name}-blackdetect"))
    findings.extend(_process_findings(black, "black-frame diagnostic"))
    black_segments = _parse_black_segments(f"{black['stdout']}\n{black['stderr']}")
    diagnostics["blackSegments"] = black_segments
    if ux["failOnBlackFrame"] and black_segments:
        findings.append("Native journey contains a governed black video segment")

    freeze = _run_process(
        [
            ffmpeg,
            "-hide_banner",
            "-nostdin",
            "-i",
            str(movie),
            "-vf",
            f"freezedetect=n=0.003:d={ux['freezeDurationSeconds']}",
            "-an",
            "-f",
            "null",
            "-",
        ],
        movie.parent,
        timeout,
        artifact_budget_root=movie.parent,
        maximum_artifact_bytes=maximum_artifact_bytes,
    )
    evidence.extend(_write_process_evidence(freeze, root, f"{movie.parent.name}-freezedetect"))
    findings.extend(_process_findings(freeze, "frozen-video diagnostic"))
    freeze_segments = _parse_freeze_segments(f"{freeze['stdout']}\n{freeze['stderr']}")
    diagnostics["freezeSegments"] = freeze_segments
    if ux["failOnFrozenVideo"] and freeze_segments:
        findings.append("Native journey contains a governed frozen video segment")

    screenshots = movie.parent / "screenshots"
    screenshots.mkdir(parents=True, exist_ok=True)
    extract = _run_process(
        [
            ffmpeg,
            "-hide_banner",
            "-nostdin",
            "-y",
            "-i",
            str(movie),
            "-vf",
            "fps=1,scale=640:-1",
            "-frames:v",
            "8",
            str(screenshots / "frame-%02d.png"),
        ],
        movie.parent,
        timeout,
        artifact_budget_root=movie.parent,
        maximum_artifact_bytes=maximum_artifact_bytes,
    )
    evidence.extend(_write_process_evidence(extract, root, f"{movie.parent.name}-screenshots"))
    findings.extend(_process_findings(extract, "screenshot extraction"))
    frames = sorted(screenshots.glob("frame-*.png"))
    invalid_frames = [path for path in frames if not _validate_png(path)]
    evidence.extend(
        path.relative_to(root).as_posix()
        for path in frames
        if path not in invalid_frames
    )
    if invalid_frames:
        findings.append("One or more extracted screenshots were not valid PNG files")
    if not frames:
        findings.append("No screenshots were extracted from the native journey")

    sheet = movie.parent / "contact-sheet.png"
    contact = _run_process(
        [
            ffmpeg,
            "-hide_banner",
            "-nostdin",
            "-y",
            "-i",
            str(movie),
            "-vf",
            "fps=1,scale=400:-1,tile=3x2:padding=4:margin=4",
            "-frames:v",
            "1",
            str(sheet),
        ],
        movie.parent,
        timeout,
        artifact_budget_root=movie.parent,
        maximum_artifact_bytes=maximum_artifact_bytes,
    )
    evidence.extend(_write_process_evidence(contact, root, f"{movie.parent.name}-contact-sheet"))
    findings.extend(_process_findings(contact, "contact-sheet extraction"))
    if _validate_png(sheet):
        evidence.append(sheet.relative_to(root).as_posix())
    else:
        findings.append("Native journey contact sheet was not created as a valid PNG")

    used_bytes, file_count, complete = _directory_usage(movie.parent)
    diagnostics["artifactUsage"] = {
        "bytes": used_bytes,
        "files": file_count,
        "complete": complete,
        "maximumBytes": maximum_artifact_bytes,
    }
    if not complete or used_bytes > maximum_artifact_bytes:
        findings.append("Native journey evidence exceeded its bounded artifact budget")
    return {
        "status": "passed" if not findings else "failed",
        "findings": sorted(set(findings)),
        "evidence": sorted(set(evidence)),
        "diagnostics": diagnostics,
    }


def _artifact_inventory(
    root: Path,
    *,
    maximum_files: int = _MAX_ARTIFACT_FILES,
    maximum_total_bytes: int | None = None,
) -> list[dict[str, Any]]:
    resolved_root = root.expanduser().resolve(strict=True)
    records: list[dict[str, Any]] = []
    total_bytes = 0
    inspected = 0
    stack = [resolved_root]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as iterator:
                entries = sorted(iterator, key=lambda entry: entry.name.casefold())
        except OSError as error:
            raise NativeQaError(f"Could not inventory retained evidence: {current}") from error
        for entry in reversed(entries):
            inspected += 1
            if inspected > _MAX_ARTIFACT_FILES * 4:
                raise NativeQaError("Retained evidence exceeds its bounded entry-count limit")
            path = Path(entry.path)
            try:
                if entry.is_symlink():
                    raise NativeQaError(
                        f"Retained evidence contains a symbolic link: {path}"
                    )
                if entry.is_dir(follow_symlinks=False):
                    relative_dir = path.relative_to(resolved_root).as_posix()
                    if relative_dir != "work" and not relative_dir.startswith("work/"):
                        stack.append(path)
                    continue
                if not entry.is_file(follow_symlinks=False):
                    raise NativeQaError(
                        f"Retained evidence contains a special filesystem entry: {path}"
                    )
                relative = path.relative_to(resolved_root).as_posix()
                if relative == "native-agent-summary.json":
                    continue
                if len(records) >= maximum_files:
                    raise NativeQaError(
                        "Retained evidence exceeds its bounded file-count limit"
                    )
                size_before = entry.stat(follow_symlinks=False).st_size
                total_bytes += size_before
                if maximum_total_bytes is not None and total_bytes > maximum_total_bytes:
                    raise NativeQaError("Retained evidence exceeds its bounded byte limit")
                digest = _sha256_file(path)
                size_after = path.stat().st_size
                if size_after != size_before:
                    raise NativeQaError(
                        f"Retained evidence changed while it was inventoried: {relative}"
                    )
                records.append(
                    {
                        "path": relative,
                        "bytes": size_before,
                        "sha256": digest,
                    }
                )
            except NativeQaError:
                raise
            except OSError as error:
                raise NativeQaError(
                    f"Could not inspect retained evidence entry: {path}"
                ) from error
    return sorted(records, key=lambda record: str(record["path"]).casefold())
