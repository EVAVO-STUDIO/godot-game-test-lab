from __future__ import annotations

import ctypes
import os
import shutil
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .native_qa_common import (
    _process_findings,
    _run_process,
    _sha256_file,
    _write_process_evidence,
)


def _interactive_session() -> dict[str, Any]:
    result: dict[str, Any] = {
        "platform": os.name,
        "sessionName": os.environ.get("SESSIONNAME", ""),
        "sessionId": None,
        "interactive": False,
    }
    if os.name != "nt":
        return result
    session_id = ctypes.c_uint32()
    ok = ctypes.windll.kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(session_id))
    if ok:
        result["sessionId"] = int(session_id.value)
    name = str(result["sessionName"]).casefold()
    result["interactive"] = bool(ok and session_id.value != 0 and name != "services")
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
        "session": _interactive_session(),
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
        "truthBoundary": (
            "Adapter, Vulkan, NVIDIA and CUDA probes are environment evidence. They do not "
            "prove that a particular Godot frame rendered on a selected adapter."
        ),
    }
    if os.name == "nt":
        evidence["windowsVideoControllers"] = _probe(
            [
                "powershell",
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


def _extract_video_evidence(movie: Path, root: Path, timeout: int) -> dict[str, Any]:
    findings: list[str] = []
    evidence: list[str] = []
    if not movie.is_file() or movie.stat().st_size <= 0:
        return {
            "status": "failed",
            "findings": ["Godot Movie Maker did not produce a non-empty movie"],
            "evidence": [],
        }
    evidence.append(movie.relative_to(root).as_posix())
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        findings.append("ffmpeg and ffprobe are required for native visual evidence extraction")
        return {"status": "blocked", "findings": findings, "evidence": evidence}

    probe = _run_process(
        [ffprobe, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(movie)],
        movie.parent,
        timeout,
    )
    evidence.extend(_write_process_evidence(probe, root, f"{movie.parent.name}-ffprobe"))
    findings.extend(_process_findings(probe, "ffprobe"))
    if not findings:
        probe_path = movie.parent / "ffprobe.json"
        probe_path.write_text(str(probe["stdout"]), encoding="utf-8")
        evidence.append(probe_path.relative_to(root).as_posix())

    screenshots = movie.parent / "screenshots"
    screenshots.mkdir(parents=True, exist_ok=True)
    extract = _run_process(
        [
            ffmpeg,
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
    )
    evidence.extend(_write_process_evidence(extract, root, f"{movie.parent.name}-screenshots"))
    findings.extend(_process_findings(extract, "screenshot extraction"))
    frames = sorted(screenshots.glob("frame-*.png"))
    evidence.extend(path.relative_to(root).as_posix() for path in frames)
    if not frames:
        findings.append("No screenshots were extracted from the native journey")

    sheet = movie.parent / "contact-sheet.png"
    contact = _run_process(
        [
            ffmpeg,
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
    )
    evidence.extend(_write_process_evidence(contact, root, f"{movie.parent.name}-contact-sheet"))
    findings.extend(_process_findings(contact, "contact-sheet extraction"))
    if sheet.is_file():
        evidence.append(sheet.relative_to(root).as_posix())
    else:
        findings.append("Native journey contact sheet was not created")
    return {
        "status": "passed" if not findings else "failed",
        "findings": sorted(set(findings)),
        "evidence": sorted(set(evidence)),
    }


def _artifact_inventory(root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(root).as_posix()
        if relative == "native-agent-summary.json" or relative.startswith("work/"):
            continue
        records.append(
            {
                "path": relative,
                "bytes": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )
    return records
