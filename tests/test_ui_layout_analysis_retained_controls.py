from __future__ import annotations

from godot_game_test_lab.ui_layout_analysis import analyze_ui_layout


def test_retained_interactive_controls_are_analyzed_without_full_control_tree() -> None:
    result = analyze_ui_layout(
        {
            "viewport": {"width": 320, "height": 200},
            "interactiveControls": [
                {
                    "path": "/root/Save",
                    "class": "Button",
                    "interactive": True,
                    "disabled": False,
                    "x": 10,
                    "y": 10,
                    "width": 80,
                    "height": 40,
                    "insideViewport": True,
                },
                {
                    "path": "/root/Cancel",
                    "class": "Button",
                    "interactive": True,
                    "disabled": False,
                    "x": 50,
                    "y": 20,
                    "width": 80,
                    "height": 40,
                    "insideViewport": True,
                },
            ],
        }
    )
    assert result["controlCount"] == 2
    assert result["interactiveControlCount"] == 2
    assert any(issue["code"] == "interactive-overlap" for issue in result["issues"])
