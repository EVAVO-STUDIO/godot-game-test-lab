from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
import uuid
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from .command_guard import validate_scene_argument
from .core import inspect_project
from .multiplayer_profile import normalize_multiplayer_profile
from .native_qa_common import (
    _ERROR_MARKERS,
    _VERSION_RE,
    NativeQaError,
    _archive_checkout,
    _canonical_json,
    _directory_usage,
    _git_text,
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
)
from .native_qa_runner import (
    _artifact_remaining,
    _checkpoint_evidence,
    _process_receipt,
    _read_validation_status,
    _remaining_seconds,
    _validate_roots,
)
from .pipeline import discover_godot_binary


def _role_environment(role_root: Path) -> dict[str, str]:
    environment = os.environ.copy()
    runtime_home = role_root / "runtime-home"
    runtime_home.mkdir(parents=True, exist_ok=True)
    environment["EVAVO_MULTIPLAYER_ROLE_ROOT"] = str(runtime_home)
    if os.name == "nt":
        appdata = runtime_home / "AppData" / "Roaming"
        localappdata = runtime_home / "AppData" / "Local"
        temp = runtime_home / "Temp"
        for directory in (appdata, localappdata, temp):
            directory.mkdir(parents=True, exist_ok=True)
        environment.update(
            {
                "APPDATA": str(appdata),
                "LOCALAPPDATA": str(localappdata),
                "TEMP": str(temp),
                "TMP": str(temp),
            }
        )
    else:
        data = runtime_home / "share"
        config = runtime_home / "config"
        cache = runtime_home / "cache"
        temp = runtime_home / "tmp"
        for directory in (data, config, cache, temp):
            directory.mkdir(parents=True, exist_ok=True)
        environment.update(
            {
                "HOME": str(runtime_home),
                "XDG_DATA_HOME": str(data),
                "XDG_CONFIG_HOME": str(config),
                "XDG_CACHE_HOME": str(cache),
                "TMPDIR": str(temp),
            }
        )
    return environment


def _run_role(
    *,
    role: dict[str, Any],
    role_index: int,
    project_root: Path,
    artifacts: Path,
    harness_root: Path,
    godot: Path,
    help_text: str,
    args: argparse.Namespace,
    started: float,
    role_budget_bytes: int,
) -> dict[str, Any]:
    role_id = str(role["id"])
    journey = dict(role["journey"])
    role_root = artifacts / "roles" / role_id
    checkpoints = role_root / "checkpoints"
    role_root.mkdir(parents=True, exist_ok=False)
    checkpoints.mkdir(parents=True, exist_ok=False)
    retained = role_root / "journey.normalized.json"
    retained.write_text(_canonical_json(journey), encoding="utf-8")

    start_delay_ms = int(role["startDelayMs"])
    if start_delay_ms:
        time.sleep(start_delay_ms / 1000.0)

    scene = str(journey["scene"])
    if scene:
        scene = validate_scene_argument(scene, project_root)
    missing = _required_visual_capabilities(help_text, journey)
    if missing:
        return {
            "id": role_id,
            "personaId": role.get("personaId"),
            "required": bool(role["required"]),
            "startDelayMs": start_delay_ms,
            "status": "blocked",
            "findings": [
                "Godot is missing required native visual capabilities: " + ", ".join(missing)
            ],
            "evidence": [retained.relative_to(artifacts).as_posix()],
        }

    journey_file = harness_root / f"multiplayer-journey-{role_id}.json"
    journey_file.write_text(_canonical_json(journey), encoding="utf-8")
    report_path = role_root / "journey-report.json"
    movie = role_root / "gameplay.avi"
    engine_log = role_root / "godot.log"
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
    base_x, base_y = [int(part) for part in args.window_position.split(",", 1)]
    columns = max(1, int(args.window_columns))
    column = role_index % columns
    row = role_index // columns
    position = f"{base_x + column * int(args.window_step_x)},{base_y + row * int(args.window_step_y)}"
    command.extend(
        [
            "--windowed",
            "--resolution",
            f"{journey['width']}x{journey['height']}",
            "--position",
            position,
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

    environment = _role_environment(role_root)
    environment.update(
        {
            "EVAVO_MULTIPLAYER_SESSION": str(args.session_label),
            "EVAVO_MULTIPLAYER_ROLE": role_id,
            "EVAVO_JOURNEY_PATH": f"res://.evavo-lab/{journey_file.name}",
            "EVAVO_JOURNEY_REPORT": str(report_path),
            "EVAVO_JOURNEY_CHECKPOINT_ROOT": str(checkpoints),
            "EVAVO_JOURNEY_SCENE": scene,
            "EVAVO_JOURNEY_MAX_FRAMES": str(journey["maxFrames"]),
        }
    )
    scoped_budget = max(role_budget_bytes, 64 * 1024 * 1024)
    process = _run_process(
        command,
        project_root,
        _remaining_seconds(started, args.max_total_seconds, args.timeout),
        environment=environment,
        artifact_budget_root=role_root,
        maximum_artifact_bytes=scoped_budget,
    )

    evidence = [retained.relative_to(artifacts).as_posix()]
    evidence.extend(_write_process_evidence(process, artifacts, f"multiplayer-{role_id}"))
    findings = _process_findings(process, f"multiplayer role {role_id}")
    if engine_log.is_file():
        evidence.append(engine_log.relative_to(artifacts).as_posix())
        engine_text = _read_bounded_text(engine_log)
        for marker in _ERROR_MARKERS:
            if marker.casefold() in engine_text.casefold():
                findings.append(
                    f"multiplayer role {role_id} engine log contains error marker: {marker}"
                )
    else:
        findings.append("Godot multiplayer role engine log was not produced")

    harness: dict[str, Any] = {}
    if report_path.is_file():
        try:
            harness = _load_json_object(report_path, "multiplayer journey report")
            evidence.append(report_path.relative_to(artifacts).as_posix())
        except NativeQaError as error:
            findings.append(str(error))
    else:
        findings.append("multiplayer journey report was not produced")
    if harness.get("status") != "passed":
        for failure in harness.get("failures", []):
            findings.append(f"journey harness: {failure}")

    checkpoint_evidence, checkpoint_findings = _checkpoint_evidence(checkpoints, artifacts)
    evidence.extend(checkpoint_evidence)
    findings.extend(checkpoint_findings)
    visual = _extract_video_evidence(
        movie,
        artifacts,
        _remaining_seconds(started, args.max_total_seconds, args.timeout),
        journey["ux"],
        maximum_artifact_bytes=scoped_budget,
    )
    findings.extend(visual["findings"])
    evidence.extend(visual["evidence"])
    return {
        "id": role_id,
        "personaId": role.get("personaId"),
        "required": bool(role["required"]),
        "startDelayMs": start_delay_ms,
        "status": "passed" if not findings else "failed",
        "scene": scene or "configured main scene",
        "windowPosition": position,
        "renderingMethod": journey["renderingMethod"],
        "renderingDriver": journey["renderingDriver"],
        "requestedGpuIndex": journey["gpuIndex"],
        "syntheticInput": True,
        "concurrentClient": True,
        "process": _process_receipt(process),
        "harness": harness,
        "visual": visual,
        "findings": sorted(set(findings)),
        "evidence": sorted(set(evidence)),
    }


def run_multiplayer_qa(args: argparse.Namespace) -> dict[str, Any]:
    started = time.monotonic()
    run_id = f"multiplayer-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:12]}"
    expected_lab_sha = _validate_sha(args.expected_lab_sha, "expected_lab_sha")
    expected_target_sha = _validate_sha(args.expected_target_sha, "expected_target_sha")
    if _VERSION_RE.fullmatch(args.minimum_godot_version) is None:
        raise NativeQaError("minimum_godot_version must be an explicit Godot 4.x.y version")

    lab_root, target_root, _allowed_artifact_root, artifacts = _validate_roots(args)
    work_container = artifacts / "work"
    target_git_root: Path | None = None
    status_before = ""
    checkout_verified = False
    lease_record: dict[str, Any] = {"acquired": False}

    try:
        _validate_exact_checkout(lab_root, expected_lab_sha, "test lab")
        _require_clean_checkout(lab_root, "test lab")
        target_git_root = Path(_git_text(target_root, ["rev-parse", "--show-toplevel"])).resolve()
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
            raise NativeQaError("multiplayer QA profile may not be a symbolic link")
        profile_path = profile_input.resolve(strict=True)
        profile_relative = _require_tracked_file(
            target_git_root, profile_path, "multiplayer profile"
        )
        profile = normalize_multiplayer_profile(
            _load_json_object(profile_path, "multiplayer QA profile")
        )
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
                    "sessionLabel": args.session_label,
                    "roleCount": len(profile["roles"]),
                    "maximumTotalSeconds": args.max_total_seconds,
                    "maximumArtifactBytes": args.max_artifact_bytes,
                }
            ),
            encoding="utf-8",
        )

        with _native_desktop_lease(enabled=os.name == "nt") as acquired_lease:
            lease_record = acquired_lease
            hardware = _hardware_evidence(target_git_root)
            (artifacts / "hardware.json").write_text(_canonical_json(hardware), encoding="utf-8")
            interactive = bool(hardware["session"]["interactive"])
            if args.require_interactive_desktop and not interactive:
                detail = hardware["session"].get("probeError") or (
                    "Explorer is not running in the worker's nonzero Windows session"
                )
                raise NativeQaError(
                    "multiplayer visual QA requires Greg's logged-in interactive Windows session: "
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
                "archived multiplayer profile",
            )
            if _sha256_file(archived_profile) != _sha256_file(profile_path):
                raise NativeQaError("archived multiplayer profile does not match exact target checkout")

            validation_root = artifacts / "validation"
            validation_root.mkdir(parents=True, exist_ok=True)
            remaining = _remaining_seconds(started, args.max_total_seconds, args.max_total_seconds)
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
            validation_process = _run_process(
                validation_command,
                lab_root,
                remaining,
                artifact_budget_root=validation_root,
                maximum_artifact_bytes=max(
                    64 * 1024 * 1024,
                    min(args.max_artifact_bytes // 4, args.max_artifact_bytes),
                ),
            )
            validation_evidence = _write_process_evidence(
                validation_process, artifacts, "multiplayer-native-validation"
            )
            validation_findings = _process_findings(
                validation_process, "multiplayer native validation"
            )
            validation_report = validation_root / "report.json"
            try:
                validation_status = _read_validation_status(validation_report)
            except NativeQaError as error:
                validation_status = "failed"
                validation_findings.append(str(error))
            if validation_findings and validation_status == "passed":
                validation_status = "failed"

            roles: list[dict[str, Any]] = []
            if validation_status == "passed":
                inventory = inspect_project(project_root)
                godot = discover_godot_binary(
                    args.godot, requires_mono=bool(inventory.csharp_projects)
                )
                if godot is None:
                    raise NativeQaError("compatible Godot executable was not found for multiplayer QA")
                help_result = _run_process(
                    [str(godot), "--help"],
                    project_root,
                    _remaining_seconds(started, args.max_total_seconds, 30),
                )
                help_findings = _process_findings(help_result, "Godot --help")
                _write_process_evidence(help_result, artifacts, "multiplayer-godot-help")
                if help_findings:
                    raise NativeQaError("Godot --help failed before multiplayer execution")
                help_text = f"{help_result['stdout']}\n{help_result['stderr']}"
                harness_root = project_root / ".evavo-lab"
                harness_root.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(
                    lab_root / "scripts" / "godot_input_journey.gd",
                    harness_root / "godot_input_journey.gd",
                )
                remaining_bytes, _usage = _artifact_remaining(
                    artifacts, args.max_artifact_bytes
                )
                role_budget = max(
                    64 * 1024 * 1024,
                    remaining_bytes // max(1, len(profile["roles"])),
                )
                with ThreadPoolExecutor(
                    max_workers=len(profile["roles"]),
                    thread_name_prefix="evavo-godot-role",
                ) as executor:
                    futures = {
                        executor.submit(
                            _run_role,
                            role=role,
                            role_index=index,
                            project_root=project_root,
                            artifacts=artifacts,
                            harness_root=harness_root,
                            godot=godot,
                            help_text=help_text,
                            args=args,
                            started=started,
                            role_budget_bytes=role_budget,
                        ): index
                        for index, role in enumerate(profile["roles"])
                    }
                    ordered: dict[int, dict[str, Any]] = {}
                    for future in as_completed(futures):
                        index = futures[future]
                        try:
                            ordered[index] = future.result()
                        except Exception as error:
                            role = profile["roles"][index]
                            ordered[index] = {
                                "id": role["id"],
                                "personaId": role.get("personaId"),
                                "required": role["required"],
                                "startDelayMs": role["startDelayMs"],
                                "status": "blocked",
                                "findings": [
                                    f"multiplayer role raised {type(error).__name__}: {error}"
                                ],
                                "evidence": [],
                            }
                    roles = [ordered[index] for index in range(len(profile["roles"]))]

            required_failures = [
                role for role in roles if role["required"] and role["status"] != "passed"
            ]
            optional_failures = [
                role for role in roles if not role["required"] and role["status"] != "passed"
            ]
            findings: list[str] = []
            status = "passed"
            if validation_status != "passed":
                status = "failed"
                findings.append("multiplayer native validation did not pass")
            if len(roles) < 2 and validation_status == "passed":
                status = "failed"
                findings.append("fewer than two multiplayer roles executed")
            if required_failures:
                status = "failed"
                findings.append("one or more required multiplayer roles did not pass")
            if optional_failures:
                findings.append("one or more optional multiplayer roles did not pass")
            if not interactive:
                findings.append(
                    "execution was non-interactive and is not native desktop evidence"
                )

            status_after = _git_text(
                target_git_root, ["status", "--porcelain=v1", "--untracked-files=all"]
            )
            mutation = status_after != status_before
            if mutation:
                status = "failed"
                findings.append("multiplayer QA changed the target repository checkout")

            shutil.rmtree(work_container, ignore_errors=True)
            used_bytes, used_files, usage_complete = _directory_usage(artifacts)
            if not usage_complete or used_bytes > args.max_artifact_bytes:
                status = "failed"
                findings.append("retained multiplayer evidence exceeded artifact budget")
            if time.monotonic() - started > args.max_total_seconds:
                status = "failed"
                findings.append("multiplayer QA exceeded total execution time budget")

            summary: dict[str, Any] = {
                "schemaVersion": "1.0",
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
                "sessionLabel": args.session_label,
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
                "roles": roles,
                "concurrentRoleCount": len(roles),
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
                "truthBoundary": profile["truthBoundary"],
            }
            summary["artifacts"] = _artifact_inventory(
                artifacts, maximum_total_bytes=args.max_artifact_bytes
            )
            (artifacts / "multiplayer-agent-summary.json").write_text(
                _canonical_json(summary), encoding="utf-8"
            )
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
                        "multiplayer QA changed the target repository checkout after finalization"
                    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="godot-lab-multiplayer-qa",
        description=(
            "Run exact-SHA concurrent Godot client journeys under one guarded native desktop lease."
        ),
    )
    parser.add_argument("--lab-root", type=Path, required=True)
    parser.add_argument("--target-repository", type=Path, required=True)
    parser.add_argument("--project-subpath", default=".")
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--expected-lab-sha", required=True)
    parser.add_argument("--expected-target-sha", required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--allowed-artifact-root", type=Path, required=True)
    parser.add_argument("--godot", type=Path)
    parser.add_argument("--dotnet", type=Path)
    parser.add_argument("--minimum-godot-version", default="4.6.2")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--boot-frames", type=int, default=30)
    parser.add_argument("--max-total-seconds", type=int, default=3600)
    parser.add_argument("--max-artifact-bytes", type=int, default=20 * 1024**3)
    parser.add_argument("--window-position", default="32,32")
    parser.add_argument("--window-columns", type=int, default=2)
    parser.add_argument("--window-step-x", type=int, default=48)
    parser.add_argument("--window-step-y", type=int, default=48)
    parser.add_argument("--session-label", default="evavo-multiplayer-session")
    parser.add_argument(
        "--allow-noninteractive",
        action="store_false",
        dest="require_interactive_desktop",
        help="Allow contract testing without claiming native desktop evidence.",
    )
    parser.set_defaults(require_interactive_desktop=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    if not 30 <= args.timeout <= 7200:
        raise SystemExit("--timeout must be between 30 and 7200 seconds")
    if not 0 <= args.boot_frames <= 3600:
        raise SystemExit("--boot-frames must be between 0 and 3600")
    if not 60 <= args.max_total_seconds <= 14400:
        raise SystemExit("--max-total-seconds must be between 60 and 14400")
    if not 1024**3 <= args.max_artifact_bytes <= 200 * 1024**3:
        raise SystemExit("--max-artifact-bytes must be between 1 GiB and 200 GiB")
    if re.fullmatch(r"-?[0-9]{1,5},-?[0-9]{1,5}", args.window_position) is None:
        raise SystemExit("--window-position must use X,Y integer coordinates")
    if not 1 <= args.window_columns <= 8:
        raise SystemExit("--window-columns must be between 1 and 8")
    if not 0 <= args.window_step_x <= 4096 or not 0 <= args.window_step_y <= 4096:
        raise SystemExit("window steps must be between 0 and 4096 pixels")
    if not isinstance(args.session_label, str) or not args.session_label.strip() or len(args.session_label) > 128:
        raise SystemExit("--session-label must contain 1 to 128 characters")
    try:
        summary = run_multiplayer_qa(args)
    except KeyboardInterrupt:
        print(json.dumps({"status": "cancelled", "error": "interrupted"}, sort_keys=True))
        return 130
    except (NativeQaError, FileNotFoundError, OSError, TypeError, ValueError) as error:
        print(json.dumps({"status": "blocked", "error": str(error)}, sort_keys=True))
        return 2
    print(json.dumps(summary, sort_keys=True))
    return 0 if summary.get("status") == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
