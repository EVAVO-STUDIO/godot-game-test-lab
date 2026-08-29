from __future__ import annotations

from collections.abc import Mapping, Sequence
from hashlib import sha256
from math import isfinite
from typing import Any

ISSUE_CODES = (
    "interactive-overlap",
    "interactive-spacing",
    "viewport-clipping",
    "ancestor-clipping",
    "center-occluded",
    "small-target",
)
SEVERITY_RANK = {"info": 0, "minor": 1, "major": 2, "critical": 3}
INTERACTIVE_CLASSES = {
    "BaseButton",
    "Button",
    "CheckBox",
    "CheckButton",
    "ColorPickerButton",
    "HScrollBar",
    "HSlider",
    "ItemList",
    "LineEdit",
    "LinkButton",
    "MenuButton",
    "OptionButton",
    "Range",
    "SpinBox",
    "TabBar",
    "TextEdit",
    "Tree",
    "VScrollBar",
    "VSlider",
}


def _number(value: object, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)) and isfinite(float(value)):
        return float(value)
    return default


def _integer(value: object, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    return default


def _rect(record: Mapping[str, Any]) -> dict[str, float]:
    nested = record.get("rect")
    source = nested if isinstance(nested, Mapping) else record
    x = _number(source.get("x"))
    y = _number(source.get("y"))
    width = max(0.0, _number(source.get("width")))
    height = max(0.0, _number(source.get("height")))
    return {
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "right": x + width,
        "bottom": y + height,
    }


def _path(record: Mapping[str, Any], index: int) -> str:
    value = record.get("path")
    return value if isinstance(value, str) and value else f"control:{index + 1:04d}"


def _is_interactive(record: Mapping[str, Any]) -> bool:
    explicit = record.get("interactive")
    if isinstance(explicit, bool):
        return explicit
    if _integer(record.get("focusMode"), 0) != 0:
        return True
    class_name = record.get("class")
    return isinstance(class_name, str) and class_name in INTERACTIVE_CLASSES


def _is_disabled(record: Mapping[str, Any]) -> bool:
    if record.get("disabled") is True or record.get("editable") is False:
        return True
    return False


def _ancestor_paths(record: Mapping[str, Any]) -> set[str]:
    raw = record.get("ancestorPaths", [])
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return set()
    return {value for value in raw if isinstance(value, str) and value}


def _related(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    left_path = str(left["path"])
    right_path = str(right["path"])
    if left_path in right["ancestorPaths"] or right_path in left["ancestorPaths"]:
        return True
    return right_path.startswith(f"{left_path}/") or left_path.startswith(f"{right_path}/")


def _intersection(
    left: Mapping[str, float], right: Mapping[str, float]
) -> dict[str, float] | None:
    x = max(left["x"], right["x"])
    y = max(left["y"], right["y"])
    edge_x = min(left["right"], right["right"])
    edge_y = min(left["bottom"], right["bottom"])
    if edge_x <= x or edge_y <= y:
        return None
    return {
        "x": x,
        "y": y,
        "width": edge_x - x,
        "height": edge_y - y,
        "right": edge_x,
        "bottom": edge_y,
    }


def _axis_gap(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    if a_end < b_start:
        return b_start - a_end
    if b_end < a_start:
        return a_start - b_end
    return 0.0


def _overlap_size(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def _issue_id(code: str, paths: Sequence[str]) -> str:
    digest = sha256((code + "\0" + "\0".join(sorted(paths))).encode()).hexdigest()[:16]
    return f"layout:{code}:{digest}"


def _overlap_severity(minimum_coverage: float) -> str:
    if minimum_coverage >= 0.75:
        return "critical"
    if minimum_coverage >= 0.25:
        return "major"
    return "minor"


def _issue(
    code: str,
    severity: str,
    paths: Sequence[str],
    description: str,
    metrics: Mapping[str, Any],
    confidence: float = 1.0,
) -> dict[str, Any]:
    return {
        "id": _issue_id(code, paths),
        "code": code,
        "severity": severity,
        "confidence": confidence,
        "paths": list(paths),
        "description": description,
        "metrics": dict(metrics),
    }


def _normalize_controls(snapshot: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw_controls = snapshot.get("controls", [])
    if not isinstance(raw_controls, Sequence) or isinstance(raw_controls, (str, bytes)):
        return []
    controls: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_controls):
        if not isinstance(raw, Mapping):
            continue
        controls.append(
            {
                **raw,
                "path": _path(raw, index),
                "rect": _rect(raw),
                "interactive": _is_interactive(raw),
                "disabled": _is_disabled(raw),
                "ancestorPaths": _ancestor_paths(raw),
            }
        )
    return controls


def analyze_ui_layout(
    snapshot: Mapping[str, Any], config: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    options = config or {}
    minimum_width = _number(options.get("minimumInteractiveWidth"), 24.0)
    minimum_height = _number(options.get("minimumInteractiveHeight"), 24.0)
    minimum_gap = _number(options.get("minimumInteractiveGap"), 8.0)
    maximum_pair_checks = max(0, _integer(options.get("maximumPairChecks"), 50_000))
    maximum_issues = max(1, _integer(options.get("maximumIssues"), 1_024))
    viewport_raw = snapshot.get("viewport", {})
    viewport = viewport_raw if isinstance(viewport_raw, Mapping) else {}
    viewport_width = max(0.0, _number(viewport.get("width")))
    viewport_height = max(0.0, _number(viewport.get("height")))
    controls = _normalize_controls(snapshot)
    interactive = [
        control
        for control in controls
        if control["interactive"] and not control["disabled"]
    ]
    issues: list[dict[str, Any]] = []
    truncated = False

    def append_issue(value: dict[str, Any]) -> bool:
        nonlocal truncated
        if len(issues) >= maximum_issues:
            truncated = True
            return False
        issues.append(value)
        return True

    for control in interactive:
        rect = control["rect"]
        path = str(control["path"])
        inside_viewport = control.get("insideViewport")
        clipped_viewport = (
            inside_viewport is False
            or rect["x"] < 0
            or rect["y"] < 0
            or (viewport_width > 0 and rect["right"] > viewport_width)
            or (viewport_height > 0 and rect["bottom"] > viewport_height)
        )
        if clipped_viewport and not append_issue(
            _issue(
                "viewport-clipping",
                "major",
                [path],
                f"{path} extends outside the rendered viewport.",
                {
                    "viewportWidth": viewport_width,
                    "viewportHeight": viewport_height,
                    **rect,
                },
            )
        ):
            break
        if control.get("clippedByAncestor") is True and not append_issue(
            _issue(
                "ancestor-clipping",
                "major",
                [path],
                f"{path} is clipped by an ancestor Control.",
                {"clippedByAncestor": True},
                0.95,
            )
        ):
            break
        blocker = control.get("centerBlockedBy")
        if isinstance(blocker, str) and blocker and not append_issue(
            _issue(
                "center-occluded",
                "major",
                [path, blocker],
                f"{path} is blocked at its centre by {blocker}.",
                {"blocked": True},
                0.95,
            )
        ):
            break
        if (rect["width"] < minimum_width or rect["height"] < minimum_height) and not (
            append_issue(
                _issue(
                    "small-target",
                    "minor",
                    [path],
                    f"{path} is smaller than the governed interactive target size.",
                    {
                        "width": rect["width"],
                        "height": rect["height"],
                        "minimumWidth": minimum_width,
                        "minimumHeight": minimum_height,
                    },
                )
            )
        ):
            break

    pair_checks = 0
    for left_index, left in enumerate(interactive):
        if truncated:
            break
        for right in interactive[left_index + 1 :]:
            if pair_checks >= maximum_pair_checks or len(issues) >= maximum_issues:
                truncated = True
                break
            pair_checks += 1
            if _related(left, right):
                continue
            left_rect = left["rect"]
            right_rect = right["rect"]
            left_path = str(left["path"])
            right_path = str(right["path"])
            overlap = _intersection(left_rect, right_rect)
            if overlap:
                overlap_area = overlap["width"] * overlap["height"]
                left_area = left_rect["width"] * left_rect["height"]
                right_area = right_rect["width"] * right_rect["height"]
                left_coverage = overlap_area / left_area if left_area else 0.0
                right_coverage = overlap_area / right_area if right_area else 0.0
                minimum_coverage = min(left_coverage, right_coverage)
                append_issue(
                    _issue(
                        "interactive-overlap",
                        _overlap_severity(minimum_coverage),
                        [left_path, right_path],
                        f"{left_path} and {right_path} overlap in the rendered UI.",
                        {
                            "overlapArea": overlap_area,
                            "overlapWidth": overlap["width"],
                            "overlapHeight": overlap["height"],
                            "leftCoverage": left_coverage,
                            "rightCoverage": right_coverage,
                            "minimumCoverage": minimum_coverage,
                            "leftPaintOrder": _integer(left.get("paintOrder"), -1),
                            "rightPaintOrder": _integer(right.get("paintOrder"), -1),
                        },
                    )
                )
                continue
            horizontal_overlap = _overlap_size(
                left_rect["x"], left_rect["right"], right_rect["x"], right_rect["right"]
            )
            vertical_overlap = _overlap_size(
                left_rect["y"],
                left_rect["bottom"],
                right_rect["y"],
                right_rect["bottom"],
            )
            horizontal_gap = _axis_gap(
                left_rect["x"], left_rect["right"], right_rect["x"], right_rect["right"]
            )
            vertical_gap = _axis_gap(
                left_rect["y"],
                left_rect["bottom"],
                right_rect["y"],
                right_rect["bottom"],
            )
            relevant_gap: float | None = None
            if horizontal_overlap > 0:
                relevant_gap = vertical_gap
            elif vertical_overlap > 0:
                relevant_gap = horizontal_gap
            if relevant_gap is not None and relevant_gap < minimum_gap:
                append_issue(
                    _issue(
                        "interactive-spacing",
                        "major" if relevant_gap == 0 else "minor",
                        [left_path, right_path],
                        f"{left_path} and {right_path} have only {relevant_gap:g}px separation.",
                        {
                            "gap": relevant_gap,
                            "minimumGap": minimum_gap,
                            "horizontalOverlap": horizontal_overlap,
                            "verticalOverlap": vertical_overlap,
                        },
                    )
                )

    counts = {code: 0 for code in ISSUE_CODES}
    for issue in issues:
        counts[str(issue["code"])] += 1
    highest = max(
        (str(issue["severity"]) for issue in issues),
        key=lambda value: SEVERITY_RANK[value],
        default=None,
    )
    return {
        "schemaVersion": 1,
        "viewport": {"width": viewport_width, "height": viewport_height},
        "controlCount": len(controls),
        "interactiveControlCount": len(interactive),
        "issues": issues,
        "summary": {
            "issueCount": len(issues),
            "issueCounts": counts,
            "highestSeverity": highest,
            "pairChecks": pair_checks,
            "truncated": truncated,
        },
    }


def analyze_ui_snapshots(
    report: Mapping[str, Any], config: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    snapshots: list[dict[str, Any]] = []
    raw_checkpoints = report.get("checkpointUi", [])
    if isinstance(raw_checkpoints, Sequence) and not isinstance(
        raw_checkpoints, (str, bytes)
    ):
        for index, raw in enumerate(raw_checkpoints):
            if not isinstance(raw, Mapping):
                continue
            ui = raw.get("ui")
            if not isinstance(ui, Mapping):
                continue
            checkpoint_id = raw.get("id")
            snapshots.append(
                {
                    "id": checkpoint_id
                    if isinstance(checkpoint_id, str) and checkpoint_id
                    else f"checkpoint-{index + 1}",
                    "analysis": analyze_ui_layout(ui, config),
                }
            )
    final_ui = report.get("ui")
    if isinstance(final_ui, Mapping):
        snapshots.append({"id": "final", "analysis": analyze_ui_layout(final_ui, config)})
    total_issues = sum(item["analysis"]["summary"]["issueCount"] for item in snapshots)
    severe_issues = sum(
        1
        for item in snapshots
        for issue in item["analysis"]["issues"]
        if issue["severity"] in {"major", "critical"}
    )
    return {
        "schemaVersion": 1,
        "snapshotCount": len(snapshots),
        "issueCount": total_issues,
        "majorOrCriticalIssueCount": severe_issues,
        "snapshots": snapshots,
    }
