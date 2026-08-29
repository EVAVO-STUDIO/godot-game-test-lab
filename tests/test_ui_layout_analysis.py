from __future__ import annotations

from godot_game_test_lab.ui_layout_analysis import analyze_ui_layout, analyze_ui_snapshots


def control(
    path: str,
    x: float,
    y: float,
    width: float,
    height: float,
    **extra: object,
) -> dict[str, object]:
    return {
        "path": path,
        "class": "Button",
        "interactive": True,
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "insideViewport": True,
        **extra,
    }


def test_overlap_includes_coverage_and_severity() -> None:
    result = analyze_ui_layout(
        {
            "viewport": {"width": 320, "height": 200},
            "controls": [
                control("/root/Save", 10, 10, 80, 40),
                control("/root/Cancel", 50, 20, 80, 40),
            ],
        }
    )
    issue = next(
        item for item in result["issues"] if item["code"] == "interactive-overlap"
    )
    assert issue["severity"] == "major"
    assert issue["metrics"]["overlapArea"] == 1_200


def test_touching_controls_are_distinct_from_diagonal_controls() -> None:
    result = analyze_ui_layout(
        {
            "viewport": {"width": 500, "height": 300},
            "controls": [
                control("/root/First", 10, 10, 80, 40),
                control("/root/Touching", 90, 10, 80, 40),
                control("/root/Diagonal", 250, 120, 80, 40),
            ],
        }
    )
    spacing = [item for item in result["issues"] if item["code"] == "interactive-spacing"]
    assert len(spacing) == 1
    assert spacing[0]["severity"] == "major"


def test_nested_interactive_controls_are_not_reported_as_overlap() -> None:
    result = analyze_ui_layout(
        {
            "viewport": {"width": 320, "height": 200},
            "controls": [
                control("/root/Panel", 10, 10, 120, 80),
                control(
                    "/root/Panel/Child",
                    20,
                    20,
                    80,
                    40,
                    ancestorPaths=["/root/Panel"],
                ),
            ],
        }
    )
    assert not any(item["code"] == "interactive-overlap" for item in result["issues"])


def test_clipping_occlusion_and_small_targets_are_reported() -> None:
    result = analyze_ui_layout(
        {
            "viewport": {"width": 320, "height": 200},
            "controls": [
                control("/root/Clipped", -5, 10, 40, 40, insideViewport=False),
                control(
                    "/root/Occluded",
                    50,
                    10,
                    40,
                    40,
                    centerBlockedBy="/root/Overlay",
                ),
                control("/root/Tiny", 100, 10, 16, 16),
                control(
                    "/root/AncestorClipped",
                    130,
                    10,
                    40,
                    40,
                    clippedByAncestor=True,
                ),
            ],
        }
    )
    codes = {item["code"] for item in result["issues"]}
    assert {
        "viewport-clipping",
        "center-occluded",
        "small-target",
        "ancestor-clipping",
    }.issubset(codes)


def test_multiple_checkpoint_snapshots_are_indexed() -> None:
    report = {
        "checkpointUi": [
            {
                "id": "menu",
                "ui": {
                    "viewport": {"width": 320, "height": 200},
                    "controls": [control("/root/Menu/Play", 10, 10, 80, 40)],
                },
            }
        ],
        "ui": {
            "viewport": {"width": 320, "height": 200},
            "controls": [control("/root/Hud/Pause", 10, 10, 80, 40)],
        },
    }
    result = analyze_ui_snapshots(report)
    assert result["snapshotCount"] == 2
    assert [item["id"] for item in result["snapshots"]] == ["menu", "final"]


def test_pair_analysis_is_bounded() -> None:
    controls = [
        control(f"/root/Item{index}", index * 30, 10, 24, 24) for index in range(20)
    ]
    result = analyze_ui_layout(
        {"viewport": {"width": 800, "height": 200}, "controls": controls},
        {"maximumPairChecks": 2},
    )
    assert result["summary"]["truncated"] is True
    assert result["summary"]["pairChecks"] == 2
