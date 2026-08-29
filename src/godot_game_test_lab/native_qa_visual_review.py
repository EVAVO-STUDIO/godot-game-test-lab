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
_LAYOUT_FILE = "ui-layout-analysis.json"
_ISSUE_BUDGETS = {
    "viewport-clipping": ("maximumOutOfBoundsInteractive", 0),
    "ancestor-clipping": ("maximumAncestorClippedInteractive", 0),
    "center-occluded": ("maximumOccludedInteractive", 0),
    "interactive-overlap": ("maximumOverlappingInteractivePairs", 0),
    "interactive-spacing": ("maximumCloseInteractivePairs", 32),
    "small-target": ("maximumSmallInteractiveTargets", 8),
}


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


def _bounded_int(config: Mapping[str, Any], key: str, default: int) -> int:
    value = config.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return max(0, value)


def _admission_budgets(ux: Mapping[str, Any]) -> dict[str, Any]:
    budgets = {
        code: _bounded_int(ux, key, default)
        for code, (key, default) in _ISSUE_BUDGETS.items()
    }
    budgets["minimumVisibleControls"] = _bounded_int(
        ux, "minimumVisibleControls", 0
    )
    budgets["requireFocusOwner"] = ux.get("requireFocusOwner") is True
    budgets["failOnTruncatedLayoutAnalysis"] = (
        ux.get("failOnTruncatedLayoutAnalysis") is True
    )
    return budgets


def _snapshot_budget_findings(
    snapshot: Mapping[str, Any], ux: Mapping[str, Any]
) -> list[str]:
    snapshot_id = snapshot.get("id")
    label = snapshot_id if isinstance(snapshot_id, str) and snapshot_id else "unknown"
    analysis = snapshot.get("analysis")
    if not isinstance(analysis, Mapping):
        return [f"layout admission: {label} is missing its analysis object"]
    summary = analysis.get("summary")
    source = analysis.get("source")
    summary_data = summary if isinstance(summary, Mapping) else {}
    source_data = source if isinstance(source, Mapping) else {}
    raw_counts = summary_data.get("issueCounts")
    counts = raw_counts if isinstance(raw_counts, Mapping) else {}
    budgets = _admission_budgets(ux)
    findings: list[str] = []

    for code, (config_key, default) in _ISSUE_BUDGETS.items():
        actual = counts.get(code, 0)
        actual_count = actual if isinstance(actual, int) and not isinstance(actual, bool) else 0
        allowed = _bounded_int(ux, config_key, default)
        if actual_count > allowed:
            findings.append(
                f"layout admission: {label} has {actual_count} {code} issue(s); "
                f"the governed maximum is {allowed}"
            )

    visible = source_data.get("visibleControlCount", 0)
    visible_count = visible if isinstance(visible, int) and not isinstance(visible, bool) else 0
    minimum_visible = int(budgets["minimumVisibleControls"])
    if visible_count < minimum_visible:
        findings.append(
            f"layout admission: {label} retained {visible_count} visible control(s); "
            f"the governed minimum is {minimum_visible}"
        )

    focus_owner = source_data.get("focusOwner")
    if budgets["requireFocusOwner"] and not (
        isinstance(focus_owner, str) and focus_owner.strip()
    ):
        findings.append(f"layout admission: {label} has no GUI focus owner")

    if budgets["failOnTruncatedLayoutAnalysis"] and summary_data.get("truncated") is True:
        findings.append(
            f"layout admission: {label} reached a semantic layout analysis bound"
        )
    return findings


def _governed_layout_findings(
    analysis: Mapping[str, Any], ux: Mapping[str, Any]
) -> list[str]:
    snapshots = analysis.get("snapshots", [])
    if not isinstance(snapshots, Sequence) or isinstance(snapshots, (str, bytes)):
        return ["layout admission: snapshot collection is invalid"]
    findings: list[str] = []
    for snapshot in snapshots:
        if isinstance(snapshot, Mapping):
            findings.extend(_snapshot_budget_findings(snapshot, ux))
        else:
            findings.append("layout admission: snapshot entry is not an object")
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
    layout_findings = _governed_layout_findings(analysis, ux)
    analysis["admission"] = {
        "status": "failed" if layout_findings else "passed",
        "budgets": _admission_budgets(ux),
        "findings": sorted(set(layout_findings)),
    }
    analysis["reviewPending"] = ["visual", "game-feel", "content"]
    analysis["truthBoundary"] = (
        "Deterministic geometry identifies and retains layout risks. Admission honours the "
        "normalized journey budgets, but does not replace rendered image, motion, "
        "accessibility, game-feel or human visual review."
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

    admission_failure_detected = False
    journeys: list[dict[str, Any]] = []
    for raw in journeys_raw:
        if not isinstance(raw, dict):
            raise NativeQaError("Native QA summary contains a non-object journey")
        admission_failure_detected = (
            _augment_journey(artifacts, raw) or admission_failure_detected
        )
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
    if admission_failure_detected:
        findings.append("semantic UI layout evidence exceeded a governed journey budget")
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
