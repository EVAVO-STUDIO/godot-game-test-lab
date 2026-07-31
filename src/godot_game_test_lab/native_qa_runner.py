from __future__ import annotations

import argparse
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from .command_guard import validate_scene_argument
from .core import inspect_project
from .native_qa_common import (
    NativeQaError,
    _ERROR_MARKERS,
    _VERSION_RE,
    _archive_checkout,
    _canonical_json,
    _git_text,
    _is_within,
    _load_json_object,
    _process_findings,
    _require_tracked_file,
    _resolve_child,
    _run_process,
    _safe_relative_path,
    _sha256_file,
    _validate_exact_checkout,
    _validate_sha,
    _write_process_evidence,
)
from .native_qa_evidence import (
    _artifact_inventory,
    _extract_video_evidence,
    _hardware_evidence,
    _required_visual_capabilities,
)
from .native_qa_profile import normalize_profile
from .pipeline import (
    discover_godot_binary,
    validate_project_pipeline,
    write_report_bundle,
)


def run_native_qa(args: argparse.Namespace) -> dict[str, Any]:
    expected_lab_sha = _validate_sha(args.expected_lab_sha, "expected_lab_sha")
    expected_target_sha = _validate_sha(args.expected_target_sha, "expected_target_sha")
    if _VERSION_RE.fullmatch(args.minimum_godot_version) is None:
        raise NativeQaError("minimum_godot_version must be an explicit Godot 4.x.y version")

    lab_root = args.lab_root.expanduser().resolve(strict=True)
    target_root = args.target_repository.expanduser().resolve(strict=True)
    allowed_artifact_root = args.allowed_artifact_root.expanduser().resolve(strict=True)
    artifacts = args.artifacts.expanduser().resolve(strict=False)
    if not target_root.is_dir() or not lab_root.is_dir() or not allowed_artifact_root.is_dir():
        raise NativeQaError("lab, target and allowed artifact roots must be directories")
    if not _is_within(artifacts, allowed_artifact_root):
        raise NativeQaError("artifacts must remain beneath allowed_artifact_root")
    if _is_within(artifacts, target_root) or _is_within(artifacts, lab_root):
        raise NativeQaError("native QA artifacts must remain outside target and lab source")
    if artifacts.exists() and any(artifacts.iterdir()):
        raise NativeQaError("artifacts directory must not contain a previous run")
    artifacts.mkdir(parents=True, exist_ok=True)

    _validate_exact_checkout(lab_root, expected_lab_sha, "test lab")
    target_git_root = Path(_git_text(target_root, ["rev-parse", "--show-toplevel"])).resolve()
    _validate_exact_checkout(target_git_root, expected_target_sha, "target repository")
    status_before = _git_text(
        target_git_root, ["status", "--porcelain=v1", "--untracked-files=all"]
    )

    project_subpath = _safe_relative_path(args.project_subpath, "project_subpath")
    profile_input = args.profile.expanduser()
    if not profile_input.is_absolute():
        profile_input = target_git_root / profile_input
    profile_path = profile_input.resolve(strict=True)
    profile_relative = _require_tracked_file(target_git_root, profile_path, "profile")
    profile = normalize_profile(_load_json_object(profile_path, "native QA profile"))
    (artifacts / "profile.normalized.json").write_text(
        _canonical_json(profile), encoding="utf-8"
    )

    hardware = _hardware_evidence(target_git_root)
    (artifacts / "hardware.json").write_text(_canonical_json(hardware), encoding="utf-8")
    if args.require_interactive_desktop and not hardware["session"]["interactive"]:
        raise NativeQaError(
            "native visual QA requires the logged-in interactive Windows session, not Session 0"
        )

    work_root = artifacts / "work" / "repository"
    _archive_checkout(target_git_root, expected_target_sha, work_root, args.timeout)
    project_root = _resolve_child(work_root, project_subpath, "project_subpath")
    if not (project_root / "project.godot").is_file():
        raise NativeQaError("selected project_subpath does not contain project.godot")
    archived_profile = _resolve_child(
        work_root, Path(*PurePosixPath(profile_relative).parts), "archived profile"
    )
    if _sha256_file(archived_profile) != _sha256_file(profile_path):
        raise NativeQaError("archived profile does not match the exact target checkout")

    validation_root = artifacts / "validation"
    validation = validate_project_pipeline(
        project_root,
        godot_executable=args.godot,
        dotnet_executable=args.dotnet,
        minimum_godot_version=args.minimum_godot_version,
        timeout_seconds=args.timeout,
        boot_frames=args.boot_frames,
        log_directory=validation_root / "engine-logs",
    )
    write_report_bundle(validation, validation_root)

    inventory = inspect_project(project_root)
    godot = discover_godot_binary(args.godot, requires_mono=bool(inventory.csharp_projects))
    if godot is None:
        raise NativeQaError("compatible Godot executable was not found for native QA")
    help_result = _run_process([str(godot), "--help"], project_root, 30)
    help_findings = _process_findings(help_result, "Godot --help")
    _write_process_evidence(help_result, artifacts, "godot-help")
    if help_findings:
        raise NativeQaError("Godot --help failed before visual execution")
    help_text = f"{help_result['stdout']}\n{help_result['stderr']}"

    journeys: list[dict[str, Any]] = []
    if validation.status == "passed":
        harness_root = project_root / ".evavo-lab"
        harness_root.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(
            lab_root / "scripts" / "godot_input_journey.gd",
            harness_root / "godot_input_journey.gd",
        )
        for journey in profile["journeys"]:
            journey_id = journey["id"]
            journey_root = artifacts / "journeys" / journey_id
            checkpoints = journey_root / "checkpoints"
            journey_root.mkdir(parents=True, exist_ok=True)
            checkpoints.mkdir(parents=True, exist_ok=True)
            scene = journey["scene"]
            if scene:
                scene = validate_scene_argument(scene, project_root)
            missing = _required_visual_capabilities(help_text, journey)
            if missing:
                journeys.append(
                    {
                        "id": journey_id,
                        "required": journey["required"],
                        "status": "blocked",
                        "findings": [
                            "Godot is missing required native visual capabilities: "
                            + ", ".join(missing)
                        ],
                        "evidence": [],
                    }
                )
                continue

            journey_file = harness_root / f"journey-{journey_id}.json"
            journey_file.write_text(_canonical_json(journey), encoding="utf-8")
            retained = journey_root / "journey.normalized.json"
            retained.write_text(_canonical_json(journey), encoding="utf-8")
            report_path = journey_root / "journey-report.json"
            movie = journey_root / "gameplay.avi"
            engine_log = journey_root / "godot.log"
            command = [
                str(godot),
                "--verbose",
                "--path",
                str(project_root),
                "--rendering-method",
                journey["renderingMethod"],
                "--rendering-driver",
                journey["renderingDriver"],
            ]
            if journey["renderingMethod"] != "gl_compatibility":
                command.extend(["--gpu-index", str(journey["gpuIndex"])])
            command.extend([
                "--windowed",
                "--resolution",
                f"{journey['width']}x{journey['height']}",
                "--position",
                args.window_position,
                "--log-file",
                str(engine_log),
                "--write-movie",
                str(movie),
                "--fixed-fps",
                str(journey["fps"]),
                "--quit-after",
                str(journey["maxFrames"] + 240),
                "--script",
                "res://.evavo-lab/godot_input_journey.gd",
            ])
            if journey["userArguments"]:
                command.append("--")
                command.extend(journey["userArguments"])
            environment = os.environ.copy()
            environment.update(
                {
                    "EVAVO_JOURNEY_PATH": f"res://.evavo-lab/{journey_file.name}",
                    "EVAVO_JOURNEY_REPORT": str(report_path),
                    "EVAVO_JOURNEY_CHECKPOINT_ROOT": str(checkpoints),
                    "EVAVO_JOURNEY_SCENE": scene,
                    "EVAVO_JOURNEY_MAX_FRAMES": str(journey["maxFrames"]),
                }
            )
            process = _run_process(command, project_root, args.timeout, environment=environment)
            evidence = [retained.relative_to(artifacts).as_posix()]
            evidence.extend(_write_process_evidence(process, artifacts, f"journey-{journey_id}"))
            findings = _process_findings(process, f"journey {journey_id}")
            if engine_log.is_file():
                evidence.append(engine_log.relative_to(artifacts).as_posix())
                engine_text = engine_log.read_text(encoding="utf-8", errors="replace")
                for marker in _ERROR_MARKERS:
                    if marker.casefold() in engine_text.casefold():
                        findings.append(
                            f"journey {journey_id} engine log contains error marker: {marker}"
                        )
            else:
                findings.append("Godot journey engine log was not produced")
            harness: dict[str, Any] = {}
            if report_path.is_file():
                try:
                    harness = _load_json_object(report_path, "journey report")
                    evidence.append(report_path.relative_to(artifacts).as_posix())
                except NativeQaError as error:
                    findings.append(str(error))
            else:
                findings.append("journey report was not produced")
            if harness.get("status") != "passed":
                for failure in harness.get("failures", []):
                    findings.append(f"journey harness: {failure}")
            visual = _extract_video_evidence(movie, artifacts, args.timeout)
            findings.extend(visual["findings"])
            evidence.extend(visual["evidence"])
            journeys.append(
                {
                    "id": journey_id,
                    "required": journey["required"],
                    "status": "passed" if not findings else "failed",
                    "scene": scene or "configured main scene",
                    "renderingMethod": journey["renderingMethod"],
                    "renderingDriver": journey["renderingDriver"],
                    "requestedGpuIndex": journey["gpuIndex"],
                    "syntheticInput": True,
                    "physicalControllerCertified": False,
                    "process": process,
                    "harness": harness,
                    "visual": visual,
                    "findings": sorted(set(findings)),
                    "evidence": sorted(set(evidence)),
                }
            )

    required_failures = [
        item for item in journeys if item["required"] and item["status"] != "passed"
    ]
    status = "passed"
    findings: list[str] = []
    if validation.status != "passed":
        status = "failed"
        findings.append("native validation did not pass")
    if required_failures:
        status = "failed"
        findings.append("one or more required native journeys did not pass")
    if not journeys and validation.status == "passed":
        status = "failed"
        findings.append("no native journeys were executed")

    status_after = _git_text(
        target_git_root, ["status", "--porcelain=v1", "--untracked-files=all"]
    )
    mutation = status_after != status_before
    if mutation:
        status = "failed"
        findings.append("native QA changed the target repository checkout")

    summary: dict[str, Any] = {
        "schemaVersion": "1.0",
        "status": status,
        "generatedAt": datetime.now(UTC).isoformat(),
        "labSha": expected_lab_sha,
        "targetSha": expected_target_sha,
        "targetGitRoot": str(target_git_root),
        "projectSubpath": project_subpath.as_posix(),
        "profile": profile_relative,
        "profileSha256": _sha256_file(profile_path),
        "minimumGodotVersion": args.minimum_godot_version,
        "interactiveDesktopRequired": args.require_interactive_desktop,
        "hardware": hardware,
        "validationStatus": validation.status,
        "validationReport": "validation/report.json",
        "journeys": journeys,
        "targetMutationDetected": mutation,
        "targetStatusBefore": status_before,
        "targetStatusAfter": status_after,
        "findings": findings,
        "truthBoundary": (
            "This receipt proves only the exact validation and synthetic journeys retained in "
            "its evidence. It does not certify physical controllers, complete gameplay, game "
            "feel, accessibility or human visual approval."
        ),
    }
    shutil.rmtree(artifacts / "work", ignore_errors=True)
    summary_path = artifacts / "native-agent-summary.json"
    summary_path.write_text(_canonical_json(summary), encoding="utf-8")
    summary["artifacts"] = _artifact_inventory(artifacts)
    summary_path.write_text(_canonical_json(summary), encoding="utf-8")
    return summary
