from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path, PurePosixPath
from typing import Any

from .audio_analysis_contract import (
    _contract_authority,
    _index_rows,
    _policy_blockers,
    _role_for_path,
    _runtime_format_blockers,
    _selected_audio,
    _validate_analysis_authority,
    _validate_inventory_authority,
)
from .audio_analysis_io import (
    _canonical_directory,
    _is_within,
    _read_json,
    _read_regular,
    _reject_link_components,
    _repository_state,
)
from .audio_analysis_media import (
    _close,
    _import_blockers,
    _import_evidence,
    _metadata,
)
from .audio_analysis_types import (
    ANALYSIS_ID,
    CHECK_ID,
    CONTRACT_ID,
    INVENTORY_ID,
    MAXIMUM_AUDIO_BYTES,
    MAXIMUM_JSON_BYTES,
    REPORT_ID,
    SELECTION_ID,
    TARGET_REPOSITORY,
    AudioAnalysisVerificationError,
)

__all__ = (
    "ANALYSIS_ID",
    "AudioAnalysisVerificationError",
    "CONTRACT_ID",
    "INVENTORY_ID",
    "REPORT_ID",
    "SELECTION_ID",
    "TARGET_REPOSITORY",
    "validate_audio_analysis",
    "write_report",
)


def _finding(code: str, message: str, *, path: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "code": code,
        "severity": "error",
        "message": message,
    }
    if path is not None:
        result["path"] = path
    return result


def validate_audio_analysis(
    project: Path,
    contract_path: Path,
    selection_path: Path,
    inventory_path: Path,
    analysis_path: Path,
    *,
    strict: bool = True,
) -> dict[str, Any]:
    repository = _canonical_directory(project, "Brass & Brine repository")
    project_file = repository / "project.godot"
    _read_regular(project_file, "project.godot", 8 * 1024 * 1024, retain_payload=False)
    state_before = _repository_state(repository)

    contract_file, contract_bytes, contract, contract_sha = _read_json(
        contract_path,
        "Audio production contract",
    )
    selection_file, selection_bytes, selection, selection_sha = _read_json(
        selection_path,
        "Audio publication selection",
    )
    inventory_file, inventory_bytes, inventory, inventory_sha = _read_json(
        inventory_path,
        "Audio inventory",
    )
    analysis_file, analysis_bytes, analysis, analysis_sha = _read_json(
        analysis_path,
        "Audio Studio analysis report",
    )

    roles, buses, mastering = _contract_authority(contract)
    selected = _selected_audio(selection, state_before["head"])
    inventory_rows = _validate_inventory_authority(
        inventory,
        head=state_before["head"],
        contract_sha=contract_sha,
        selection_sha=selection_sha,
        observed_state=state_before,
    )
    analyzed_paths, analysis_rows = _validate_analysis_authority(
        analysis,
        head=state_before["head"],
        contract_sha=contract_sha,
        selection_sha=selection_sha,
        inventory_sha=inventory_sha,
        observed_state=state_before,
    )
    inventory_by_path = _index_rows(inventory_rows, label="inventory.files")
    analysis_by_path = _index_rows(analysis_rows, label="analysis.results")
    if selected != analyzed_paths:
        raise AudioAnalysisVerificationError(
            "Audio Studio analyzedPaths do not equal the selected audio paths"
        )
    if selected != sorted(inventory_by_path, key=str.casefold):
        raise AudioAnalysisVerificationError(
            "Audio inventory paths do not equal the selected audio paths"
        )
    if selected != sorted(analysis_by_path, key=str.casefold):
        raise AudioAnalysisVerificationError(
            "Audio analysis result paths do not equal the selected audio paths"
        )

    findings: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    final_files: list[dict[str, Any]] = []
    for relative in selected:
        inventory_row = inventory_by_path[relative]
        analysis_row = analysis_by_path[relative]
        file_path = repository.joinpath(*PurePosixPath(relative).parts)
        resolved, size, digest, _ = _read_regular(
            file_path,
            relative,
            MAXIMUM_AUDIO_BYTES,
            retain_payload=False,
        )
        metadata = _metadata(resolved)
        role_id = _role_for_path(relative, roles)
        blockers: list[str] = []
        if role_id is None:
            blockers.append("unresolved-or-ambiguous-audio-role")
            role = None
            bus = None
        else:
            role = roles[role_id]
            bus = buses[role["bus"]]

        if inventory_row.get("sha256") != digest or inventory_row.get("bytes") != size:
            blockers.append("current-runtime-identity-mismatch")
        if analysis_row.get("sourceSha256") != digest:
            blockers.append("analysis-source-sha256-mismatch")
        if analysis_row.get("runtimeSha256") != digest:
            blockers.append("analysis-runtime-sha256-mismatch")
        if analysis_row.get("sourceRelationship") != "selected-runtime-self":
            blockers.append("analysis-source-relationship-invalid")
        if role_id is not None:
            if inventory_row.get("role") != role_id or analysis_row.get("role") != role_id:
                blockers.append("audio-role-mismatch")
            if inventory_row.get("bus") != role["bus"] or analysis_row.get("bus") != role["bus"]:
                blockers.append("audio-bus-mismatch")
            blockers.extend(_runtime_format_blockers(relative, role, metadata))
            blockers.extend(_policy_blockers(inventory_row, role, bus, mastering))

        for key in ("sampleRateHz", "bitDepth", "channels"):
            if inventory_row.get(key) != metadata[key]:
                blockers.append(f"independent-{key}-mismatch")
        if not _close(
            inventory_row.get("durationSeconds"),
            metadata["durationSeconds"],
            tolerance=max(0.001, 1.0 / max(1, metadata["sampleRateHz"])),
        ):
            blockers.append("independent-duration-mismatch")
        metrics = analysis_row.get("metrics")
        if not isinstance(metrics, dict):
            blockers.append("analysis-metrics-missing")
            metrics = {}
        for key in (
            "sampleRateHz",
            "bitDepth",
            "channels",
            "durationSeconds",
            "integratedLufs",
            "truePeakDbtp",
            "rmsDbfs",
            "dcOffset",
            "leadingSilenceMs",
            "trailingSilenceMs",
            "clippingSamples",
            "loopStartSamples",
            "loopEndSamples",
            "loopBoundarySampleDelta",
        ):
            tolerance = 0.001 if key == "durationSeconds" else 1e-6
            if not _close(inventory_row.get(key), metrics.get(key), tolerance=tolerance):
                blockers.append(f"inventory-analysis-{key}-mismatch")
        inventory_findings = inventory_row.get("findings")
        result_blockers = analysis_row.get("blockers")
        if not isinstance(inventory_findings, list) or not isinstance(result_blockers, list):
            blockers.append("upstream-blocker-list-invalid")
            upstream_blockers: list[str] = []
        else:
            upstream_blockers = sorted(
                {
                    str(value)
                    for value in [*inventory_findings, *result_blockers]
                    if isinstance(value, str) and value
                }
            )
            if sorted(inventory_findings) != sorted(result_blockers):
                blockers.append("inventory-analysis-blockers-mismatch")
        blockers.extend(upstream_blockers)

        import_evidence = _import_evidence(repository, relative)
        if role_id is not None:
            blockers.extend(_import_blockers(relative, role, import_evidence))
        reported_import = metrics.get("godotImport")
        if not isinstance(reported_import, dict):
            blockers.append("analysis-godot-import-evidence-missing")
        else:
            for key in ("path", "present", "sha256", "bytes"):
                if reported_import.get(key) != import_evidence.get(key):
                    blockers.append(f"godot-import-{key}-mismatch")

        blockers = sorted(set(blockers))
        upstream_status = analysis_row.get("status")
        if upstream_status not in {"passed", "blocked"}:
            blockers.append("analysis-result-status-invalid")
        elif (upstream_status == "passed") != (not upstream_blockers):
            blockers.append("analysis-result-status-incoherent")
        blockers = sorted(set(blockers))
        result_status = "passed" if not blockers else "failed"
        results.append(
            {
                "path": relative,
                "sha256": digest,
                "bytes": size,
                "role": role_id or "unresolved",
                "bus": role["bus"] if role_id is not None else "unresolved",
                "status": result_status,
                "blockers": blockers,
                "independentMetadata": metadata,
                "godotImport": import_evidence,
            }
        )
        for blocker in blockers:
            findings.append(
                _finding(
                    blocker,
                    f"Audio verification failed for {relative}: {blocker}",
                    path=relative,
                )
            )
        final_files.append(
            {
                "path": relative,
                "sha256": digest,
                "bytes": size,
                "import": import_evidence,
            }
        )

    if analysis.get("status") == "passed" and any(
        row.get("status") != "passed" for row in analysis_rows
    ):
        findings.append(
            _finding(
                "analysis-summary-status-incoherent",
                "Audio Studio report status is passed while one result is not passed",
            )
        )
    if strict and analysis.get("status") != "passed":
        findings.append(
            _finding(
                "strict-upstream-analysis-not-passed",
                "Strict Test Lab validation requires a passed Audio Studio report",
            )
        )

    state_after = _repository_state(repository)
    if (
        state_after["head"] != state_before["head"]
        or state_after["origin"] != state_before["origin"]
        or state_after["status"] != state_before["status"]
        or state_after["statusSha256"] != state_before["statusSha256"]
    ):
        raise AudioAnalysisVerificationError(
            "Brass & Brine repository state changed during Test Lab validation"
        )
    for source, payload, label in (
        (contract_file, contract_bytes, "Audio production contract"),
        (selection_file, selection_bytes, "Audio publication selection"),
        (inventory_file, inventory_bytes, "Audio inventory"),
        (analysis_file, analysis_bytes, "Audio Studio analysis report"),
    ):
        _, _, _, current = _read_regular(
            source,
            f"{label} final identity",
            MAXIMUM_JSON_BYTES,
            retain_payload=True,
        )
        if current != payload:
            raise AudioAnalysisVerificationError(
                f"{label} changed during Test Lab validation"
            )
    for row in final_files:
        _, size, digest, _ = _read_regular(
            repository.joinpath(*PurePosixPath(row["path"]).parts),
            f"{row['path']} final identity",
            MAXIMUM_AUDIO_BYTES,
            retain_payload=False,
        )
        if size != row["bytes"] or digest != row["sha256"]:
            raise AudioAnalysisVerificationError(
                f"Selected audio changed during final identity recheck: {row['path']}"
            )
        imported = row["import"]
        if imported["present"]:
            _, import_size, import_sha, _ = _read_regular(
                repository.joinpath(*PurePosixPath(imported["path"]).parts),
                f"{imported['path']} final identity",
                1024 * 1024,
                retain_payload=False,
            )
            if import_size != imported["bytes"] or import_sha != imported["sha256"]:
                raise AudioAnalysisVerificationError(
                    f"Godot import changed during final identity recheck: {imported['path']}"
                )

    status = "passed" if not findings else "failed"
    return {
        "schemaVersion": "1.0",
        "report": REPORT_ID,
        "tool": "godot-game-test-lab",
        "check": CHECK_ID,
        "status": status,
        "targetRepository": TARGET_REPOSITORY,
        "targetHeadSha": state_before["head"],
        "contractSha256": contract_sha,
        "selectionSha256": selection_sha,
        "inventorySha256": inventory_sha,
        "analysisReportSha256": analysis_sha,
        "selectedPaths": selected,
        "results": results,
        "summary": {
            "selectedPaths": len(selected),
            "passedPaths": sum(row["status"] == "passed" for row in results),
            "failedPaths": sum(row["status"] != "passed" for row in results),
            "findings": len(findings),
        },
        "findings": findings,
        "sourceState": {
            "before": {
                "branch": state_before["branch"],
                "origin": state_before["origin"],
                "targetSha": state_before["head"],
                "statusSha256": state_before["statusSha256"],
            },
            "after": {
                "branch": state_after["branch"],
                "origin": state_after["origin"],
                "targetSha": state_after["head"],
                "statusSha256": state_after["statusSha256"],
            },
            "unchanged": True,
        },
        "finalIdentityRecheck": True,
        "strict": strict,
        "mutationPerformed": False,
        "publicationAuthority": False,
        "humanListeningApproval": False,
        "godotGameplayMixApproval": False,
        "provenanceApproval": False,
        "truthBoundaries": [
            "Independent technical validation is not human listening approval.",
            "A passing report is not native Godot gameplay-mix approval.",
            "A passing report is not provenance or public release approval.",
            "Only Development Studio may execute governed publication.",
        ],
    }


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")


def write_report(
    report: dict[str, Any],
    *,
    output: Path,
    evidence_root: Path,
    protected_roots: tuple[Path, ...],
) -> Path:
    root = _canonical_directory(evidence_root, "Audio evidence root")
    expanded = output.expanduser()
    requested = expanded if expanded.is_absolute() else root / expanded
    requested = Path(os.path.abspath(os.fspath(requested)))
    requested = _reject_link_components(requested, "Audio Test Lab report output")
    if not _is_within(requested, root):
        raise AudioAnalysisVerificationError(
            "Audio Test Lab report output must remain below the evidence root"
        )
    for protected in protected_roots:
        if _is_within(requested, protected) or _is_within(protected, requested):
            raise AudioAnalysisVerificationError(
                "Audio Test Lab report output overlaps a protected source root"
            )
    requested.parent.mkdir(parents=True, exist_ok=True)
    parent = _canonical_directory(requested.parent, "Audio report output parent")
    target = parent / requested.name
    if target.exists() or target.is_symlink():
        raise AudioAnalysisVerificationError(
            "Audio Test Lab report output already exists"
        )
    payload = _json_bytes(report)
    with target.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    return target


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="godot-lab-audio-analysis",
        description=(
            "Independently verify exact Brass & Brine Audio Studio evidence "
            "against current Godot project bytes."
        ),
    )
    parser.add_argument("project", type=Path)
    parser.add_argument("contract", type=Path)
    parser.add_argument("selection", type=Path)
    parser.add_argument("inventory", type=Path)
    parser.add_argument("analysis", type=Path)
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--evidence-root", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = validate_audio_analysis(
            args.project,
            args.contract,
            args.selection,
            args.inventory,
            args.analysis,
            strict=args.strict,
        )
        if args.output is not None:
            if args.evidence_root is None:
                raise AudioAnalysisVerificationError(
                    "--evidence-root is required with --output"
                )
            written = write_report(
                report,
                output=args.output,
                evidence_root=args.evidence_root,
                protected_roots=(
                    _canonical_directory(args.project, "Brass & Brine repository"),
                ),
            )
            report["outputPath"] = str(written)
    except (AudioAnalysisVerificationError, OSError, UnicodeError) as error:
        print(
            json.dumps(
                {
                    "schemaVersion": "1.0",
                    "report": REPORT_ID,
                    "status": "failed",
                    "error": str(error),
                    "mutationPerformed": False,
                    "publicationAuthority": False,
                },
                indent=2,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
