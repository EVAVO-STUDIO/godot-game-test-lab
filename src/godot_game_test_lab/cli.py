from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from . import __version__
from .core import inspect_project
from .integrity import AuditLimits, audit_project, execution_blocking_findings
from .linux_sandbox import run_linux_sandbox, safe_project_subpath
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
    parser.add_argument(
        "--version",
        action="version",
        version=f"godot-game-test-lab {__version__}",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    capabilities = subparsers.add_parser(
        "capabilities",
        help="Describe the stable automation, evidence and truth-boundary surface.",
    )
    capabilities.add_argument("--output")

    doctor = subparsers.add_parser("doctor", help="Inspect available Godot and .NET tools.")
    doctor.add_argument("--godot")
    doctor.add_argument("--dotnet")
    doctor.add_argument("--output")

    inspect = subparsers.add_parser(
        "inspect", help="Inspect one Godot project without executing it."
    )
    inspect.add_argument("project")
    inspect.add_argument("--output")

    defaults = AuditLimits()
    audit = subparsers.add_parser(
        "audit",
        help="Statically audit project, scene, resource, path, Git and export integrity.",
    )
    audit.add_argument("project")
    audit.add_argument("--output")
    audit.add_argument("--max-files", type=int, default=defaults.max_files)
    audit.add_argument(
        "--max-total-mib", type=int, default=defaults.max_total_bytes // (1024 * 1024)
    )
    audit.add_argument(
        "--max-text-file-mib",
        type=int,
        default=defaults.max_text_file_bytes // (1024 * 1024),
    )
    audit.add_argument("--max-findings", type=int, default=defaults.max_findings)
    audit.add_argument("--warnings-as-errors", action="store_true")

    validate = subparsers.add_parser(
        "validate",
        help=(
            "Run static integrity, .NET build when required, authoritative Godot import, "
            "recovery diagnosis and a bounded headless boot."
        ),
    )
    validate.add_argument("project")
    validate.add_argument("--godot")
    validate.add_argument("--dotnet")
    validate.add_argument("--minimum-godot-version", default="4.6.2")
    validate.add_argument("--timeout", type=int, default=300)
    validate.add_argument("--boot-frames", type=int, default=5)
    validate.add_argument("--artifacts")
    validate.add_argument("--skip-integrity-audit", action="store_true")
    validate.add_argument("--warnings-as-errors", action="store_true")
    validate.add_argument("--no-recovery-diagnostic", action="store_true")
    validate.add_argument(
        "--allow-major-upgrade",
        action="store_true",
        help="Permit a later Godot major version instead of requiring the same major.",
    )

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
    linux.add_argument("--warnings-as-errors", action="store_true")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        if args.command == "capabilities":
            payload = {
                "schemaVersion": "1.1",
                "tool": "godot-game-test-lab",
                "toolVersion": __version__,
                "minimumGodotVersion": "4.6.2",
                "projectSelection": "absolute or relative path to an external Godot repository",
                "commands": [
                    "audit",
                    "capabilities",
                    "doctor",
                    "export",
                    "inspect",
                    "linux-sandbox",
                    "record",
                    "run",
                    "validate",
                ],
                "automationEntrypoints": {
                    "profileBootstrap": "godot-lab-init-qa",
                    "nativeAuthoredQa": "godot-lab-native-qa",
                    "nativeBotQa": "godot-lab-bot-qa",
                    "nativeValidationWrapper": (
                        "scripts/Invoke-GodotLabNativeValidation.ps1"
                    ),
                    "nativeAuthoredQaWrapper": (
                        "scripts/Invoke-GodotLabNativeAgentQA.ps1"
                    ),
                    "nativeBotQaWrapper": "scripts/Invoke-GodotLabBotQA.ps1",
                    "linuxWorkflow": (
                        ".github/workflows/reusable-godot-linux-sandbox.yml"
                    ),
                },
                "validationStages": [
                    "bounded static integrity audit",
                    "Godot version and editor-capability verification",
                    ".NET build for C# projects",
                    "authoritative Godot --import",
                    "recovery-mode import diagnosis after normal import failure",
                    "bounded headless boot",
                    "target-authored native visual and input journeys",
                    "deterministic fresh-process bot state exploration",
                ],
                "evidence": [
                    "report.json",
                    "integrity-report.json",
                    "structured finding code, category, repair action and bounded evidence",
                    "separate stdout and stderr logs",
                    "Godot engine log files",
                    "native-agent-summary.json",
                    "bot-agent-summary.json",
                    "run-context.json and source-archive.json",
                    "deterministic state graphs and exact replay traces",
                    "screenshots, checkpoints, movies and contact sheets",
                    "InputMap, UI geometry and bounded performance telemetry",
                    "Linux journey movies, screenshots and telemetry when configured",
                ],
                "truthBoundaries": [
                    "static findings are diagnostics; Godot import is authoritative "
                    "for engine parsing",
                    "recovery-mode success identifies a suspected disabled editor "
                    "execution surface",
                    "deterministic bot exploration is bounded and does not prove every "
                    "game state",
                    "synthetic input proves Godot event routing, not physical controller "
                    "behavior",
                    "headless validation is not visual quality or game-feel approval",
                    "Linux software rendering is not native Windows GPU performance evidence",
                    "native visual evidence requires the logged-in interactive Windows session",
                    "the lab diagnoses target repositories but does not repair or publish them",
                ],
            }
            _write_json(payload, args.output)
            return 0

        if args.command == "doctor":
            payload = doctor_payload(
                godot_executable=_path(args.godot),
                dotnet_executable=_path(args.dotnet),
            )
            _write_json(payload, args.output)
            return 0 if (
                payload["godot"]["editorCompatible"]
                or payload["godotMono"]["editorCompatible"]
            ) else 2

        if args.command == "inspect":
            payload = asdict(inspect_project(Path(args.project)))
            _write_json(payload, args.output)
            return 0

        if args.command == "audit":
            report = audit_project(
                Path(args.project),
                limits=AuditLimits(
                    max_files=args.max_files,
                    max_total_bytes=args.max_total_mib * 1024 * 1024,
                    max_text_file_bytes=args.max_text_file_mib * 1024 * 1024,
                    max_findings=args.max_findings,
                ),
            )
            passed = report.status == "passed" and (
                not args.warnings_as_errors or report.warnings == 0
            )
            payload = report.to_dict()
            payload["warnings_as_errors"] = args.warnings_as_errors
            payload["policy_status"] = "passed" if passed else "failed"
            _write_json(payload, args.output)
            return 0 if passed else 2

        if args.command == "validate":
            artifact_root = _path(args.artifacts)
            report = validate_project_pipeline(
                Path(args.project),
                godot_executable=_path(args.godot),
                dotnet_executable=_path(args.dotnet),
                minimum_godot_version=args.minimum_godot_version,
                timeout_seconds=max(1, args.timeout),
                boot_frames=max(0, args.boot_frames),
                run_integrity_audit=not args.skip_integrity_audit,
                warnings_as_errors=args.warnings_as_errors,
                recovery_diagnostic=not args.no_recovery_diagnostic,
                allow_major_upgrade=args.allow_major_upgrade,
                log_directory=(artifact_root / "engine-logs") if artifact_root else None,
            )
            if artifact_root:
                write_report_bundle(report, artifact_root)
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
            source_root = Path(args.source).expanduser().resolve()
            relative_project = safe_project_subpath(args.project_subpath)
            artifact_root = Path(args.artifacts).expanduser().resolve()
            artifact_root.mkdir(parents=True, exist_ok=True)
            integrity = audit_project(source_root / relative_project)
            integrity_path = artifact_root / "integrity-report.json"
            integrity_path.write_text(f"{integrity.to_json()}\n", encoding="utf-8")
            execution_blockers = execution_blocking_findings(integrity)
            if integrity.findings_truncated:
                execution_blockers = [*execution_blockers, None]
            if execution_blockers:
                blocker_codes = sorted(
                    {
                        finding.code if finding is not None else "limits.findings_truncated"
                        for finding in execution_blockers
                    }
                )
                payload = {
                    "schema_version": "1.1",
                    "status": "blocked",
                    "project_subpath": args.project_subpath,
                    "findings": [
                        "Static integrity evidence is incomplete or unsafe for Godot execution.",
                        "Execution blockers: " + ", ".join(blocker_codes),
                    ],
                    "artifacts": ["integrity-report.json"],
                }
                report_path = artifact_root / "sandbox-report.json"
                report_path.write_text(
                    json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
                print(json.dumps(payload, indent=2, ensure_ascii=False))
                return 2

            report = run_linux_sandbox(
                source_root,
                working_root=Path(args.working_root),
                artifacts_root=artifact_root,
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
            integrity_failed = integrity.errors > 0 or (
                args.warnings_as_errors and integrity.warnings > 0
            )
            summary = (
                f"static-integrity: {integrity.errors} error(s), "
                f"{integrity.warnings} warning(s)"
            )
            report.findings.insert(0, summary)
            if "integrity-report.json" not in report.artifacts:
                report.artifacts.append("integrity-report.json")
            if integrity_failed and report.status == "passed":
                report.status = "failed"
            report_path = artifact_root / "sandbox-report.json"
            report_path.write_text(f"{report.to_json()}\n", encoding="utf-8")
            print(f"{report.to_json()}\n", end="")
            return 0 if report.status == "passed" and not integrity_failed else 2
    except (FileNotFoundError, ValueError, OSError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "blocked", "error": str(error)}, indent=2), file=sys.stderr)
        return 2

    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
