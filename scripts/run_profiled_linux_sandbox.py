#!/usr/bin/env python3
"""Run the canonical Linux sandbox plus a governed rendered Godot journey."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from collections.abc import Iterable
from dataclasses import asdict
from pathlib import Path
from typing import Any

ERROR_MARKERS = (
    "ERROR:",
    "SCRIPT ERROR:",
    "Parse Error",
    "Build FAILED",
    "Unhandled exception",
    "Failed to load script",
    "Cannot open file",
    "ASSERTION FAILED",
)
ALLOWED_RENDERING_METHODS = {"gl_compatibility", "mobile", "forward_plus"}
MAX_ARGUMENTS = 32
MAX_ARGUMENT_BYTES = 256


class JourneyError(ValueError):
    pass


def _reject_duplicate_keys(
    pairs: Iterable[tuple[str, Any]],
) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise JourneyError(f"Duplicate JSON key is not allowed: {key!r}")
        value[key] = item
    return value


def _reject_non_finite(value: str) -> None:
    raise JourneyError(f"Non-finite JSON number is not allowed: {value}")


def parse_user_arguments(value: str) -> list[str]:
    if not value.strip():
        return []
    try:
        parsed = json.loads(
            value,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite,
        )
    except JourneyError:
        raise
    except json.JSONDecodeError as exc:
        raise JourneyError(f"visual user arguments are invalid JSON: {exc}") from exc
    if not isinstance(parsed, list):
        raise JourneyError("visual user arguments must be a JSON array.")
    if len(parsed) > MAX_ARGUMENTS:
        raise JourneyError(f"visual user arguments may contain at most {MAX_ARGUMENTS} values.")

    result: list[str] = []
    for index, item in enumerate(parsed):
        if not isinstance(item, str):
            raise JourneyError(f"visual user argument {index} must be a string.")
        if (
            not item.startswith("--")
            or "\x00" in item
            or "\n" in item
            or "\r" in item
            or len(item.encode("utf-8")) > MAX_ARGUMENT_BYTES
        ):
            raise JourneyError(f"visual user argument {index} must be a bounded --prefixed value.")
        result.append(item)
    return result


def safe_scene(value: str) -> str:
    scene = value.strip()
    if not scene:
        return ""
    if not scene.startswith("res://") or "\\" in scene or "\n" in scene or "\r" in scene:
        raise JourneyError("visual scene must be empty or a canonical res:// path.")
    parts = scene[6:].split("/")
    if not parts or any(part in ("", ".", "..") for part in parts):
        raise JourneyError("visual scene must be empty or a canonical res:// path.")
    return "res://" + "/".join(parts)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_command_logs(
    result: Any,
    artifacts: Path,
    name: str,
) -> list[str]:
    logs = artifacts / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    stdout_path = logs / f"{name}.stdout.log"
    stderr_path = logs / f"{name}.stderr.log"
    stdout_path.write_text(str(result.stdout), encoding="utf-8")
    stderr_path.write_text(str(result.stderr), encoding="utf-8")
    return [
        stdout_path.relative_to(artifacts).as_posix(),
        stderr_path.relative_to(artifacts).as_posix(),
    ]


def _command_findings(result: Any) -> list[str]:
    findings: list[str] = []
    combined = f"{result.stdout}\n{result.stderr}".lower()
    for marker in ERROR_MARKERS:
        if marker.lower() in combined:
            findings.append(f"output contains error marker: {marker}")
    if bool(result.timed_out):
        findings.append(f"timed out after {result.duration_seconds} seconds")
    elif result.exit_code != 0:
        findings.append(f"exited with code {result.exit_code}")
    return findings


def _artifact_inventory(root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == "agent-summary.json":
            continue
        records.append(
            {
                "path": path.relative_to(root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return records


def _append_check(
    checks: list[dict[str, Any]],
    findings: list[str],
    check: dict[str, Any],
) -> None:
    checks.append(check)
    check_id = str(check.get("id", "check"))
    for finding in check.get("findings", []):
        findings.append(f"{check_id}: {finding}")


def _run_visual_probe(
    movie: Path,
    project_root: Path,
    artifacts: Path,
    timeout: int,
) -> dict[str, Any]:
    from godot_game_test_lab.core import run_command

    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return {
            "id": "visual-probe",
            "status": "blocked",
            "findings": ["ffprobe is unavailable"],
        }

    result = run_command(
        [
            ffprobe,
            "-v",
            "error",
            "-show_format",
            "-show_streams",
            "-of",
            "json",
            str(movie),
        ],
        project_root,
        timeout,
    )
    probe_findings = _command_findings(result)
    probe_path = artifacts / "visual" / "ffprobe.json"
    if not probe_findings:
        probe_path.write_text(result.stdout, encoding="utf-8")
    evidence = _write_command_logs(
        result,
        artifacts,
        "profiled-visual-probe",
    )
    if probe_path.is_file():
        evidence.append(probe_path.relative_to(artifacts).as_posix())
    return {
        "id": "visual-probe",
        "status": "passed" if not probe_findings else "failed",
        "findings": probe_findings,
        "evidence": evidence,
    }


def _run_screenshot_extraction(
    movie: Path,
    project_root: Path,
    artifacts: Path,
    timeout: int,
) -> list[dict[str, Any]]:
    from godot_game_test_lab.core import run_command

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return [
            {
                "id": "visual-screenshots",
                "status": "blocked",
                "findings": ["ffmpeg is unavailable"],
            },
            {
                "id": "visual-contact-sheet",
                "status": "blocked",
                "findings": ["ffmpeg is unavailable"],
            },
        ]

    visual = artifacts / "visual"
    screenshots = visual / "screenshots"
    screenshots.mkdir(parents=True, exist_ok=True)
    extract = run_command(
        [
            ffmpeg,
            "-y",
            "-i",
            str(movie),
            "-vf",
            "fps=1,scale=640:-1",
            "-frames:v",
            "6",
            str(screenshots / "frame-%02d.png"),
        ],
        project_root,
        timeout,
    )
    extract_findings = _command_findings(extract)
    frames = sorted(screenshots.glob("frame-*.png"))
    if not frames:
        extract_findings.append("no individual screenshots were extracted")
    extract_evidence = _write_command_logs(
        extract,
        artifacts,
        "profiled-visual-screenshots",
    )
    extract_evidence.extend(path.relative_to(artifacts).as_posix() for path in frames)

    contact = visual / "contact-sheet.png"
    sheet = run_command(
        [
            ffmpeg,
            "-y",
            "-i",
            str(movie),
            "-vf",
            "fps=1,scale=400:-1,tile=3x2:padding=4:margin=4",
            "-frames:v",
            "1",
            str(contact),
        ],
        project_root,
        timeout,
    )
    sheet_findings = _command_findings(sheet)
    if not contact.is_file():
        sheet_findings.append("contact sheet was not created")
    sheet_evidence = _write_command_logs(
        sheet,
        artifacts,
        "profiled-visual-contact-sheet",
    )
    if contact.is_file():
        sheet_evidence.append(contact.relative_to(artifacts).as_posix())

    return [
        {
            "id": "visual-screenshots",
            "status": "passed" if not extract_findings else "failed",
            "findings": extract_findings,
            "evidence": extract_evidence,
        },
        {
            "id": "visual-contact-sheet",
            "status": "passed" if not sheet_findings else "failed",
            "findings": sheet_findings,
            "evidence": sheet_evidence,
        },
    ]


def _run_rendered_journey(
    args: argparse.Namespace,
    project_root: Path,
    artifacts: Path,
    scene: str,
    user_arguments: list[str],
    rendering_method: str,
) -> tuple[dict[str, Any], Path]:
    from godot_game_test_lab.core import run_command

    visual = artifacts / "visual"
    visual.mkdir(parents=True, exist_ok=True)
    movie = visual / "gameplay.avi"
    xvfb = shutil.which("xvfb-run")
    if not xvfb:
        return (
            {
                "id": "governed-rendered-journey",
                "status": "blocked",
                "findings": ["xvfb-run is unavailable"],
            },
            movie,
        )

    command = [
        "/usr/bin/env",
        "LIBGL_ALWAYS_SOFTWARE=1",
        "GALLIUM_DRIVER=llvmpipe",
        xvfb,
        "-a",
        "-s",
        (f"-screen 0 {args.visual_width}x{args.visual_height}x24 -nolisten tcp"),
        str(args.godot),
        "--path",
        str(project_root),
        "--display-driver",
        "x11",
        "--audio-driver",
        "Dummy",
        "--rendering-method",
        rendering_method,
        "--windowed",
        "--resolution",
        f"{args.visual_width}x{args.visual_height}",
        "--write-movie",
        str(movie),
        "--fixed-fps",
        str(args.visual_fps),
        "--quit-after",
        str(args.visual_frames),
    ]
    if scene:
        command.extend(["--scene", scene])
    if user_arguments:
        command.append("--")
        command.extend(user_arguments)

    result = run_command(
        command,
        project_root,
        max(1, args.timeout),
    )
    journey_findings = _command_findings(result)
    evidence = _write_command_logs(
        result,
        artifacts,
        "governed-rendered-journey",
    )
    if not movie.is_file() or movie.stat().st_size <= 0:
        journey_findings.append("Godot Movie Maker did not produce gameplay.avi")
    else:
        evidence.append(movie.relative_to(artifacts).as_posix())

    return (
        {
            "id": "governed-rendered-journey",
            "status": "passed" if not journey_findings else "failed",
            "command": asdict(result),
            "scene": scene or "configured main scene",
            "userArguments": user_arguments,
            "renderingMethod": rendering_method,
            "findings": journey_findings,
            "evidence": evidence,
        },
        movie,
    )


def run(args: argparse.Namespace) -> dict[str, Any]:
    from godot_game_test_lab.linux_sandbox import run_linux_sandbox

    source = args.source.expanduser().resolve()
    working = args.working_root.expanduser().resolve()
    artifacts = args.artifacts.expanduser().resolve()
    artifacts.mkdir(parents=True, exist_ok=True)

    scene = safe_scene(args.visual_scene)
    user_arguments = parse_user_arguments(args.visual_arguments_json)
    rendering_method = args.rendering_method.strip()
    if rendering_method not in ALLOWED_RENDERING_METHODS:
        raise JourneyError("rendering method must be gl_compatibility, mobile, or forward_plus.")

    base = run_linux_sandbox(
        source,
        working_root=working,
        artifacts_root=artifacts,
        project_subpath=args.project_subpath,
        godot_executable=args.godot,
        dotnet_executable=args.dotnet,
        minimum_godot_version=args.minimum_godot_version,
        timeout_seconds=max(1, args.timeout),
        boot_frames=max(0, args.boot_frames),
        visual_frames=0,
        export_preset=args.export_preset or None,
    )

    checks: list[dict[str, Any]] = []
    findings: list[str] = []
    _append_check(
        checks,
        findings,
        {
            "id": "base-linux-validation",
            "status": base.status,
            "findings": list(base.findings),
            "report": "sandbox-report.json",
        },
    )

    if base.status == "passed" and args.visual_frames > 0:
        project_root = working / Path(base.project_subpath)
        journey, movie = _run_rendered_journey(
            args,
            project_root,
            artifacts,
            scene,
            user_arguments,
            rendering_method,
        )
        _append_check(checks, findings, journey)
        if movie.is_file() and movie.stat().st_size > 0:
            _append_check(
                checks,
                findings,
                _run_visual_probe(
                    movie,
                    project_root,
                    artifacts,
                    max(1, args.timeout),
                ),
            )
            for check in _run_screenshot_extraction(
                movie,
                project_root,
                artifacts,
                max(1, args.timeout),
            ):
                _append_check(checks, findings, check)

    required_statuses = [str(check.get("status", "failed")) for check in checks]
    status = (
        "passed"
        if required_statuses and all(item == "passed" for item in required_statuses)
        else "failed"
    )
    summary = {
        "schemaVersion": "1.0",
        "status": status,
        "targetRepository": os.environ.get(
            "EVAVO_TARGET_REPOSITORY",
            "",
        ),
        "targetSha": os.environ.get("EVAVO_TARGET_SHA", ""),
        "labSha": os.environ.get("EVAVO_LAB_SHA", ""),
        "projectSubpath": base.project_subpath,
        "minimumGodotVersion": args.minimum_godot_version,
        "visual": {
            "scene": scene or "configured main scene",
            "frames": args.visual_frames,
            "fps": args.visual_fps,
            "width": args.visual_width,
            "height": args.visual_height,
            "renderingMethod": rendering_method,
            "userArguments": user_arguments,
        },
        "sandboxControls": {
            "network": "none",
            "targetMount": "read-only",
            "workingCopy": "ephemeral",
            "rootFilesystem": "read-only",
            "capabilities": "all-dropped",
            "noNewPrivileges": True,
            "softwareRenderer": "mesa-llvmpipe",
            "display": "xvfb-x11",
        },
        "checks": checks,
        "findings": findings,
    }
    summary["artifacts"] = _artifact_inventory(artifacts)
    (artifacts / "agent-summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--working-root", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--project-subpath", default=".")
    parser.add_argument("--godot", type=Path, required=True)
    parser.add_argument("--dotnet", type=Path)
    parser.add_argument("--minimum-godot-version", default="4.6.2")
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--boot-frames", type=int, default=30)
    parser.add_argument("--visual-scene", default="")
    parser.add_argument("--visual-frames", type=int, default=180)
    parser.add_argument("--visual-fps", type=int, default=30)
    parser.add_argument("--visual-width", type=int, default=1280)
    parser.add_argument("--visual-height", type=int, default=720)
    parser.add_argument("--rendering-method", default="gl_compatibility")
    parser.add_argument("--visual-arguments-json", default="[]")
    parser.add_argument("--export-preset", default="")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        summary = run(args)
    except (JourneyError, FileNotFoundError, OSError, ValueError) as exc:
        args.artifacts.mkdir(parents=True, exist_ok=True)
        summary = {
            "schemaVersion": "1.0",
            "status": "blocked",
            "error": str(exc),
            "targetRepository": os.environ.get(
                "EVAVO_TARGET_REPOSITORY",
                "",
            ),
            "targetSha": os.environ.get("EVAVO_TARGET_SHA", ""),
            "labSha": os.environ.get("EVAVO_LAB_SHA", ""),
        }
        (args.artifacts / "agent-summary.json").write_text(
            json.dumps(summary, indent=2) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(summary, sort_keys=True))
        return 2
    print(json.dumps(summary, sort_keys=True))
    return 0 if summary.get("status") == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
