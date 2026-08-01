from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from .command_guard import validate_scene_argument
from .core import inspect_project
from .native_qa_common import (
    _ERROR_MARKERS,
    _VERSION_RE,
    NativeQaError,
    _archive_checkout,
    _canonical_json,
    _directory_usage,
    _git_text,
    _is_within,
    _load_json_object,
    _native_desktop_lease,
    _process_findings,
    _read_bounded_text,
    _require_clean_checkout,
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
    _validate_png,
)
from .native_qa_profile import normalize_profile
from .pipeline import discover_godot_binary


def _remaining_seconds(started: float, maximum_total_seconds: int, stage_limit: int) -> int:
    remaining = maximum_total_seconds - int(time.monotonic() - started)
    if remaining < 1:
        raise NativeQaError("Native QA exceeded its total execution time budget")
    return max(1, min(stage_limit, remaining))


def _artifact_remaining(artifacts: Path, maximum_bytes: int) -> tuple[int, dict[str, Any]]:
    used, files, complete = _directory_usage(artifacts)
    usage = {
        "bytes": used,
        "files": files,
        "complete": complete,
        "maximumBytes": maximum_bytes,
    }
    if not complete:
        raise NativeQaError("Native QA could not completely measure its artifact directory")
    if used >= maximum_bytes:
        raise NativeQaError("Native QA exhausted its total artifact byte budget")
    return (maximum_bytes - used, usage)


def _artifact_root_budget(
    artifacts: Path,
    scoped_root: Path,
    maximum_bytes: int,
) -> int:
    remaining, _usage = _artifact_remaining(artifacts, maximum_bytes)
    scoped_bytes, _files, complete = _directory_usage(scoped_root)
    if not complete:
        raise NativeQaError("Native QA could not measure the scoped artifact directory")
    return scoped_bytes + remaining


def _process_receipt(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "command": list(result.get("command", [])),
        "exitCode": result.get("exitCode"),
        "durationSeconds": result.get("durationSeconds"),
        "timedOut": bool(result.get("timedOut", False)),
        "artifactBudgetExceeded": bool(result.get("artifactBudgetExceeded", False)),
    }


def _read_validation_status(report_path: Path) -> str:
    try:
        if report_path.is_symlink() or not report_path.is_file():
            raise NativeQaError("native validation did not produce a regular report.json")
        with report_path.open("rb") as handle:
            prefix = handle.read(512 * 1024)
    except NativeQaError:
        raise
    except OSError as error:
        raise NativeQaError(f"Could not read native validation report: {error}") from error
    if not prefix.lstrip().startswith(b"{"):
        raise NativeQaError("native validation report is not a JSON object")
    match = re.search(rb'"status"\s*:\s*"(passed|failed|blocked)"', prefix)
    if match is None:
        raise NativeQaError("native validation report does not expose a bounded status")
    return match.group(1).decode("ascii")


def _validate_roots(
    args: argparse.Namespace,
) -> tuple[Path, Path, Path, Path]:
    lab_root = args.lab_root.expanduser().resolve(strict=True)
    target_root = args.target_repository.expanduser().resolve(strict=True)
    allowed_artifact_root = args.allowed_artifact_root.expanduser().resolve(strict=True)
    artifacts = args.artifacts.expanduser().resolve(strict=False)
    if not target_root.is_dir() or not lab_root.is_dir() or not allowed_artifact_root.is_dir():
        raise NativeQaError("lab, target and allowed artifact roots must be directories")
    if artifacts == allowed_artifact_root or not _is_within(artifacts, allowed_artifact_root):
        raise NativeQaError(
            "artifacts must be a run-specific child beneath allowed_artifact_root"
        )
    if (
        _is_within(artifacts, target_root)
        or _is_within(artifacts, lab_root)
        or _is_within(target_root, artifacts)
        or _is_within(lab_root, artifacts)
    ):
        raise NativeQaError("native QA artifacts must remain disjoint from target and lab source")
    if (
        target_root == lab_root
        or _is_within(target_root, lab_root)
        or _is_within(lab_root, target_root)
    ):
        raise NativeQaError("target and test-lab repositories must be separate checkouts")
    if artifacts.exists() and any(artifacts.iterdir()):
        raise NativeQaError("artifacts directory must not contain a previous run")
    artifacts.mkdir(parents=True, exist_ok=True)
    return lab_root, target_root, allowed_artifact_root, artifacts


def _checkpoint_evidence(checkpoints: Path, artifacts: Path) -> tuple[list[str], list[str]]:
    evidence: list[str] = []
    findings: list[str] = []
    try:
        entries = sorted(checkpoints.iterdir(), key=lambda path: path.name.casefold())
    except OSError as error:
        return ([], [f"Checkpoint directory could not be read: {error}"])
    for path in entries:
        if path.is_symlink() or not path.is_file() or path.suffix.casefold() != ".png":
            findings.append(f"Unexpected checkpoint evidence entry: {path.name}")
        elif _validate_png(path):
            evidence.append(path.relative_to(artifacts).as_posix())
        else:
            findings.append(f"Checkpoint is not a valid PNG: {path.name}")
    return evidence, findings


def run_native_qa(args: argparse.Namespace) -> dict[str, Any]:
    started = time.monotonic()
    run_id = f"native-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:12]}"
    expected_lab_sha = _validate_sha(args.expected_lab_sha, "expected_lab_sha")
    expected_target_sha = _validate_sha(args.expected_target_sha, "expected_target_sha")
    if _VERSION_RE.fullmatch(args.minimum_godot_version) is None:
        raise NativeQaError("minimum_godot_version must be an explicit Godot 4.x.y version")

    lab_root, target_root, _allowed_artifact_root, artifacts = _validate_roots(args)
    work_container = artifacts / "work"
    target_git_root: Path | None = None
    status_before = ""
    status_after = ""
    checkout_verified = False
    mutation = False
    lease_record: dict[str, Any] = {"acquired": False}

    try:
        _validate_exact_checkout(lab_root, expected_lab_sha, "test lab")
        _require_clean_checkout(lab_root, "test lab")
        target_git_root = Path(
            _git_text(target_root, ["rev-parse", "--show-toplevel"])
        ).resolve()
        _validate_exact_checkout(target_git_root, expected_target_sha, "target repository")
        _require_clean_checkout(target_git_root, "target repository")
        status_before = _git_text(
            target_git_root, ["status", "--porcelain=v1", "--untracked-files=all"]
        )
        checkout_verified = True

        project_subpath = _safe_relative_path(args.project_subpath, "project_subpath")
        profile_input = args.profile.expanduser()
        if not profile_input.is_absolute():
            profile_input = target_git_root / profile_input
        if profile_input.is_symlink():
            raise NativeQaError("native QA profile may not be a symbolic link")
        profile_path = profile_input.resolve(strict=True)
        profile_relative = _require_tracked_file(target_git_root, profile_path, "profile")
        raw_profile = _load_json_object(profile_path, "native QA profile")
        profile = normalize_profile(raw_profile)
        (artifacts / "profile.normalized.json").write_text(
            _canonical_json(profile), encoding="utf-8"
        )
        (artifacts / "run-context.json").write_text(
            _canonical_json(
                {
                    "schemaVersion": "1.0",
                    "runId": run_id,
                    "labSha": expected_lab_sha,
                    "targetSha": expected_target_sha,
                    "targetGitRoot": str(target_git_root),
                    "projectSubpath": project_subpath.as_posix(),
                    "profile": profile_relative,
                    "profileSha256": _sha256_file(profile_path),
                    "maximumTotalSeconds": args.max_total_seconds,
                    "maximumArtifactBytes": args.max_artifact_bytes,
                }
            ),
            encoding="utf-8",
        )

        with _native_desktop_lease(enabled=os.name == "nt") as acquired_lease:
            lease_record = acquired_lease
            hardware = _hardware_evidence(target_git_root)
            (artifacts / "hardware.json").write_text(
                _canonical_json(hardware), encoding="utf-8"
            )
            interactive = bool(hardware["session"]["interactive"])
            if args.require_interactive_desktop and not interactive:
                detail = hardware["session"].get("probeError") or (
                    "Explorer is not running in the worker's nonzero Windows session"
                )
                raise NativeQaError(
                    "native visual QA requires Greg's logged-in interactive Windows session: "
                    + str(detail)
                )

            work_root = work_container / "repository"
            archive_receipt = _archive_checkout(
                target_git_root,
                expected_target_sha,
                work_root,
                _remaining_seconds(started, args.max_total_seconds, args.timeout),
            )
            (artifacts / "source-archive.json").write_text(
                _canonical_json(archive_receipt), encoding="utf-8"
            )
            project_root = _resolve_child(work_root, project_subpath, "project_subpath")
            if not (project_root / "project.godot").is_file():
                raise NativeQaError("selected project_subpath does not contain project.godot")
            archived_profile = _resolve_child(
                work_root,
                Path(*PurePosixPath(profile_relative).parts),
                "archived profile",
            )
            if _sha256_file(archived_profile) != _sha256_file(profile_path):
                raise NativeQaError("archived profile does not match the exact target checkout")

            validation_root = artifacts / "validation"
            validation_root.mkdir(parents=True, exist_ok=True)
            remaining = _remaining_seconds(
                started, args.max_total_seconds, args.max_total_seconds
            )
            validation_command = [
                sys.executable,
                "-m",
                "godot_game_test_lab.cli",
                "validate",
                str(project_root),
                "--minimum-godot-version",
                args.minimum_godot_version,
                "--timeout",
                str(min(args.timeout, remaining)),
                "--boot-frames",
                str(args.boot_frames),
                "--artifacts",
                str(validation_root),
            ]
            if args.godot is not None:
                validation_command.extend(["--godot", str(args.godot)])
            if args.dotnet is not None:
                validation_command.extend(["--dotnet", str(args.dotnet)])
            scoped_budget = _artifact_root_budget(
                artifacts, validation_root, args.max_artifact_bytes
            )
            validation_process = _run_process(
                validation_command,
                lab_root,
                remaining,
                artifact_budget_root=validation_root,
                maximum_artifact_bytes=scoped_budget,
            )
            validation_evidence = _write_process_evidence(
                validation_process, artifacts, "native-validation"
            )
            validation_findings = _process_findings(
                validation_process, "native validation"
            )
            validation_report = validation_root / "report.json"
            try:
                validation_status = _read_validation_status(validation_report)
            except NativeQaError as error:
                validation_status = "failed"
                validation_findings.append(str(error))
            if validation_findings and validation_status == "passed":
                validation_status = "failed"

            journeys: list[dict[str, Any]] = []
            if validation_status == "passed":
                inventory = inspect_project(project_root)
                godot = discover_godot_binary(
                    args.godot, requires_mono=bool(inventory.csharp_projects)
                )
                if godot is None:
                    raise NativeQaError(
                        "compatible Godot executable was not found for native QA"
                    )
                help_result = _run_process(
                    [str(godot), "--help"],
                    project_root,
                    _remaining_seconds(started, args.max_total_seconds, 30),
                )
                help_findings = _process_findings(help_result, "Godot --help")
                _write_process_evidence(help_result, artifacts, "godot-help")
                if help_findings:
                    raise NativeQaError("Godot --help failed before visual execution")
                help_text = f"{help_result['stdout']}\n{help_result['stderr']}"
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
                    command.extend(
                        [
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
                        ]
                    )
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
                    scoped_budget = _artifact_root_budget(
                        artifacts, journey_root, args.max_artifact_bytes
                    )
                    process = _run_process(
                        command,
                        project_root,
                        _remaining_seconds(
                            started, args.max_total_seconds, args.timeout
                        ),
                        environment=environment,
                        artifact_budget_root=journey_root,
                        maximum_artifact_bytes=scoped_budget,
                    )
                    evidence = [retained.relative_to(artifacts).as_posix()]
                    evidence.extend(
                        _write_process_evidence(
                            process, artifacts, f"journey-{journey_id}"
                        )
                    )
                    findings = _process_findings(process, f"journey {journey_id}")
                    if engine_log.is_file():
                        evidence.append(engine_log.relative_to(artifacts).as_posix())
                        engine_text = _read_bounded_text(engine_log)
                        for marker in _ERROR_MARKERS:
                            if marker.casefold() in engine_text.casefold():
                                findings.append(
                                    f"journey {journey_id} engine log contains error marker: "
                                    + marker
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
                    checkpoint_evidence, checkpoint_findings = _checkpoint_evidence(
                        checkpoints, artifacts
                    )
                    evidence.extend(checkpoint_evidence)
                    findings.extend(checkpoint_findings)
                    scoped_budget = _artifact_root_budget(
                        artifacts, journey_root, args.max_artifact_bytes
                    )
                    visual = _extract_video_evidence(
                        movie,
                        artifacts,
                        _remaining_seconds(
                            started, args.max_total_seconds, args.timeout
                        ),
                        journey["ux"],
                        maximum_artifact_bytes=scoped_budget,
                    )
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
                            "process": _process_receipt(process),
                            "harness": harness,
                            "visual": visual,
                            "findings": sorted(set(findings)),
                            "evidence": sorted(set(evidence)),
                        }
                    )
                    _artifact_remaining(artifacts, args.max_artifact_bytes)

            required_failures = [
                item
                for item in journeys
                if item["required"] and item["status"] != "passed"
            ]
            optional_failures = [
                item
                for item in journeys
                if not item["required"] and item["status"] != "passed"
            ]
            status = "passed"
            findings: list[str] = []
            if validation_status != "passed":
                status = "failed"
                findings.append("native validation did not pass")
            if required_failures:
                status = "failed"
                findings.append("one or more required native journeys did not pass")
            if optional_failures:
                findings.append("one or more optional native journeys did not pass")
            if not journeys and validation_status == "passed":
                status = "failed"
                findings.append("no native journeys were executed")
            if not interactive:
                findings.append(
                    "execution was non-interactive and is not native desktop evidence"
                )

            status_after = _git_text(
                target_git_root,
                ["status", "--porcelain=v1", "--untracked-files=all"],
            )
            mutation = status_after != status_before
            if mutation:
                status = "failed"
                findings.append("native QA changed the target repository checkout")

            shutil.rmtree(work_container, ignore_errors=True)
            used_bytes, used_files, usage_complete = _directory_usage(artifacts)
            if not usage_complete or used_bytes > args.max_artifact_bytes:
                status = "failed"
                findings.append("retained evidence exceeded its bounded artifact budget")
            if time.monotonic() - started > args.max_total_seconds:
                status = "failed"
                findings.append("native QA exceeded its total execution time budget")
            summary: dict[str, Any] = {
                "schemaVersion": "2.0",
                "runId": run_id,
                "status": status,
                "generatedAt": datetime.now(UTC).isoformat(),
                "durationSeconds": round(time.monotonic() - started, 3),
                "labSha": expected_lab_sha,
                "targetSha": expected_target_sha,
                "targetGitRoot": str(target_git_root),
                "projectSubpath": project_subpath.as_posix(),
                "profile": profile_relative,
                "profileSha256": _sha256_file(profile_path),
                "minimumGodotVersion": args.minimum_godot_version,
                "interactiveDesktopRequired": args.require_interactive_desktop,
                "nativeDesktopEvidence": interactive,
                "desktopLease": lease_record,
                "hardware": hardware,
                "sourceArchive": archive_receipt,
                "validationStatus": validation_status,
                "validationReport": "validation/report.json",
                "validationProcess": _process_receipt(validation_process),
                "validationEvidence": validation_evidence,
                "validationFindings": sorted(set(validation_findings)),
                "journeys": journeys,
                "targetMutationDetected": mutation,
                "targetStatusBefore": status_before,
                "targetStatusAfter": status_after,
                "executionBudget": {
                    "maximumTotalSeconds": args.max_total_seconds,
                    "maximumArtifactBytes": args.max_artifact_bytes,
                    "retainedArtifactBytes": used_bytes,
                    "retainedArtifactFiles": used_files,
                    "measurementComplete": usage_complete,
                },
                "findings": sorted(set(findings)),
                "truthBoundary": (
                    "This receipt proves only the exact validation and synthetic journeys "
                    "retained in its evidence. It does not certify physical controllers, "
                    "complete gameplay, game feel, accessibility or human visual approval."
                ),
            }
            summary["artifacts"] = _artifact_inventory(
                artifacts, maximum_total_bytes=args.max_artifact_bytes
            )
            summary_path = artifacts / "native-agent-summary.json"
            summary_path.write_text(_canonical_json(summary), encoding="utf-8")
            return summary
    finally:
        shutil.rmtree(work_container, ignore_errors=True)
        if target_git_root is not None and checkout_verified:
            active_exception = sys.exc_info()[0] is not None
            try:
                final_status = _git_text(
                    target_git_root,
                    ["status", "--porcelain=v1", "--untracked-files=all"],
                )
            except NativeQaError:
                if not active_exception:
                    raise
            else:
                if final_status != status_before and not active_exception:
                    raise NativeQaError(
                        "native QA changed the target repository checkout after finalization"
                    )
