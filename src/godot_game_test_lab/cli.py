from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Sequence

from .core import inspect_project
from .linux_sandbox import run_linux_sandbox
from .pipeline import (
    command_result_payload,
    command_succeeded,
    doctor_payload,
    export_project,
    record_project_movie,
    render_json,
    run_bounded_project,
    validate_project_pipeline,
    write_report_bundle,
)


def _path(value: str | None) -> Path | None:
    return Path(value).expanduser() if value else None


def _write_json(value: object, output: str | None) -> None:
    text = f"{render_json(value)}\n"
    if output:
        destination = Path(output).expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text, encoding="utf-8")
    print(text, end="")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="godot-lab",
        description="EVAVO native Godot build, runtime and evidence worker.",
    )
    parser.add_argument("--version", action="version", version="godot-game-test-lab 0.3.0")
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="Inspect available Godot and .NET tools.")
    doctor.add_argument("--godot")
    doctor.add_argument("--dotnet")
    doctor.add_argument("--output")

    inspect = subparsers.add_parser(
        "inspect", help="Inspect one Godot project without executing it."
    )
    inspect.add_argument("project")
    inspect.add_argument("--output")

    validate = subparsers.add_parser(
        "validate",
        help="Run .NET build when required, Godot import and a bounded headless boot.",
    )
    validate.add_argument("project")
    validate.add_argument("--godot")
    validate.add_argument("--dotnet")
    validate.add_argument("--minimum-godot-version", default="4.6.2")
    validate.add_argument("--timeout", type=int, default=300)
    validate.add_argument("--boot-frames", type=int, default=5)
    validate.add_argument("--artifacts")

    run = subparsers.add_parser("run", help="Launch a bounded native project run.")
    run.add_argument("project")
    run.add_argument("--godot")
    run.add_argument("--scene")
    run.add_argument("--frames", type=int, default=120)
    run.add_argument("--headless", action="store_true")
    run.add_argument("--timeout", type=int, default=300)
    run.add_argument("--output")

    record = subparsers.add_parser(
        "record",
        help="Record deterministic native movie evidence using Godot Movie Maker mode.",
    )
    record.add_argument("project")
    record.add_argument("--godot")
    record.add_argument("--scene")
    record.add_argument("--output", required=True)
    record.add_argument("--frames", type=int, default=300)
    record.add_argument("--fps", type=int, default=30)
    record.add_argument("--timeout", type=int, default=900)
    record.add_argument("--report")

    export = subparsers.add_parser("export", help="Create a Godot debug or release export.")
    export.add_argument("project")
    export.add_argument("--godot")
    export.add_argument("--preset", required=True)
    export.add_argument("--output", required=True)
    export.add_argument("--debug", action="store_true")
    export.add_argument("--timeout", type=int, default=1_800)
    export.add_argument("--report")

    linux = subparsers.add_parser(
        "linux-sandbox",
        help="Run a bounded Linux Godot import, boot, visual capture and optional export.",
    )
    linux.add_argument("source")
    linux.add_argument("--working-root", required=True)
    linux.add_argument("--artifacts", required=True)
    linux.add_argument("--project-subpath", default=".")
    linux.add_argument("--godot", required=True)
    linux.add_argument("--dotnet")
    linux.add_argument("--minimum-godot-version", default="4.6.2")
    linux.add_argument("--timeout", type=int, default=600)
    linux.add_argument("--boot-frames", type=int, default=30)
    linux.add_argument("--visual-frames", type=int, default=180)
    linux.add_argument("--visual-fps", type=int, default=30)
    linux.add_argument("--visual-width", type=int, default=1280)
    linux.add_argument("--visual-height", type=int, default=720)
    linux.add_argument("--export-preset")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        if args.command == "doctor":
            payload = doctor_payload(
                godot_executable=_path(args.godot),
                dotnet_executable=_path(args.dotnet),
            )
            _write_json(payload, args.output)
            return 0 if payload["godot"]["path"] or payload["godotMono"]["path"] else 2

        if args.command == "inspect":
            payload = asdict(inspect_project(Path(args.project)))
            _write_json(payload, args.output)
            return 0

        if args.command == "validate":
            report = validate_project_pipeline(
                Path(args.project),
                godot_executable=_path(args.godot),
                dotnet_executable=_path(args.dotnet),
                minimum_godot_version=args.minimum_godot_version,
                timeout_seconds=max(1, args.timeout),
                boot_frames=max(0, args.boot_frames),
            )
            if args.artifacts:
                write_report_bundle(report, Path(args.artifacts))
            print(f"{report.to_json()}\n", end="")
            return 0 if report.status == "passed" else 2

        if args.command == "run":
            result = run_bounded_project(
                Path(args.project),
                godot_executable=_path(args.godot),
                scene=args.scene,
                frames=max(1, args.frames),
                headless=args.headless,
                timeout_seconds=max(1, args.timeout),
            )
            payload = command_result_payload(result)
            _write_json(payload, args.output)
            return 0 if command_succeeded(result) else 2

        if args.command == "record":
            result = record_project_movie(
                Path(args.project),
                Path(args.output),
                godot_executable=_path(args.godot),
                scene=args.scene,
                frames=max(1, args.frames),
                fps=max(1, args.fps),
                timeout_seconds=max(1, args.timeout),
            )
            payload = {
                "command": command_result_payload(result),
                "movie": str(Path(args.output).expanduser().resolve()),
                "movieExists": Path(args.output).expanduser().resolve().exists(),
            }
            _write_json(payload, args.report)
            return 0 if command_succeeded(result) and payload["movieExists"] else 2

        if args.command == "export":
            result = export_project(
                Path(args.project),
                args.preset,
                Path(args.output),
                godot_executable=_path(args.godot),
                debug=args.debug,
                timeout_seconds=max(1, args.timeout),
            )
            payload = {
                "command": command_result_payload(result),
                "export": str(Path(args.output).expanduser().resolve()),
                "exportExists": Path(args.output).expanduser().resolve().exists(),
            }
            _write_json(payload, args.report)
            return 0 if command_succeeded(result) and payload["exportExists"] else 2

        if args.command == "linux-sandbox":
            report = run_linux_sandbox(
                Path(args.source),
                working_root=Path(args.working_root),
                artifacts_root=Path(args.artifacts),
                project_subpath=args.project_subpath,
                godot_executable=Path(args.godot),
                dotnet_executable=_path(args.dotnet),
                minimum_godot_version=args.minimum_godot_version,
                timeout_seconds=max(1, args.timeout),
                boot_frames=max(0, args.boot_frames),
                visual_frames=max(0, args.visual_frames),
                visual_fps=max(1, args.visual_fps),
                visual_width=max(320, args.visual_width),
                visual_height=max(180, args.visual_height),
                export_preset=args.export_preset,
            )
            print(f"{report.to_json()}\n", end="")
            return 0 if report.status == "passed" else 2
    except (FileNotFoundError, ValueError, OSError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "blocked", "error": str(error)}, indent=2), file=sys.stderr)
        return 2

    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
