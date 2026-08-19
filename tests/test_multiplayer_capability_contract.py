from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_multiplayer_capability_is_discoverable_and_bounded() -> None:
    manifest = json.loads((ROOT / "evavo.capabilities.json").read_text(encoding="utf-8"))
    capability = next(item for item in manifest["capabilities"] if item["id"] == "testlab.qa.multiplayer")
    assert capability["effects"] == ["read", "compute", "write", "execute"]
    assert "godot-lab-multiplayer-qa" in capability["entrypoints"]
    assert "src/godot_game_test_lab/multiplayer_qa.py" in capability["entrypoints"]
    assert "scripts/Invoke-GodotLabMultiplayerAgentQA.ps1" in capability["entrypoints"]
    description = capability["description"].lower()
    assert "two to eight" in description
    assert "exact lab/target/profile identity" in description
    assert "physical controllers" in description
    assert "human game feel" in description


def test_multiplayer_wrapper_is_fixed_exact_sha_and_budget_bounded() -> None:
    text = (ROOT / "scripts" / "Invoke-GodotLabMultiplayerAgentQA.ps1").read_text(encoding="utf-8")
    for marker in (
        '"-m", "godot_game_test_lab.multiplayer_qa"',
        '"--expected-lab-sha", $ExpectedLabSha',
        '"--expected-target-sha", $ExpectedTargetSha',
        '"--allowed-artifact-root", $AllowedArtifactRoot',
        '"--max-total-seconds", $MaxTotalSeconds.ToString()',
        '"--max-artifact-bytes", $maxArtifactBytes.ToString()',
        '[ValidateRange(1, 8)]',
        '$WindowColumns = 2',
        '[switch]$AllowNonInteractive',
        'Session 0 service',
    ):
        assert marker in text
    for forbidden in (
        "Invoke-Expression",
        "cmd /c",
        "powershell -Command",
        "git reset --hard",
        "git clean",
    ):
        assert forbidden not in text
