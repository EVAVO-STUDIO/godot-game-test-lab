from __future__ import annotations

import json
from pathlib import Path

from godot_game_test_lab.native_qa_profile import normalize_profile

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schemas" / "native-agent-qa-profile.schema.json"
EXAMPLE = ROOT / "examples" / "native-agent-visual-layout.profile.json"

LAYOUT_KEYS = {
    "captureUiAtCheckpoints",
    "failOnTruncatedLayoutAnalysis",
    "maximumAncestorClippedInteractive",
    "maximumCloseInteractivePairs",
    "maximumOccludedInteractive",
    "maximumPairChecks",
    "minimumInteractiveGap",
}


def test_layout_profile_keys_match_runtime_normalization_and_schema() -> None:
    normalized = normalize_profile(
        {"schemaVersion": "2.0", "journeys": [{"id": "contract", "steps": []}]}
    )
    ux = normalized["journeys"][0]["ux"]
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    properties = schema["$defs"]["ux"]["properties"]

    assert LAYOUT_KEYS <= set(ux)
    assert LAYOUT_KEYS <= set(properties)
    for key in LAYOUT_KEYS:
        assert properties[key]["default"] == ux[key]


def test_visual_layout_profile_example_normalizes_without_loss() -> None:
    raw = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    normalized = normalize_profile(raw)
    ux = normalized["journeys"][0]["ux"]

    assert ux["captureUiAtCheckpoints"] is True
    assert ux["failOnTruncatedLayoutAnalysis"] is True
    assert ux["maximumOverlappingInteractivePairs"] == 0
    assert ux["maximumPairChecks"] == 50_000
    assert normalized["journeys"][0]["steps"][0] == {
        "type": "checkpoint",
        "id": "menu-settled",
    }
