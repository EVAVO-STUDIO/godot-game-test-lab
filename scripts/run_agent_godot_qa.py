#!/usr/bin/env python3
"""Run the canonical Linux evidence path plus governed interactive journeys."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
PROFILED_RUNNER = HERE / "run_profiled_linux_sandbox.py"
JOURNEY_RUNNER = HERE / "godot_input_journey.gd"
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
PROCESS_OUTPUT_EXCERPT_LIMIT = 4096
BLACK_DURATION_RE = re.compile(r"black_duration:(?P<duration>[0-9.]+)")
FREEZE_DURATION_RE = re.compile(r"freeze_duration: (?P<duration>[0-9.]+)")


class AgentQaError(ValueError):
    pass


def _load_profiled_runner() -> Any:
    spec = importlib.util.spec_from_file_location("profiled_runner", PROFILED_RUNNER)
    if spec is None or spec.loader is None:
        raise AgentQaError(f"Could not import {PROFILED_RUNNER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AgentQaError(f"Could not read {label} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise AgentQaError(f"{label} root must be an object.")
    return value


def _run_process(
    command: list[str],
    cwd: Path,
    timeout: int,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(1, timeout),
            check=False,
        )
        return {
            "command": command,
            "exitCode": completed.returncode,
            "durationSeconds": round(time.monotonic() - started, 3),
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "timedOut": False,
        }
    except subprocess.TimeoutExpired as exc:
        stdout = (
            exc.stdout.decode(errors="replace")
            if isinstance(exc.stdout, bytes)
            else (exc.stdout or "")
        )
        stderr = (
            exc.stderr.decode(errors="replace")
            if isinstance(exc.stderr, bytes)
            else (exc.stderr or "")
        )
        return {
            "command": command,
            "exitCode": None,
            "durationSeconds": round(time.monotonic() - started, 3),
            "stdout": stdout,
            "stderr": stderr,
            "timedOut": True,
        }


def _write_process_logs(result: dict[str, Any], root: Path, stem: str) -> list[str]:
    logs = root / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    stdout_path = logs / f"{stem}.stdout.log"
    stderr_path = logs / f"{stem}.stderr.log"
    stdout_path.write_text(str(result.get("stdout", "")), encoding="utf-8")
    stderr_path.write_text(str(result.get("stderr", "")), encoding="utf-8")
    return [
        stdout_path.relative_to(root).as_posix(),
        stderr_path.relative_to(root).as_posix(),
    ]


def _process_findings(result: dict[str, Any]) -> list[str]:
    findings: list[str] = []
    combined = f"{result.get('stdout', '')}\n{result.get('stderr', '')}".lower()
    for marker in ERROR_MARKERS:
        if marker.lower() in combined:
            findings.append(f"output contains error marker: {marker}")
    if bool(result.get("timedOut", False)):
        findings.append("process exceeded its bounded timeout")
    elif result.get("exitCode") not in (0, None):
        findings.append(f"process exited with code {result.get('exitCode')}")
    return findings


def _process_output_excerpt(result: dict[str, Any]) -> dict[str, str]:
    excerpt: dict[str, str] = {}
    for stream in ("stdout", "stderr"):
        value = str(result.get(stream, "")).strip()
        if not value:
            continue
        if len(value) > PROCESS_OUTPUT_EXCERPT_LIMIT:
            removed = len(value) - PROCESS_OUTPUT_EXCERPT_LIMIT
            value = (
                f"[truncated {removed} characters]\n"
                f"{value[-PROCESS_OUTPUT_EXCERPT_LIMIT:]}"
            )
        excerpt[stream] = value
    return excerpt


def _extract_visual_evidence(
    movie: Path,
    root: Path,
    project_root: Path,
    timeout: int,
    ux: dict[str, Any],
) -> dict[str, Any]:
    findings: list[str] = []
    evidence: list[str] = []
    metrics: dict[str, Any] = {
        "blackSegments": [],
        "freezeSegments": [],
    }
    ffprobe = shutil.which("ffprobe")
    ffmpeg = shutil.which("ffmpeg")
    if not movie.is_file() or movie.stat().st_size <= 0:
        return {
            "status": "failed",
            "findings": ["interactive journey did not produce a movie"],
            "metrics": metrics,
            "evidence": evidence,
        }
    evidence.append(movie.relative_to(root).as_posix())

    if not ffprobe:
        findings.append("ffprobe is unavailable")
    else:
        probe = _run_process(
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
        evidence.extend(_write_process_logs(probe, root, "ffprobe"))
        findings.extend(_process_findings(probe))
        if not _process_findings(probe):
            probe_path = root / "ffprobe.json"
            probe_path.write_text(str(probe.get("stdout", "")), encoding="utf-8")
            evidence.append(probe_path.relative_to(root).as_posix())
            try:
                metrics["probe"] = json.loads(str(probe.get("stdout", "{}")))
            except json.JSONDecodeError:
                findings.append("ffprobe output is not valid JSON")

    if not ffmpeg:
        findings.append("ffmpeg is unavailable")
    else:
        diagnostics = _run_process(
            [
                ffmpeg,
                "-hide_banner",
                "-nostats",
                "-i",
                str(movie),
                "-vf",
                "blackdetect=d=0.5:pix_th=0.10,freezedetect=n=0.003:d=2",
                "-an",
                "-f",
                "null",
                "-",
            ],
            project_root,
            timeout,
        )
        evidence.extend(_write_process_logs(diagnostics, root, "visual-diagnostics"))
        diagnostic_text = (
            f"{diagnostics.get('stdout', '')}\n{diagnostics.get('stderr', '')}"
        )
        black_durations = [
            float(match.group("duration"))
            for match in BLACK_DURATION_RE.finditer(diagnostic_text)
        ]
        freeze_durations = [
            float(match.group("duration"))
            for match in FREEZE_DURATION_RE.finditer(diagnostic_text)
        ]
        metrics["blackSegments"] = black_durations
        metrics["freezeSegments"] = freeze_durations
        if black_durations and bool(ux.get("failOnBlackFrame", True)):
            findings.append("rendered journey contains a sustained black segment")
        if freeze_durations and bool(ux.get("failOnFrozenVideo", False)):
            findings.append("rendered journey contains a sustained frozen segment")

        screenshots = root / "screenshots"
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
            project_root,
            timeout,
        )
        evidence.extend(_write_process_logs(extract, root, "screenshots"))
        findings.extend(_process_findings(extract))
        frames = sorted(screenshots.glob("frame-*.png"))
        if not frames:
            findings.append("no screenshots were extracted from the journey")
        evidence.extend(path.relative_to(root).as_posix() for path in frames)

        contact_sheet = root / "contact-sheet.png"
        sheet = _run_process(
            [
                ffmpeg,
                "-y",
                "-i",
                str(movie),
                "-vf",
                "fps=1,scale=400:-1,tile=3x2:padding=4:margin=4",
                "-frames:v",
                "1",
                str(contact_sheet),
            ],
            project_root,
            timeout,
        )
        evidence.extend(_write_process_logs(sheet, root, "contact-sheet"))
        findings.extend(_process_findings(sheet))
        if contact_sheet.is_file():
            evidence.append(contact_sheet.relative_to(root).as_posix())
        else:
            findings.append("journey contact sheet was not created")

    return {
        "status": "passed" if not findings else "failed",
        "findings": findings,
        "metrics": metrics,
        "evidence": sorted(set(evidence)),
    }


def _run_journey(
    args: argparse.Namespace,
    profile: dict[str, Any],
    journey: dict[str, Any],
    project_root: Path,
    artifacts: Path,
) -> dict[str, Any]:
    journey_id = str(journey["id"])
    root = artifacts / "journeys" / journey_id
    checkpoints = root / "checkpoints"
    root.mkdir(parents=True, exist_ok=True)
    checkpoints.mkdir(parents=True, exist_ok=True)

    harness_root = project_root / ".evavo-lab"
    harness_root.mkdir(parents=True, exist_ok=True)
    harness_script = harness_root / "godot_input_journey.gd"
    shutil.copyfile(JOURNEY_RUNNER, harness_script)
    journey_path = harness_root / f"journey-{journey_id}.json"
    journey_path.write_text(
        json.dumps(journey, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    retained_journey = root / "journey.normalized.json"
    retained_journey.write_text(
        journey_path.read_text(encoding="utf-8"), encoding="utf-8"
    )

    movie = root / "gameplay.avi"
    report = root / "journey-report.json"
    scene = str(journey.get("scene", "") or profile["visual"].get("scene", ""))
    user_arguments = list(journey.get("userArguments", []))
    if not user_arguments:
        user_arguments = list(profile["visual"].get("userArguments", []))
    max_frames = int(journey.get("maxFrames", 900))
    fps = int(profile["visual"].get("fps", 30))
    width = int(profile["visual"].get("width", 1280))
    height = int(profile["visual"].get("height", 720))
    rendering_method = str(
        profile["visual"].get("renderingMethod", "gl_compatibility")
    )
    xvfb = shutil.which("xvfb-run")
    if not xvfb:
        return {
            "id": journey_id,
            "required": bool(journey.get("required", True)),
            "status": "blocked",
            "findings": ["xvfb-run is unavailable"],
            "evidence": [retained_journey.relative_to(artifacts).as_posix()],
        }

    command = [
        xvfb,
        "-a",
        "-s",
        f"-screen 0 {width}x{height}x24 -nolisten tcp",
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
        f"{width}x{height}",
        "--write-movie",
        str(movie),
        "--fixed-fps",
        str(fps),
        "--quit-after",
        str(max_frames + 120),
        "--script",
        "res://.evavo-lab/godot_input_journey.gd",
    ]
    if user_arguments:
        command.append("--")
        command.extend(user_arguments)

    env = os.environ.copy()
    env.update(
        {
            "LIBGL_ALWAYS_SOFTWARE": "1",
            "GALLIUM_DRIVER": "llvmpipe",
            "EVAVO_JOURNEY_PATH": f"res://.evavo-lab/{journey_path.name}",
            "EVAVO_JOURNEY_REPORT": str(report),
            "EVAVO_JOURNEY_CHECKPOINT_ROOT": str(checkpoints),
            "EVAVO_JOURNEY_SCENE": scene,
            "EVAVO_JOURNEY_MAX_FRAMES": str(max_frames),
        }
    )
    process = _run_process(command, project_root, max(30, args.timeout), env)
    process_evidence = _write_process_logs(process, root, "journey")
    process_findings = _process_findings(process)
    findings = list(process_findings)
    process_output_excerpt = (
        _process_output_excerpt(process) if process_findings else {}
    )
    report_value: dict[str, Any] = {}
    if report.is_file():
        try:
            report_value = _load_json_object(report, "journey report")
        except AgentQaError as exc:
            findings.append(str(exc))
    else:
        findings.append("journey report was not produced")
    if report_value.get("status") != "passed":
        for failure in report_value.get("failures", []):
            findings.append(f"journey harness: {failure}")

    visual = _extract_visual_evidence(
        movie,
        root,
        project_root,
        max(30, args.timeout),
        dict(journey.get("ux", {})),
    )
    findings.extend(str(item) for item in visual.get("findings", []))
    evidence = [retained_journey.relative_to(artifacts).as_posix()]
    evidence.extend(f"journeys/{journey_id}/{path}" for path in process_evidence)
    if report.is_file():
        evidence.append(report.relative_to(artifacts).as_posix())
    evidence.extend(
        f"journeys/{journey_id}/{path}" for path in visual.get("evidence", [])
    )
    review = {
        "schemaVersion": "1.0",
        "journeyId": journey_id,
        "status": "passed" if not findings else "failed",
        "device": journey.get("device", "semantic"),
        "syntheticInput": True,
        "hardwareGamepadClaimed": False,
        "scene": scene or "configured main scene",
        "process": {
            "exitCode": process.get("exitCode"),
            "durationSeconds": process.get("durationSeconds"),
            "timedOut": process.get("timedOut"),
            "failureOutputExcerpt": process_output_excerpt,
        },
        "harness": report_value,
        "visual": visual,
        "findings": sorted(set(findings)),
        "evidence": sorted(set(evidence)),
    }
    review_path = root / "visual-ux-review.json"
    review_path.write_text(
        json.dumps(review, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    review["evidence"].append(review_path.relative_to(artifacts).as_posix())
    return {
        "id": journey_id,
        "required": bool(journey.get("required", True)),
        "status": review["status"],
        "device": journey.get("device", "semantic"),
        "syntheticInput": True,
        "hardwareGamepadClaimed": False,
        "findings": review["findings"],
        "evidence": sorted(set(review["evidence"])),
        "processFailureOutputExcerpt": process_output_excerpt,
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    profile = _load_json_object(args.profile, "normalized profile")
    profiled = _load_profiled_runner()
    summary = profiled.run(args)
    summary["schemaVersion"] = "2.0"
    summary["profileSchemaVersion"] = profile.get("schemaVersion", "1.0")
    summary["qualityBoundary"] = {
        "nativeBuildImportExport": True,
        "softwareRenderedVisualEvidence": True,
        "syntheticKeyboardMouseInput": True,
        "syntheticGamepadEvents": True,
        "physicalUsbGamepad": False,
        "subjectiveHumanUxApproval": False,
    }
    journeys: list[dict[str, Any]] = []
    if summary.get("status") == "passed":
        project_root = args.working_root.expanduser().resolve() / Path(
            str(summary.get("projectSubpath", "."))
        )
        for journey_value in profile.get("journeys", []):
            if not isinstance(journey_value, dict):
                continue
            journeys.append(
                _run_journey(
                    args,
                    profile,
                    journey_value,
                    project_root,
                    args.artifacts.expanduser().resolve(),
                )
            )
    summary["journeys"] = journeys
    required_failures = [
        journey
        for journey in journeys
        if bool(journey.get("required", True))
        and journey.get("status") != "passed"
    ]
    optional_failures = [
        journey
        for journey in journeys
        if not bool(journey.get("required", True))
        and journey.get("status") != "passed"
    ]
    findings = list(summary.get("findings", []))
    for journey in required_failures:
        for finding in journey.get("findings", []):
            findings.append(f"journey {journey.get('id')}: {finding}")
    for journey in optional_failures:
        findings.append(f"optional journey {journey.get('id')} did not pass")
    summary["findings"] = sorted(set(findings))
    if required_failures:
        summary["status"] = "failed"
    summary["artifacts"] = profiled._artifact_inventory(
        args.artifacts.expanduser().resolve()
    )
    summary_path = args.artifacts.expanduser().resolve() / "agent-summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--working-root", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
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
    except (AgentQaError, FileNotFoundError, OSError, ValueError) as exc:
        args.artifacts.mkdir(parents=True, exist_ok=True)
        summary = {
            "schemaVersion": "2.0",
            "status": "blocked",
            "error": str(exc),
            "targetRepository": os.environ.get("EVAVO_TARGET_REPOSITORY", ""),
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
