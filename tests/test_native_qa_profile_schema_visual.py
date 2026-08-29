from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schemas" / "native-agent-qa-profile.schema.json"


def test_native_visual_ux_schema_matches_runtime_controls() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    ux = schema["$defs"]["ux"]
    properties = ux["properties"]
    expected = {
        "captureUiAtCheckpoints": ("boolean", True),
        "failOnTruncatedLayoutAnalysis": ("boolean", False),
        "maximumAncestorClippedInteractive": ("integer", 0),
        "maximumCloseInteractivePairs": ("integer", 32),
        "maximumOccludedInteractive": ("integer", 0),
        "maximumPairChecks": ("integer", 50_000),
        "minimumInteractiveGap": ("number", 8),
    }
    for key, (expected_type, expected_default) in expected.items():
        assert properties[key]["type"] == expected_type
        assert properties[key]["default"] == expected_default
    assert properties["maximumPairChecks"]["maximum"] == 50_000
    assert ux["additionalProperties"] is False


def test_deliberate_fixture_profile_uses_only_schema_declared_ux_keys() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    declared = set(schema["$defs"]["ux"]["properties"])
    profile = json.loads(
        (
            ROOT
            / "fixtures"
            / "visual-qa-overlap"
            / "native-agent-qa.profile.json"
        ).read_text(encoding="utf-8")
    )
    supplied = set(profile["journeys"][0]["ux"])
    assert supplied <= declared
