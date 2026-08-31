#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

TEST_LAB = Path(__file__).resolve().parents[1]
CONFIG = TEST_LAB / "config" / "evavo-game-runtime-content-cache-crash-recovery.v1.json"
CONTRACT = TEST_LAB / "contracts" / "evavo-game-runtime-content-cache-crash-recovery-receipt-v1.json"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict), f"{path} must contain an object"
    return value


def require(path: Path, *values: str) -> None:
    content = path.read_text(encoding="utf-8")
    for value in values:
        assert value in content, f"{path} missing {value!r}"


def validate(runtime: Path) -> None:
    config = load(CONFIG)
    contract = load(CONTRACT)
    assert config["version"] == 1
    assert config["suite_id"] == "evavo_game_runtime_content_cache_crash_recovery"
    assert len(config["scenarios"]) == 3
    assert {row["id"] for row in config["scenarios"]} == {
        "dependency_free_validator",
        "headless_import_parse",
        "fault_plan_behavior",
    }
    required_false = set(config["required_false_claims"])
    assert required_false == {
        "simulated_interrupt_is_process_crash",
        "restart_receipt_grants_content_availability",
        "reconciliation_grants_scene_activation",
        "reconciliation_grants_simulation_authority",
    }

    props = contract["properties"]
    assert props["version"]["const"] == 1
    assert props["suite_id"]["const"] == config["suite_id"]
    assert props["runtime_sha"]["pattern"] == "^[0-9a-f]{40}$"
    assert props["test_lab_sha"]["pattern"] == "^[0-9a-f]{40}$"
    for claim in required_false:
        assert props["claims"]["properties"][claim]["const"] is False
    assert contract["additionalProperties"] is False

    for relative in config["required_runtime_paths"]:
        path = runtime / relative
        assert path.is_file(), f"runtime path missing: {relative}"

    fault_plan = runtime / "addons" / "evavo_game_runtime" / "world" / "content_cache_fault_plan.gd"
    harness = runtime / "addons" / "evavo_game_runtime" / "world" / "content_cache_crash_recovery_harness.gd"
    smoke = runtime / "tests" / "godot" / "test_content_cache_crash_recovery.gd"
    validator = runtime / "tests" / "validate_content_cache_crash_recovery.py"

    require(
        fault_plan,
        "fault_plan_generation_mismatch",
        '"fault_observation_is_process_crash": false',
        '"fault_receipt_grants_recovery_success": false',
    )
    require(
        harness,
        "func restart()",
        'has_method("reconcile")',
        '"simulated_interrupt_is_process_crash": false',
        '"reconciliation_grants_simulation_authority": false',
    )
    require(
        smoke,
        "EVAVO_CONTENT_CACHE_CRASH_RECOVERY_TEST=PASS",
        "restart_did_not_reconcile",
        "stale_generation_was_accepted",
    )
    require(
        validator,
        "EVAVO content cache crash recovery validation passed",
        "validate_contract",
        "validate_sources",
    )

    for path in (CONFIG, CONTRACT, Path(__file__), fault_plan, harness, smoke, validator):
        content = path.read_text(encoding="utf-8")
        assert "\t" not in content, f"{path} contains tabs"
        assert not any(line.rstrip() != line for line in content.splitlines()), (
            f"{path} contains trailing whitespace"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-repo", type=Path, required=True)
    args = parser.parse_args()
    runtime = args.runtime_repo.resolve()
    assert (runtime / "project.godot").is_file(), "runtime repository project.godot missing"
    validate(runtime)
    print("EVAVO Game Runtime content cache crash recovery integration validation passed")


if __name__ == "__main__":
    main()
