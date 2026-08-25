from __future__ import annotations

import argparse
import json
import os
import re
import threading
from dataclasses import asdict
from pathlib import Path, PurePosixPath
from typing import Any

from .asset_audit_io import paths_overlap, read_git_state
from .core import find_project_root, run_command
from .pipeline import discover_godot_binary
from .sprite_animation_runtime_admission import (
    admit_sprite_animation_runtime,
    compile_sprite_animation_runtime_evidence,
)
from .sprite_animation_runtime_cli import _write_create_only

HEAD40 = re.compile(r"^[0-9a-f]{40}$")
_ENV_LOCK = threading.Lock()
_ENV_KEYS = (
    "EVAVO_SPRITE_ANIMATION_RAW_TELEMETRY",
    "EVAVO_SPRITE_ANIMATION_RESOURCE",
    "EVAVO_SPRITE_ANIMATION_CLIP",
    "EVAVO_SPRITE_ANIMATION_CYCLES",
)


def _res_path(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.startswith("res://") or "\\" in value:
        raise ValueError(f"{label} must be a canonical res:// path")
    relative = value.removeprefix("res://")
    parsed = PurePosixPath(relative)
    if not relative or parsed.is_absolute() or any(part in {"", ".", ".."} for part in parsed.parts):
        raise ValueError(f"{label} must not contain traversal")
    return value


def _inside_resource(root: Path, res_path: str, label: str) -> Path:
    relative = PurePosixPath(_res_path(res_path, label).removeprefix("res://"))
    candidate = root.joinpath(*relative.parts).resolve(strict=True)
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise ValueError(f"{label} escaped the target project") from error
    if candidate.is_symlink() or not candidate.is_file():
        raise ValueError(f"{label} must resolve to a regular target file")
    return candidate


def _external_output(root: Path, value: Path, label: str) -> Path:
    destination = value.expanduser().resolve()
    if not destination.is_absolute():
        raise ValueError(f"{label} must be absolute")
    if paths_overlap(destination, root):
        raise ValueError(f"{label} must remain outside the target project")
    if destination.exists():
        raise ValueError(f"{label} already exists; probe evidence is create-only")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if paths_overlap(destination.parent.resolve(), root):
        raise ValueError(f"{label} parent overlaps the target project")
    return destination


def _read_json_object(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return value


def run_sprite_animation_probe(
    *,
    project: Path,
    expected_target_sha: str,
    expectation_path: Path,
    scene: str,
    resource: str,
    clip: str,
    raw_output: Path,
    evidence_output: Path,
    report_output: Path,
    godot_executable: Path | None = None,
    cycles: int = 2,
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    root = find_project_root(project)
    git_state = read_git_state(root)
    expected = expected_target_sha.strip().lower()
    if not HEAD40.fullmatch(expected):
        raise ValueError("expected-target-sha must be a lowercase 40-character Git SHA")
    if not git_state.available or git_state.target_sha != expected:
        raise ValueError("target checkout HEAD differs from expected-target-sha")
    if git_state.dirty:
        raise ValueError("target checkout must be clean for authoritative sprite-animation evidence")

    _inside_resource(root, scene, "scene")
    _inside_resource(root, resource, "resource")
    if not isinstance(clip, str) or not clip.strip() or clip != clip.strip() or len(clip) > 256:
        raise ValueError("clip must be a non-empty trimmed string up to 256 characters")
    if isinstance(cycles, bool) or not isinstance(cycles, int) or cycles < 1 or cycles > 8:
        raise ValueError("cycles must be an integer from 1 to 8")
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int) or timeout_seconds < 1 or timeout_seconds > 300:
        raise ValueError("timeout-seconds must be an integer from 1 to 300")

    raw_path = _external_output(root, raw_output, "raw-output")
    evidence_path = _external_output(root, evidence_output, "evidence-output")
    report_path = _external_output(root, report_output, "report-output")
    if len({raw_path, evidence_path, report_path}) != 3:
        raise ValueError("raw, evidence and report outputs must be distinct")

    expectation = _read_json_object(expectation_path.resolve(strict=True), "expectation")
    executable = discover_godot_binary(godot_executable, requires_mono=False)
    if executable is None:
        raise ValueError("Godot executable could not be resolved")

    overrides = {
        "EVAVO_SPRITE_ANIMATION_RAW_TELEMETRY": str(raw_path),
        "EVAVO_SPRITE_ANIMATION_RESOURCE": resource,
        "EVAVO_SPRITE_ANIMATION_CLIP": clip,
        "EVAVO_SPRITE_ANIMATION_CYCLES": str(cycles),
    }
    with _ENV_LOCK:
        previous = {key: os.environ.get(key) for key in _ENV_KEYS}
        try:
            os.environ.update(overrides)
            command = run_command(
                [str(executable), "--path", str(root), scene],
                root,
                timeout_seconds,
            )
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    if command.timed_out:
        raise ValueError("Godot sprite-animation probe timed out")
    if command.exit_code != 0:
        raise ValueError(f"Godot sprite-animation probe exited with code {command.exit_code}")
    if not raw_path.is_file():
        raise ValueError("Godot sprite-animation probe did not create raw telemetry")

    raw = _read_json_object(raw_path, "raw telemetry")
    evidence = compile_sprite_animation_runtime_evidence(
        raw,
        expectation.get("expectationSha256"),
    )
    report = admit_sprite_animation_runtime(expectation, evidence)
    _write_create_only(evidence_path, evidence)
    _write_create_only(report_path, report)

    return {
        "status": report["status"],
        "targetSha": expected,
        "projectRoot": str(root),
        "godotExecutable": str(executable),
        "command": asdict(command),
        "rawTelemetry": str(raw_path),
        "runtimeEvidence": str(evidence_path),
        "runtimeAdmission": str(report_path),
        "expectationSha256": report["expectationSha256"],
        "runtimeEvidenceSha256": report["runtimeEvidenceSha256"],
        "reportSha256": report["reportSha256"],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="godot-lab-sprite-animation-probe",
        description="Run a target-owned AnimatedSprite2D probe and admit its exact runtime evidence.",
    )
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--expected-target-sha", required=True)
    parser.add_argument("--expectation", type=Path, required=True)
    parser.add_argument("--scene", required=True)
    parser.add_argument("--resource", required=True)
    parser.add_argument("--clip", required=True)
    parser.add_argument("--raw-output", type=Path, required=True)
    parser.add_argument("--evidence-output", type=Path, required=True)
    parser.add_argument("--report-output", type=Path, required=True)
    parser.add_argument("--godot", type=Path)
    parser.add_argument("--cycles", type=int, default=2)
    parser.add_argument("--timeout-seconds", type=int, default=30)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = run_sprite_animation_probe(
            project=args.project,
            expected_target_sha=args.expected_target_sha,
            expectation_path=args.expectation,
            scene=args.scene,
            resource=args.resource,
            clip=args.clip,
            raw_output=args.raw_output,
            evidence_output=args.evidence_output,
            report_output=args.report_output,
            godot_executable=args.godot,
            cycles=args.cycles,
            timeout_seconds=args.timeout_seconds,
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"sprite animation probe failed: {error}", file=os.sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
