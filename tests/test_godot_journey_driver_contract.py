from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "scripts" / "godot_input_journey.gd"


def test_variant_stack_pop_has_an_explicit_node_type() -> None:
    source = DRIVER.read_text(encoding="utf-8")
    assert "var node: Node = stack.pop_back()" in source
    assert "var node := stack.pop_back()" not in source


def test_checkpoint_ui_and_stacking_evidence_are_retained() -> None:
    source = DRIVER.read_text(encoding="utf-8")
    for token in (
        '"checkpointUi"',
        '"captureUiAtCheckpoints"',
        '"ancestorPaths"',
        '"clippedByAncestor"',
        '"paintOrder"',
        '"canvasLayer"',
        '"effectiveZIndex"',
        '"centerBlockedBy"',
        '"pairAnalysisTruncated"',
    ):
        assert token in source


def test_editable_control_text_is_never_serialized() -> None:
    source = DRIVER.read_text(encoding="utf-8")
    assert '"inputTextRedacted": control is LineEdit or control is TextEdit' in source
    assert "(control as LineEdit).text" not in source
    assert "(control as TextEdit).text" not in source
