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
) -> tuple[Namespace, dict[str, object]]:
    journey_root = tmp_path / "journeys" / "menu"
    journey_root.mkdir(parents=True)
    (journey_root / "journey.normalized.json").write_text(
        json.dumps({"ux": {"minimumInteractiveWidth": 24}}),
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


def test_severe_layout_findings_fail_required_journey(tmp_path: Path) -> None:
    args, summary = fixture_summary(
        tmp_path,
        [control("/root/Save", 10), control("/root/Cancel", 50)],
    )
    result = augment_native_qa_summary(args, summary)
    journey = result["journeys"][0]
    assert result["status"] == "failed"
    assert journey["status"] == "failed"
    assert journey["layoutAnalysis"]["majorOrCriticalIssueCount"] == 1
    assert "journeys/menu/ui-layout-analysis.json" in journey["evidence"]
    assert (tmp_path / "journeys" / "menu" / "ui-layout-analysis.json").is_file()
    assert (tmp_path / "native-agent-summary.json").is_file()


def test_minor_layout_finding_does_not_fail_journey(tmp_path: Path) -> None:
    args, summary = fixture_summary(tmp_path, [control("/root/Tiny", 10, width=16)])
    result = augment_native_qa_summary(args, summary)
    journey = result["journeys"][0]
    assert result["status"] == "passed"
    assert journey["status"] == "passed"
    assert journey["layoutAnalysis"]["issueCount"] == 1
    assert journey["layoutAnalysis"]["majorOrCriticalIssueCount"] == 0


def test_unsafe_journey_id_is_rejected(tmp_path: Path) -> None:
    args, summary = fixture_summary(tmp_path, [control("/root/Save", 10)])
    summary["journeys"][0]["id"] = "../escape"
    with pytest.raises(NativeQaError, match="unsafe id"):
        augment_native_qa_summary(args, summary)
