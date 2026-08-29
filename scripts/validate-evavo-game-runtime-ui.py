#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise AssertionError(f"{path.relative_to(ROOT)} must be a JSON object")
    return value


def main() -> None:
    matrix = load_json(ROOT / "config/evavo-game-runtime-ui-matrix.v1.json")
    receipt = load_json(ROOT / "contracts/evavo-game-runtime-ui-receipt-v1.json")
    runner = (ROOT / "scripts/run-evavo-game-runtime-ui.ps1").read_text(encoding="utf-8")

    assert matrix.get("version") == 1
    assert matrix.get("consumer") == "EVAVO-STUDIO/evavo-game-runtime"
    scenarios = matrix.get("scenarios", [])
    assert len(scenarios) >= 5
    expected = {"retro_16_9", "desktop_16_9", "desktop_ultrawide", "mobile_landscape", "mobile_portrait"}
    assert expected.issubset({str(item.get("id", "")) for item in scenarios})
    for scenario in scenarios:
        assert int(scenario.get("width", 0)) > 0
        assert int(scenario.get("height", 0)) > 0
        assert float(scenario.get("minimum_target_px", 0)) > 0

    assert receipt.get("properties", {}).get("version", {}).get("const") == 1
    for marker in ("EVAVO_QA_SCENARIO", "EVAVO_QA_LAYOUT", "EVAVO_QA_MIN_TARGET", "EVAVO_UI_EVIDENCE"):
        assert marker in runner, f"runner missing handshake marker {marker}"

    print("EVAVO game runtime UI Test Lab handshake validation passed")


if __name__ == "__main__":
    main()
