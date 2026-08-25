from __future__ import annotations

import json
from pathlib import Path

import pytest

from godot_game_test_lab.android_semantic_driver_cli import SCHEMA, _assert_project_state, _load_journey


def _write(path: Path, value: dict[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_loads_bounded_semantic_journey(tmp_path: Path) -> None:
    journey = _write(
        tmp_path / "journey.json",
        {
            "schema": SCHEMA,
            "steps": [
                {"type": "state"},
                {"type": "press", "action": "move_right"},
                {"type": "wait", "milliseconds": 250},
                {"type": "pulse", "action": "jump", "durationMs": 80},
                {"type": "assert-state", "expected": {"checkpoint": "ledge_2", "alive": True}},
                {"type": "release", "action": "move_right"},
            ],
        },
    )
    steps = _load_journey(journey)
    assert len(steps) == 6
    assert steps[1]["action"] == "move_right"
    assert steps[4]["expected"] == {"checkpoint": "ledge_2", "alive": True}


def test_project_state_assertion_matches_only_declared_expected_keys() -> None:
    result = _assert_project_state(
        {"projectState": {"checkpoint": "ledge_2", "alive": True, "coins": 7}},
        {"checkpoint": "ledge_2", "alive": True},
        3,
    )
    assert result["matched"] is True
    assert result["observed"] == {"checkpoint": "ledge_2", "alive": True}


def test_project_state_assertion_rejects_missing_or_wrong_value() -> None:
    with pytest.raises(AssertionError, match="checkpoint:not_equal"):
        _assert_project_state({"projectState": {"checkpoint": "ledge_1"}}, {"checkpoint": "ledge_2"}, 4)
    with pytest.raises(AssertionError, match="inventory_open:missing"):
        _assert_project_state({"projectState": {}}, {"inventory_open": True}, 5)


def test_rejects_unknown_schema_step_type_and_unbounded_assertion(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="journey schema"):
        _load_journey(_write(tmp_path / "schema.json", {"schema": "wrong", "steps": [{"type": "state"}]}))
    with pytest.raises(ValueError, match="unsupported type"):
        _load_journey(_write(tmp_path / "type.json", {"schema": SCHEMA, "steps": [{"type": "shell"}]}))
    with pytest.raises(ValueError, match="bounded scalar"):
        _load_journey(_write(tmp_path / "nested.json", {"schema": SCHEMA, "steps": [{"type": "assert-state", "expected": {"bad": {"nested": True}}}]}))


def test_rejects_excessive_waits_and_step_counts(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="10000ms"):
        _load_journey(
            _write(
                tmp_path / "long-wait.json",
                {"schema": SCHEMA, "steps": [{"type": "wait", "milliseconds": 10001}]},
            )
        )
    with pytest.raises(ValueError, match="120 seconds"):
        _load_journey(
            _write(
                tmp_path / "total-wait.json",
                {
                    "schema": SCHEMA,
                    "steps": [{"type": "wait", "milliseconds": 10000} for _ in range(13)],
                },
            )
        )
    with pytest.raises(ValueError, match="1..256"):
        _load_journey(
            _write(
                tmp_path / "too-many.json",
                {"schema": SCHEMA, "steps": [{"type": "state"} for _ in range(257)]},
            )
        )
