from __future__ import annotations

from argparse import Namespace
from pathlib import Path

from godot_game_test_lab import visual_qa_self_test as base
from godot_game_test_lab.visual_qa_self_test_runner import (
    _normalized_fixture_journey,
    run_visual_qa_self_test,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PROFILE = (
    ROOT / "fixtures" / "visual-qa-overlap" / "native-agent-qa.profile.json"
)


def test_fixture_is_normalized_to_one_driver_journey() -> None:
    journey = _normalized_fixture_journey(FIXTURE_PROFILE)
    assert journey["id"] == "visual-qa-overlap"
    assert "journeys" not in journey
    assert journey["ux"]["captureUiAtCheckpoints"] is True
    assert journey["ux"]["minimumInteractiveGap"] == 8.0
    assert journey["ux"]["failOnTruncatedLayoutAnalysis"] is True


def test_missing_godot_is_reported_as_source_present(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(base, "_resolve_godot", lambda _value: None)
    artifacts = tmp_path / "artifacts"
    receipt = run_visual_qa_self_test(
        Namespace(
            lab_root=ROOT,
            artifacts=artifacts,
            godot=None,
            timeout=30,
            headless=True,
        )
    )
    assert receipt["status"] == "source-present"
    assert receipt["ready"] is False
    assert len(receipt["sourceSha256"]) == 64
    assert (artifacts / "latest-receipt.json").is_file()


def test_driver_receives_normalized_journey_contract() -> None:
    source = (
        ROOT
        / "src"
        / "godot_game_test_lab"
        / "visual_qa_self_test_runner.py"
    ).read_text(encoding="utf-8")
    assert '"EVAVO_JOURNEY_PATH": str(journey_path)' in source
    assert "_normalized_fixture_journey(profile_path)" in source
    assert 'report.get("journeyId") != "visual-qa-overlap"' in source
