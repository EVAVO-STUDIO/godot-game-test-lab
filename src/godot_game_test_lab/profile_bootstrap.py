from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Sequence
from pathlib import Path

from .bot_profile import normalize_bot_profile
from .core import find_project_root, inspect_project
from .native_qa_common import NativeQaError, _canonical_json


def _within(candidate: Path, root: Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def _rendering_defaults(project_text: str) -> tuple[str, str]:
    lowered = project_text.casefold()
    if "gl_compatibility" in lowered:
        return ("gl_compatibility", "opengl3")
    if 'renderer/rendering_method="mobile"' in lowered:
        return ("mobile", "vulkan")
    return ("forward_plus", "vulkan")


def _device_defaults(project_text: str) -> list[str]:
    devices: list[str] = []
    if "InputEventMouse" in project_text:
        devices.append("mouse")
    if "InputEventKey" in project_text:
        devices.append("keyboard")
    if "InputEventJoypad" in project_text:
        devices.append("gamepad")
    devices.append("semantic")
    return devices


def build_profile(project: Path) -> tuple[dict, dict]:
    root = find_project_root(project)
    project_file = root / "project.godot"
    if project_file.is_symlink():
        raise NativeQaError("project.godot may not be a symbolic link")
    text = project_file.read_text(encoding="utf-8-sig", errors="strict")
    inventory = inspect_project(root)
    method, driver = _rendering_defaults(text)
    devices = _device_defaults(text)
    configured_scene = inventory.configured_main_scene or ""
    scene = configured_scene if configured_scene.startswith("res://") else ""
    seed_source = "\n".join(
        [inventory.project_name or root.name, configured_scene, str(len(inventory.scenes))]
    )
    seed = int(hashlib.sha256(seed_source.encode()).hexdigest()[:8], 16) & 0x7FFFFFFF
    profile = {
        "schemaVersion": "1.0",
        "campaigns": [
            {
                "id": "ui-graph",
                "required": True,
                "scene": scene,
                "mode": "mixed",
                "seed": seed,
                "devices": devices,
                "maxStates": 16,
                "maxDepth": 4,
                "maxRuns": 48,
                "maxActionsPerState": 12,
                "settleFrames": 20,
                "stallLimit": 12,
                "checkpointEveryState": True,
                "recordRepresentativePaths": True,
                "maxRepresentativePaths": 4,
                "maxFrames": 900,
                "fps": 30,
                "width": 1280,
                "height": 720,
                "renderingMethod": method,
                "renderingDriver": driver,
                "gpuIndex": 0,
                "userArguments": [],
                "actionAllowlist": [],
                "ux": {
                    "captureControlTree": True,
                    "failOnBlackFrame": False,
                    "failOnFrozenVideo": False,
                    "maximumOutOfBoundsInteractive": 0,
                    "maximumOverlappingInteractivePairs": 0,
                    "maximumSmallInteractiveTargets": 8,
                },
            },
            {
                "id": "input-fuzz",
                "required": False,
                "scene": scene,
                "mode": "action_fuzz",
                "seed": seed ^ 0x5EED,
                "devices": devices,
                "maxStates": 8,
                "maxDepth": 3,
                "maxRuns": 24,
                "maxActionsPerState": 16,
                "settleFrames": 10,
                "stallLimit": 16,
                "checkpointEveryState": True,
                "recordRepresentativePaths": True,
                "maxRepresentativePaths": 2,
                "maxFrames": 600,
                "fps": 30,
                "width": 1280,
                "height": 720,
                "renderingMethod": method,
                "renderingDriver": driver,
                "gpuIndex": 0,
                "userArguments": [],
                "actionAllowlist": [],
                "ux": {
                    "captureControlTree": True,
                    "failOnBlackFrame": False,
                    "failOnFrozenVideo": False,
                    "maximumOutOfBoundsInteractive": 0,
                    "maximumOverlappingInteractivePairs": 0,
                    "maximumSmallInteractiveTargets": 8,
                },
            },
        ],
    }
    normalized = normalize_bot_profile(profile)
    discovery = {
        "schemaVersion": "1.0",
        "projectRoot": str(root),
        "projectName": inventory.project_name,
        "configuredMainScene": inventory.configured_main_scene,
        "sceneCount": len(inventory.scenes),
        "gdscriptCount": len(inventory.gdscript_files),
        "csharpProjects": inventory.csharp_projects,
        "addons": inventory.addons,
        "detectedDevices": devices,
        "renderingMethod": method,
        "renderingDriver": driver,
        "profileSeed": seed,
        "notes": [
            "Review blockedText and actionDenylist before the first bot run.",
            "Mark destructive or irreversible game actions as denied.",
            "Add game-specific assertions and required campaigns after the starter run.",
        ],
    }
    return normalized, discovery


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="godot-lab-init-qa",
        description="Create a bounded starter bot-QA profile for any Godot project.",
    )
    parser.add_argument("project", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        help="Profile path; defaults to <project>/.evavo/godot-lab-bot.json.",
    )
    parser.add_argument("--report", type=Path, help="Optional discovery report path.")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--stdout", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        root = find_project_root(args.project)
        profile, discovery = build_profile(root)
        output = args.output or root / ".evavo" / "godot-lab-bot.json"
        if not output.is_absolute():
            output = root / output
        output = output.resolve(strict=False)
        if not _within(output, root):
            raise NativeQaError("generated bot profile must remain inside the Godot project")
        if output.exists() and not args.force:
            raise NativeQaError(f"profile already exists; use --force to replace it: {output}")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(_canonical_json(profile), encoding="utf-8", newline="\n")
        report_path = args.report
        if report_path is not None:
            if not report_path.is_absolute():
                report_path = root / report_path
            report_path = report_path.resolve(strict=False)
            if not _within(report_path, root):
                raise NativeQaError("discovery report must remain inside the Godot project")
            if report_path.exists() and not args.force:
                raise NativeQaError(
                    f"discovery report already exists; use --force: {report_path}"
                )
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(
                _canonical_json(discovery), encoding="utf-8", newline="\n"
            )
    except (NativeQaError, FileNotFoundError, OSError, UnicodeError, ValueError) as error:
        print(json.dumps({"status": "blocked", "error": str(error)}, sort_keys=True))
        return 2
    result = {
        "status": "created",
        "profile": str(output),
        "report": str(report_path) if report_path is not None else None,
        "discovery": discovery,
    }
    print(_canonical_json(profile) if args.stdout else json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
