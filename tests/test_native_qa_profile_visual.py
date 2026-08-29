from __future__ import annotations

import pytest

from godot_game_test_lab.native_qa_common import NativeQaError
from godot_game_test_lab.native_qa_profile_visual import normalize_profile


def profile(ux: dict[str, object] | None = None) -> dict[str, object]:
    journey: dict[str, object] = {
        "id": "main-menu",
        "scene": "res://main.tscn",
        "steps": [{"type": "wait", "frames": 2}],
    }
    if ux is not None:
        journey["ux"] = ux
    return {"schemaVersion": "2.0", "journeys": [journey]}


def test_visual_ux_defaults_are_present_in_normalized_journeys() -> None:
    normalized = normalize_profile(profile())
    ux = normalized["journeys"][0]["ux"]
    assert ux["captureUiAtCheckpoints"] is True
    assert ux["minimumInteractiveGap"] == 8.0
    assert ux["maximumCloseInteractivePairs"] == 32
    assert ux["maximumAncestorClippedInteractive"] == 0
    assert ux["maximumOccludedInteractive"] == 0
    assert ux["maximumPairChecks"] == 50_000
    assert ux["maximumIssues"] == 1_024
    assert ux["failOnTruncatedLayoutAnalysis"] is False


def test_visual_ux_controls_are_bounded_and_preserved() -> None:
    normalized = normalize_profile(
        profile(
            {
                "captureControlTree": True,
                "captureUiAtCheckpoints": False,
                "minimumInteractiveGap": 12,
                "maximumCloseInteractivePairs": 4,
                "maximumAncestorClippedInteractive": 2,
                "maximumOccludedInteractive": 1,
                "maximumPairChecks": 10_000,
                "maximumIssues": 200,
                "failOnTruncatedLayoutAnalysis": True,
            }
        )
    )
    ux = normalized["journeys"][0]["ux"]
    assert ux["captureControlTree"] is True
    assert ux["captureUiAtCheckpoints"] is False
    assert ux["minimumInteractiveGap"] == 12.0
    assert ux["maximumCloseInteractivePairs"] == 4
    assert ux["maximumAncestorClippedInteractive"] == 2
    assert ux["maximumOccludedInteractive"] == 1
    assert ux["maximumPairChecks"] == 10_000
    assert ux["maximumIssues"] == 200
    assert ux["failOnTruncatedLayoutAnalysis"] is True


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("captureUiAtCheckpoints", "yes"),
        ("minimumInteractiveGap", -1),
        ("maximumCloseInteractivePairs", 1.5),
        ("maximumAncestorClippedInteractive", -1),
        ("maximumOccludedInteractive", 513),
        ("maximumPairChecks", 50_001),
        ("maximumIssues", 0),
        ("failOnTruncatedLayoutAnalysis", 1),
    ],
)
def test_visual_ux_controls_reject_invalid_values(key: str, value: object) -> None:
    with pytest.raises(NativeQaError):
        normalize_profile(profile({key: value}))


def test_unknown_ux_keys_are_still_rejected_by_the_legacy_authority() -> None:
    with pytest.raises(NativeQaError, match="unsupported fields"):
        normalize_profile(profile({"inventedVisualPolicy": True}))
