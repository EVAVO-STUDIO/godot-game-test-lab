from __future__ import annotations

import json
from pathlib import Path

import pytest

from godot_game_test_lab.native_qa import NativeQaError, normalize_profile

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schemas" / "native-agent-qa-profile.schema.json"


def profile_with_ux(ux: dict[str, object]) -> dict[str, object]:
    return {
        "schemaVersion": "2.0",
        "journeys": [
            {
                "id": "visual-layout",
                "scene": "res://main.tscn",
                "steps": [{"type": "wait", "frames": 2}],
                "ux": ux,
            }
        ],
    }


def test_visual_layout_defaults_are_explicit() -> None:
    normalized = normalize_profile(profile_with_ux({}))
    ux = normalized["journeys"][0]["ux"]
    assert ux["captureControlTree"] is True
    assert ux["captureUiAtCheckpoints"] is True
    assert ux["failOnTruncatedLayoutAnalysis"] is False
    assert ux["maximumAncestorClippedInteractive"] == 0
    assert ux["maximumOccludedInteractive"] == 0
    assert ux["maximumCloseInteractivePairs"] == 32
    assert ux["maximumPairChecks"] == 50_000
    assert ux["minimumInteractiveGap"] == 8.0


def test_visual_layout_thresholds_are_configurable_and_bounded() -> None:
    requested = {
        "captureUiAtCheckpoints": False,
        "failOnTruncatedLayoutAnalysis": True,
        "maximumAncestorClippedInteractive": 2,
        "maximumOccludedInteractive": 3,
        "maximumCloseInteractivePairs": 4,
        "maximumPairChecks": 1234,
        "minimumInteractiveGap": 12.5,
    }
    normalized = normalize_profile(profile_with_ux(requested))
    ux = normalized["journeys"][0]["ux"]
    for key, value in requested.items():
        assert ux[key] == value

    with pytest.raises(NativeQaError, match="maximumPairChecks"):
        normalize_profile(profile_with_ux({"maximumPairChecks": 50_001}))
    with pytest.raises(NativeQaError, match="minimumInteractiveGap"):
        normalize_profile(profile_with_ux({"minimumInteractiveGap": -1}))
    with pytest.raises(NativeQaError, match="captureUiAtCheckpoints"):
        normalize_profile(profile_with_ux({"captureUiAtCheckpoints": "yes"}))


def test_json_schema_and_normalizer_expose_the_same_visual_layout_options() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    properties = schema["$defs"]["ux"]["properties"]
    expected = {
        "captureUiAtCheckpoints",
        "failOnTruncatedLayoutAnalysis",
        "maximumAncestorClippedInteractive",
        "maximumOccludedInteractive",
        "maximumCloseInteractivePairs",
        "maximumPairChecks",
        "minimumInteractiveGap",
    }
    assert expected.issubset(properties)
    normalized = normalize_profile(profile_with_ux({}))["journeys"][0]["ux"]
    assert expected.issubset(normalized)
