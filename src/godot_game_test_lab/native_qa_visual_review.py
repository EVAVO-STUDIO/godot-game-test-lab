from __future__ import annotations

import re
from argparse import Namespace
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .native_qa_common import (
    NativeQaError,
    _canonical_json,
    _directory_usage,
    _load_json_object,
)
from .native_qa_evidence import _artifact_inventory
from .ui_layout_analysis import analyze_ui_snapshots

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_SEVERE = {"major", "critical"}
_LAYOUT_FILE = "ui-layout-analysis.json"


def _resolve_journey_root(artifacts: Path, journey_id: str) -> Path:
    if _ID_RE.fullmatch(journey_id) is None:
        raise NativeQaError(f"Journey summary contains an unsafe id: {journey_id!r}")
    requested = artifacts / "journeys" / journey_id
    if requested.is_symlink():
        raise NativeQaError(f"Journey evidence may not be a symbolic link: {requested}")
    resolved = requested.resolve(strict=True)
    if not resolved.is_dir() or not resolved.is_relative_to(artifacts):
        raise NativeQaError(f"Journey evidence root is invalid: {requested}")
    return resolved


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _string_list(value: object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _severe_layout_findings(analysis: Mapping[str, Any]) -> list[str]:
    findings: list[str] = []
    snapshots = analysis.get("snapshots", [])
    if not isinstance(snapshots, Sequence) or isinstance(snapshots, (str, bytes)):
        return findings
    for snapshot in snapshots:
        if not isinstance(snapshot, Mapping):
            continue
        snapshot_id = snapshot.get("id")
        label = snapshot_id if isinstance(snapshot_id, str) and snapshot_id else "unknown"
        result = snapshot.get("analysis")
        if not isinstance(result, Mapping):
            continue
        issues = result.get("issues", [])
        if not isinstance(issues, Sequence) or isinstance(issues, (str, bytes)):
            continue
        counts: dict[str, int] = {}
        for issue in issues:
            if not isinstance(issue, Mapping) or issue.get("severity") not in _SEVERE:
                continue
            code = issue.get("code")
            if isinstance(code, str) and code:
                counts[code] = counts.get(code, 0) + 1
        for code, count in sorted(counts.items()):
            findings.append(
                f"layout analysis: {label} has {count} major or critical {code} issue(s)"
            )
    return findings


def _augment_journey(
    artifacts: Path,
    journey: dict[str, Any],
) -> bool:
    journey_id = journey.get("id")
    if not isinstance(journey_id, str):
        raise NativeQaError("Journey summary is missing its id")
    harness = journey.get("harness")
    if not isinstance(harness, Mapping):
        return False
    journey_root = _resolve_journey_root(artifacts, journey_id)
    profile_path = journey_root / "journey.normalized.json"
    profile = _load_json_object(profile_path, "normalized journey profile")
    ux = _mapping(profile.get("ux"))
    analysis = analyze_ui_snapshots(harness, ux)
    analysis["reviewPending"] = ["visual", "game-feel", "content"]
    analysis["truthBoundary"] = (
        "Deterministic geometry identifies layout risks but does not replace rendered image, "
        "motion, accessibility, game-feel or human visual review."
    )
    destination = journey_root / _LAYOUT_FILE
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_text(_canonical_json(analysis), encoding="utf-8")
    temporary.replace(destination)

    relative = destination.relative_to(artifacts).as_posix()
    evidence = _string_list(journey.get("evidence"))
    evidence.append(relative)
    journey["evidence"] = sorted(set(evidence))
    journey["layoutAnalysis"] = analysis

    layout_findings = _severe_layout_findings(analysis)
    if layout_findings:
        findings = _string_list(journey.get("findings"))
        findings.extend(layout_findings)
        journey["findings"] = sorted(set(findings))
        if journey.get("status") == "passed":
            journey["status"] = "failed"
    return bool(layout_findings)


def augment_native_qa_summary(args: Namespace, summary: dict[str, Any]) -> dict[str, Any]:
    artifacts = Path(args.artifacts).expanduser().resolve(strict=True)
    maximum_artifact_bytes = int(args.max_artifact_bytes)
    journeys_raw = summary.get("journeys", [])
    if not isinstance(journeys_raw, list):
        raise NativeQaError("Native QA summary journeys must be an array")

    severe_detected = False
    journeys: list[dict[str, Any]] = []
    for raw in journeys_raw:
        if not isinstance(raw, dict):
            raise NativeQaError("Native QA summary contains a non-object journey")
        severe_detected = _augment_journey(artifacts, raw) or severe_detected
        journeys.append(raw)
    summary["journeys"] = journeys

    required_failures = [
        item
        for item in journeys
        if item.get("required") is True and item.get("status") != "passed"
    ]
    optional_failures = [
        item
        for item in journeys
        if item.get("required") is not True and item.get("status") != "passed"
    ]
    findings = _string_list(summary.get("findings"))
    if required_failures:
        summary["status"] = "failed"
        findings.append("one or more required native journeys did not pass")
    if optional_failures:
        findings.append("one or more optional native journeys did not pass")
    if severe_detected:
        findings.append("semantic UI layout analysis detected major or critical defects")
    summary["findings"] = sorted(set(findings))

    boundary = str(summary.get("truthBoundary", "")).strip()
    layout_boundary = (
        "Semantic layout evidence does not certify visual quality or replace inspection of "
        "the retained screenshots and video frames."
    )
    if layout_boundary not in boundary:
        summary["truthBoundary"] = f"{boundary} {layout_boundary}".strip()

    used_bytes, used_files, complete = _directory_usage(artifacts)
    if not complete or used_bytes > maximum_artifact_bytes:
        raise NativeQaError("Layout analysis exceeded the native QA artifact budget")
    execution_budget = summary.get("executionBudget")
    if isinstance(execution_budget, dict):
        execution_budget["retainedArtifactBytes"] = used_bytes
        execution_budget["retainedArtifactFiles"] = used_files
        execution_budget["measurementComplete"] = complete
    summary["artifacts"] = _artifact_inventory(
        artifacts,
        maximum_total_bytes=maximum_artifact_bytes,
    )
    summary_path = artifacts / "native-agent-summary.json"
    summary_path.write_text(_canonical_json(summary), encoding="utf-8")
    return summary
