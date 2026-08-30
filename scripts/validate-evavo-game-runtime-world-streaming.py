#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "config/evavo-game-runtime-world-streaming.v1.json"
CONTRACT = ROOT / "contracts/evavo-game-runtime-world-streaming-receipt-v1.json"
RUNNER = ROOT / "scripts/run-evavo-game-runtime-world-streaming.ps1"


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise AssertionError(f"{path.relative_to(ROOT)} must contain a JSON object")
    return value


def main() -> None:
    for path in (PROFILE, CONTRACT, RUNNER):
        assert path.is_file(), f"missing Test Lab world streaming file: {path.relative_to(ROOT)}"

    profile = load_json(PROFILE)
    contract = load_json(CONTRACT)
    runner = RUNNER.read_text(encoding="utf-8")

    assert profile.get("version") == 1
    assert profile.get("consumer") == "EVAVO-STUDIO/evavo-game-runtime"
    assert profile.get("runtime_script") == "tests/world_streaming_smoke.gd"
    assert profile.get("required_marker") == "EVAVO_WORLD_STREAMING_SMOKE="
    checks = profile.get("required_checks")
    assert isinstance(checks, list) and len(checks) >= 10
    for required in (
        "package_dependency_order",
        "bounded_delivery_concurrency",
        "package_verification",
        "region_dependency_order",
        "memory_admission",
        "activation_fences",
        "authority_handoff",
        "unload_hysteresis",
    ):
        assert required in checks, f"world streaming Test Lab profile is missing {required}"

    assert contract.get("type") == "object"
    assert contract.get("properties", {}).get("version", {}).get("const") == 1
    required_fields = set(contract.get("required", []))
    assert {
        "version",
        "runtime_sha",
        "godot",
        "exit_code",
        "evidence",
    }.issubset(required_fields)
    evidence_required = set(
        contract.get("properties", {})
        .get("evidence", {})
        .get("required", [])
    )
    assert {"version", "packages", "streaming", "handoffs"}.issubset(
        evidence_required
    )

    for marker in (
        "validate_world_streaming.py",
        "--headless",
        "--editor",
        "world_streaming_smoke.gd",
        "EVAVO_WORLD_STREAMING_SMOKE=",
        "memory_admitted_mb",
        "authority_handoff_not_committed",
        "receipt.json",
        "git -C $RuntimeRepo rev-parse HEAD",
        "git -C $RuntimeRepo status --porcelain=v1",
    ):
        assert marker in runner, f"Test Lab runner is missing {marker!r}"

    assert "AllowDirty" in runner
    assert "ConvertTo-Json -Depth 40" in runner
    print("EVAVO world streaming Test Lab contract validation passed")


if __name__ == "__main__":
    main()
