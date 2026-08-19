from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .core import CommandResult, find_project_root, run_command
from .localization_plural import (
    PluralLocalizationReport,
    _command_payload,
    _generated_at,
    _is_within,
    _normalize_probe_results,
    _parse_probe_payload,
    _probe_script,
    _safe_csv_path,
    _select_godot_executable,
    _state_unchanged,
    _verify_csv,
    capture_git_state,
    validate_plural_testlab_request,
)
from .pipeline import command_succeeded, validate_project_pipeline, write_report_bundle


def _write_probe_command_artifact(
    path: Path,
    command: CommandResult | None,
    payload: dict[str, Any] | None,
) -> None:
    body = {
        "version": "evavo_godot_plural_probe_execution_v1",
        "command": _command_payload(command) if command is not None else None,
        "payload": payload,
    }
    path.write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _transient_probe_path(project_root: Path, request_sha256: str) -> Path:
    cache_root = project_root / ".godot" / "evavo-test-lab"
    cache_root.mkdir(parents=True, exist_ok=True)
    if cache_root.is_symlink():
        raise ValueError("Godot Test Lab cache root may not be a symbolic link.")
    return cache_root / f"plural-probe-{request_sha256[:16]}.gd"


def _cleanup_transient_probe(path: Path) -> str | None:
    try:
        path.unlink(missing_ok=True)
        parent = path.parent
        try:
            parent.rmdir()
        except OSError:
            pass
        return None
    except OSError as error:
        return f"Failed to remove transient Godot plural probe script: {error}"


def run_plural_localization_validation_safe(
    candidate: Path,
    request: dict[str, Any],
    *,
    artifacts_root: Path,
    godot_executable: Path | None = None,
    dotnet_executable: Path | None = None,
    minimum_godot_version: str = "4.6.2",
    timeout_seconds: int = 300,
    boot_frames: int = 5,
    warnings_as_errors: bool = False,
    recovery_diagnostic: bool = True,
    allow_major_upgrade: bool = False,
) -> PluralLocalizationReport:
    """Run exact plural artifact validation without weakening the global command guard.

    The evidence copy of the probe script is stored outside the target repository. A byte-identical
    transient execution copy is placed beneath the Godot `.godot` cache because the repository-wide
    subprocess guard deliberately rejects external Godot path operands. The transient file is removed
    before the post-run Git state is accepted.
    """

    validate_plural_testlab_request(request)
    project_root = find_project_root(candidate).resolve(strict=True)
    git_before, git_commands_before = capture_git_state(project_root)
    if git_before.head != request["exactHead"]:
        raise ValueError(
            f"Target Git HEAD {git_before.head} does not match request exactHead {request['exactHead']}."
        )
    if git_before.origin.casefold() != request["repository"].casefold():
        raise ValueError(
            f"Target Git origin {git_before.origin} does not match request repository {request['repository']}."
        )

    git_root = Path(git_before.root)
    artifact_root = artifacts_root.expanduser().resolve()
    if _is_within(artifact_root, git_root):
        raise ValueError("Plural localization Test Lab artifacts must be outside the target Git repository.")
    artifact_root.mkdir(parents=True, exist_ok=True)

    csv_path = _safe_csv_path(project_root, str(request.get("csvPath", "")))
    csv_sha, csv_bytes = _verify_csv(csv_path, request)

    request_path = artifact_root / "request.json"
    request_path.write_text(
        json.dumps(request, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    native_root = artifact_root / "native-validation"
    native_report = validate_project_pipeline(
        project_root,
        godot_executable=godot_executable,
        dotnet_executable=dotnet_executable,
        minimum_godot_version=minimum_godot_version,
        timeout_seconds=max(1, timeout_seconds),
        boot_frames=max(0, boot_frames),
        run_integrity_audit=True,
        warnings_as_errors=warnings_as_errors,
        recovery_diagnostic=recovery_diagnostic,
        allow_major_upgrade=allow_major_upgrade,
        log_directory=native_root / "engine-logs",
    )
    write_report_bundle(native_report, native_root)

    findings: list[str] = []
    commands = [_command_payload(item) for item in git_commands_before]
    runtime_results = []
    native_passed = native_report.status == "passed"
    runtime_passed = False
    probe_command: CommandResult | None = None
    probe_payload: dict[str, Any] | None = None
    probe_evidence_path: Path | None = None
    transient_probe: Path | None = None

    if native_passed:
        godot = _select_godot_executable(native_report)
        probe_root = artifact_root / "plural-probe"
        probe_root.mkdir(parents=True, exist_ok=True)
        probe_evidence_path = probe_root / "plural_probe.gd"
        probe_source = _probe_script(request)
        probe_evidence_path.write_text(probe_source, encoding="utf-8")
        transient_probe = _transient_probe_path(project_root, request["sha256"])
        transient_probe.write_text(probe_source, encoding="utf-8")
        probe_result_path = probe_root / "probe-execution.json"
        try:
            probe_command = run_command(
                [
                    str(godot),
                    "--headless",
                    "--path",
                    str(project_root),
                    "--script",
                    str(transient_probe),
                ],
                project_root,
                max(1, timeout_seconds),
            )
            commands.append(_command_payload(probe_command))
            try:
                probe_payload = _parse_probe_payload(probe_command)
                runtime_results = _normalize_probe_results(request, probe_payload)
                runtime_passed = (
                    command_succeeded(probe_command)
                    and probe_payload.get("status") == "passed"
                    and bool(runtime_results)
                    and all(item.matched for item in runtime_results)
                )
            except (ValueError, json.JSONDecodeError) as error:
                findings.append(str(error))
                runtime_passed = False
            if probe_command.timed_out:
                findings.append("Godot plural runtime probe timed out.")
            elif probe_command.exit_code != 0:
                findings.append(
                    f"Godot plural runtime probe exited with code {probe_command.exit_code}."
                )
            if not runtime_passed and not findings:
                findings.append("One or more Godot plural runtime probes did not match expected text.")
        except OSError as error:
            findings.append(f"Godot plural runtime probe could not start: {error}")
            runtime_passed = False
        finally:
            cleanup_error = _cleanup_transient_probe(transient_probe)
            if cleanup_error:
                findings.append(cleanup_error)
            _write_probe_command_artifact(probe_result_path, probe_command, probe_payload)
    else:
        findings.append("Native Godot validation did not pass; plural runtime probes were withheld.")

    csv_sha_after, csv_bytes_after = _verify_csv(csv_path, request)
    if csv_sha_after != csv_sha or csv_bytes_after != csv_bytes:
        findings.append("Plural localization CSV bytes changed during validation.")

    git_after, git_commands_after = capture_git_state(project_root)
    commands.extend(_command_payload(item) for item in git_commands_after)
    if git_after.head != request["exactHead"]:
        findings.append("Target Git HEAD changed during validation.")
    if git_after.origin.casefold() != request["repository"].casefold():
        findings.append("Target Git origin changed during validation.")
    git_unchanged = _state_unchanged(git_before, git_after)
    if not git_unchanged:
        findings.append("Target Git state changed during plural localization validation.")

    passed = native_passed and runtime_passed and git_unchanged and not findings
    report = PluralLocalizationReport(
        version="evavo_godot_plural_localization_test_lab_report_v1",
        generated_at=_generated_at(),
        status="passed" if passed else "failed",
        request_sha256=request["sha256"],
        project_root=str(project_root),
        repository=request["repository"],
        exact_head=request["exactHead"],
        csv_path=request["csvPath"],
        csv_sha256=csv_sha,
        csv_bytes=csv_bytes,
        git_before=git_before,
        git_after=git_after,
        native_validation={
            "status": native_report.status,
            "schemaVersion": native_report.schema_version,
            "runId": native_report.run_id,
            "reportPath": str(native_root / "report.json"),
            "findings": list(native_report.findings),
            "diagnostics": list(native_report.diagnostics),
        },
        runtime_probes=runtime_results,
        findings=findings,
        commands=commands,
        artifacts=[],
        authority={
            "requestFingerprintVerified": True,
            "exactTargetHeadVerified": git_before.head == request["exactHead"],
            "exactCsvBytesVerified": (
                csv_sha == request["csvSha256"] and csv_bytes == request["csvBytes"]
            ),
            "nativeGodotImportVerified": native_passed,
            "runtimePluralLookupVerified": runtime_passed,
            "targetGitStateUnchanged": git_unchanged,
            "transientProbeRemovedBeforeAcceptance": (
                transient_probe is None or not transient_probe.exists()
            ),
            "targetRepositoryMutationAuthority": False,
            "repairAuthority": False,
            "publicationAuthority": False,
        },
    )

    report_path = artifact_root / "plural-localization-report.json"
    artifact_paths = [request_path, native_root / "report.json", report_path]
    if probe_evidence_path is not None:
        artifact_paths.extend(
            [probe_evidence_path, probe_evidence_path.parent / "probe-execution.json"]
        )
    report.artifacts = [str(item) for item in artifact_paths]
    report_path.write_text(report.to_json() + "\n", encoding="utf-8")
    return report
