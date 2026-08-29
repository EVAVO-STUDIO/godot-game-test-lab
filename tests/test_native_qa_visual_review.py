from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import pytest

from godot_game_test_lab.native_qa_common import NativeQaError
from godot_game_test_lab.native_qa_visual_review import augment_native_qa_summary


def control(path: str, x: float, width: float = 80) -> dict[str, object]:
    return {
        "path": path,
        "class": "Button",
        "interactive": True,
        "x": x,
        "y": 10,
        "width": width,
        "height": 40,
        "insideViewport": True,
    }


def fixture_summary(
    tmp_path: Path,
    controls: list[dict[str, object]],
    ux: dict[str, object] | None = None,
) -> tuple[Namespace, dict[str, object]]:
    journey_root = tmp_path / "journeys" / "menu"
    journey_root.mkdir(parents=True)
    (journey_root / "journey.normalized.json").write_text(
        json.dumps({"ux": {"minimumInteractiveWidth": 24, **(ux or {})}}),
        encoding="utf-8",
    )
    summary: dict[str, object] = {
        "status": "passed",
        "findings": [],
        "truthBoundary": "Existing boundary.",
        "executionBudget": {},
        "journeys": [
            {
                "id": "menu",
                "required": True,
                "status": "passed",
                "harness": {
                    "ui": {
                        "viewport": {"width": 320, "height": 200},
                        "visibleControlCount": len(controls),
                        "interactiveControlCount": len(controls),
                        "controls": controls,
                    }
                },
                "findings": [],
                "evidence": [],
            }
        ],
    }
    args = Namespace(artifacts=tmp_path, max_artifact_bytes=10 * 1024 * 1024)
    return args, summary


def first_journey(result: dict[str, object]) -> dict[str, object]:
    journeys = result["journeys"]
    assert isinstance(journeys, list)
    journey = journeys[0]
    assert isinstance(journey, dict)
    return journey


def test_overlap_beyond_default_budget_fails_required_journey(tmp_path: Path) -> None:
    args, summary = fixture_summary(
        tmp_path,
        [control("/root/Save", 10), control("/root/Cancel", 50)],
    )
    result = augment_native_qa_summary(args, summary)
    journey = first_journey(result)
    analysis = journey["layoutAnalysis"]
    assert isinstance(analysis, dict)
    assert result["status"] == "failed"
    assert journey["status"] == "failed"
    assert analysis["majorOrCriticalIssueCount"] == 1
    assert analysis["admission"]["status"] == "failed"
    assert "journeys/menu/ui-layout-analysis.json" in journey["evidence"]
    assert (tmp_path / "journeys" / "menu" / "ui-layout-analysis.json").is_file()
    assert (tmp_path / "native-agent-summary.json").is_file()


def test_overlap_within_explicit_budget_is_retained_without_failure(tmp_path: Path) -> None:
    args, summary = fixture_summary(
        tmp_path,
        [control("/root/Save", 10), control("/root/Cancel", 50)],
        {"maximumOverlappingInteractivePairs": 1},
    )
    result = augment_native_qa_summary(args, summary)
    journey = first_journey(result)
    analysis = journey["layoutAnalysis"]
    assert isinstance(analysis, dict)
    assert result["status"] == "passed"
    assert journey["status"] == "passed"
    assert analysis["issueCount"] == 1
    assert analysis["admission"]["status"] == "passed"


def test_minor_layout_finding_within_default_budget_does_not_fail(tmp_path: Path) -> None:
    args, summary = fixture_summary(tmp_path, [control("/root/Tiny", 10, width=16)])
    result = augment_native_qa_summary(args, summary)
    journey = first_journey(result)
    analysis = journey["layoutAnalysis"]
    assert isinstance(analysis, dict)
    assert result["status"] == "passed"
    assert journey["status"] == "passed"
    assert analysis["issueCount"] == 1
    assert analysis["majorOrCriticalIssueCount"] == 0


def test_checkpoint_layout_budget_is_enforced(tmp_path: Path) -> None:
    args, summary = fixture_summary(tmp_path, [control("/root/Hud/Pause", 10)])
    journey = first_journey(summary)
    harness = journey["harness"]
    assert isinstance(harness, dict)
    harness["checkpointUi"] = [
        {
            "id": "menu-open",
            "ui": {
                "viewport": {"width": 320, "height": 200},
                "visibleControlCount": 2,
                "interactiveControlCount": 2,
                "controls": [
                    control("/root/Menu/Save", 10),
                    control("/root/Menu/Cancel", 50),
                ],
            },
        }
    ]

    result = augment_native_qa_summary(args, summary)
    journey = first_journey(result)
    assert result["status"] == "failed"
    assert journey["status"] == "failed"
    assert any("menu-open" in value for value in journey["findings"])


def test_truncated_layout_can_be_made_admission_blocking(tmp_path: Path) -> None:
    args, summary = fixture_summary(
        tmp_path,
        [control("/root/Save", 10)],
        {"failOnTruncatedLayoutAnalysis": True},
    )
    journey = first_journey(summary)
    harness = journey["harness"]
    assert isinstance(harness, dict)
    ui = harness["ui"]
    assert isinstance(ui, dict)
    ui["pairAnalysisTruncated"] = True

    result = augment_native_qa_summary(args, summary)
    journey = first_journey(result)
    assert result["status"] == "failed"
    assert any("analysis bound" in value for value in journey["findings"])


def test_focus_and_visible_control_governance_are_enforced(tmp_path: Path) -> None:
    args, summary = fixture_summary(
        tmp_path,
        [control("/root/Save", 10)],
        {"minimumVisibleControls": 2, "requireFocusOwner": True},
    )
    result = augment_native_qa_summary(args, summary)
    journey = first_journey(result)
    assert result["status"] == "failed"
    assert any("visible control" in value for value in journey["findings"])
    assert any("focus owner" in value for value in journey["findings"])


def test_unsafe_journey_id_is_rejected(tmp_path: Path) -> None:
    args, summary = fixture_summary(tmp_path, [control("/root/Save", 10)])
    journey = first_journey(summary)
    journey["id"] = "../escape"
    with pytest.raises(NativeQaError, match="unsafe id"):
        augment_native_qa_summary(args, summary)
