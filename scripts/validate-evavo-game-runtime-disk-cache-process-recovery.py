#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

TEST_LAB = Path(__file__).resolve().parents[1]
CONFIG = TEST_LAB / "config" / "evavo-game-runtime-disk-cache-process-recovery.v1.json"
CONTRACT = TEST_LAB / "contracts" / "evavo-game-runtime-disk-cache-process-recovery-receipt-v1.json"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")

FALSE_CLAIMS = {
    "checkpoint_marker_is_process_termination",
    "process_restart_grants_content_availability",
    "process_restart_grants_scene_activation",
    "process_restart_grants_simulation_authority",
    "headless_process_test_is_exported_device_test",
}


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
    assert config["suite_id"] == "evavo_game_runtime_disk_cache_process_recovery"
    assert config["runtime_repository"] == "EVAVO-STUDIO/evavo-game-runtime"
    assert {row["id"] for row in config["scenarios"]} == {
        "dependency_free_validators",
        "headless_import_parse",
        "disk_host_behavior",
        "actual_process_kill_matrix",
    }
    assert set(config["required_false_claims"]) == FALSE_CLAIMS

    properties = contract["properties"]
    assert properties["version"]["const"] == 1
    assert properties["suite_id"]["const"] == config["suite_id"]
    assert properties["runtime_sha"]["pattern"] == "^[0-9a-f]{40}$"
    assert properties["test_lab_sha"]["pattern"] == "^[0-9a-f]{40}$"
    claims = properties["claims"]["properties"]
    assert set(claims) == FALSE_CLAIMS
    assert all(claims[name]["const"] is False for name in FALSE_CLAIMS)
    assert contract["additionalProperties"] is False

    for relative in config["required_runtime_paths"]:
        path = runtime / relative
        assert path.is_file(), f"runtime path missing: {relative}"

    host = runtime / "addons" / "evavo_game_runtime" / "world" / "disk_content_package_cache_host.gd"
    worker = runtime / "tests" / "godot" / "disk_cache_process_recovery_worker.gd"
    matrix = runtime / "tests" / "run_disk_cache_process_recovery.py"
    smoke = runtime / "tests" / "godot" / "test_disk_content_package_cache_host.gd"
    plugin = runtime / "addons" / "evavo_game_runtime" / "plugin.cfg"

    require(
        host,
        "class_name EVAVODiskContentPackageCacheHost",
        "after_chunk_promote",
        "after_staged_payload_flush",
        "after_rotate_known_good",
        "after_promote_before_cleanup",
        "func reconcile()",
        '"restart_reconciliation_grants_simulation_authority": false',
    )
    require(
        worker,
        "EVAVO_DISK_CACHE_PROCESS_SEED=PASS",
        "EVAVO_DISK_CACHE_PROCESS_RECONCILE=PASS",
        "selected_digest_sha256",
    )
    require(
        matrix,
        "process.kill()",
        "checkpoint PID mismatch",
        "EVAVO_DISK_CACHE_PROCESS_MATRIX=PASS",
        '"headless_process_test_is_exported_device_test": False',
    )
    require(
        smoke,
        "EVAVO_DISK_CONTENT_PACKAGE_CACHE_TEST=PASS",
        "previous_known_good_not_restored",
        "candidate_was_not_resumed",
    )
    require(plugin, 'version="0.8.0"', 'script="plugin.gd"')

    for path in (CONFIG, CONTRACT, Path(__file__), host, worker, matrix, smoke, plugin):
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
    print("EVAVO Game Runtime disk cache process recovery integration validation passed")


if __name__ == "__main__":
    main()
