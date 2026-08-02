from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "scripts" / "godot_input_journey.gd"


def test_variant_stack_pop_has_an_explicit_node_type() -> None:
    source = DRIVER.read_text(encoding="utf-8")
    assert "var node: Node = stack.pop_back()" in source
    assert "var node := stack.pop_back()" not in source
