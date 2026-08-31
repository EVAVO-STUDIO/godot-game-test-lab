#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

TEST_LAB = Path(__file__).resolve().parents[1]
CONFIG = (
    TEST_LAB
    / "config"
    / "evavo-game-runtime-content-cache-process-recovery.v1.json"
)
CONTRACT = (
    TEST_LAB
    / "contracts"
    / "evavo-game-runtime-content-cache-process-recovery-receipt-v1.json"
)
RUNNER = (
    TEST_LAB
    / "scripts"
    / "run-evavo-game-runtime-content-cache-process-recovery.ps1"
)
DOC = (
    TEST_LAB
    / "docs"
    / "EVAVO_GAME_RUNTIME_CONTENT_CACHE_PROCESS_RECOVERY.md"
)


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
    assert (
        config["suite_id"]
        == "evavo_game_runtime_content_cache_process_recovery"
    )
    assert {row["id"] for row in config["scenarios"]} == {
        "dependency_free_validator",
        "headless_import_parse",
        "disk_host_behavior",
        "actual_process_kill_matrix",
    }
    assert set(config["required_checkpoints"]) == {
        "after_chunk_promote",
        "after_staged_payload_flush",
        "after_ready_promote_before_index",
        "after_index_write_before_candidate_cleanup",
    }
    required_false = set(config["required_false_claims"])
    assert required_false == {
        "process_kill_is_simulated",
        "headless_editor_process_is_exported_build",
        "reconciliation_grants_content_availability",
        "reconciliation_grants_scene_activation",
        "reconciliation_grants_simulation_authority",
        "cache_reconciliation_selects_active_release",
        "cache_reconciliation_performs_release_rollback",
    }

    properties = contract["properties"]
    assert properties["version"]["const"] == 1
    assert properties["suite_id"]["const"] == config["suite_id"]
    assert properties["runtime_sha"]["pattern"] == "^[0-9a-f]{40}$"
    assert properties["test_lab_sha"]["pattern"] == "^[0-9a-f]{40}$"
    for claim in required_false:
        assert properties["claims"]["properties"][claim]["const"] is False
    assert contract["additionalProperties"] is False

    for relative in config["required_runtime_paths"]:
        path = runtime / relative
        assert path.is_file(), f"runtime path missing: {relative}"

    world = runtime / "addons" / "evavo_game_runtime" / "world"
    store = world / "disk_content_cache_store.gd"
    reconciler = world / "disk_content_cache_reconciler.gd"
    host = world / "disk_content_package_cache_host.gd"
    factory = world / "content_package_cache_host_factory.gd"
    worker = runtime / "tests" / "godot" / "content_cache_process_worker.gd"
    runtime_runner = (
        runtime
        / "scripts"
        / "run-content-cache-process-recovery-smoke.ps1"
    )
    runtime_validator = (
        runtime
        / "tests"
        / "validate_content_cache_process_recovery.py"
    )
    plugin = runtime / "addons" / "evavo_game_runtime" / "plugin.cfg"

    require(
        store,
        "class_name EVAVODiskContentCacheStore",
        "FileAccess.get_sha256",
        "DirAccess.rename_absolute",
        "func expected_cache_key(",
        "disk_cache_generation_path_identity_mismatch",
        '"cache_index_is_authoritative_truth": false',
    )
    require(
        reconciler,
        "class_name EVAVODiskContentCacheReconciler",
        "promoted_verified_staged_entry",
        "discarded_stale_candidate",
        "disk_cache_candidate_manifest_cache_key_mismatch",
        '"cache_reconciliation_selects_active_release": false',
    )
    require(
        host,
        "class_name EVAVODiskContentPackageCacheHost",
        "CHECKPOINT_AFTER_CHUNK_PROMOTE",
        "CHECKPOINT_AFTER_STAGED_PAYLOAD_FLUSH",
        "CHECKPOINT_AFTER_READY_PROMOTE_BEFORE_INDEX",
        "CHECKPOINT_AFTER_INDEX_WRITE_BEFORE_CANDIDATE_CLEANUP",
        "func ready_entry(",
        "func candidate_receipt(",
        '"content_addressed_entries": true',
        '"cache_reconciliation_performs_release_rollback": false',
    )
    host_text = host.read_text(encoding="utf-8")
    assert "CHECKPOINT_AFTER_ROTATE_KNOWN_GOOD" not in host_text
    require(
        factory,
        '"disk", "persistent", "default"',
        '"memory", "in_memory", "fixture"',
    )
    require(
        worker,
        "OS.get_process_id()",
        "OS.delay_msec(50)",
        "func _cache_key(",
        "old_entry_not_retained",
        "new_ready_expectation_mismatch",
        "candidate_expectation_mismatch",
        "EVAVO_CONTENT_CACHE_PROCESS_CHECKPOINT=",
        "EVAVO_CONTENT_CACHE_PROCESS_RECOVERED=",
    )
    require(
        runtime_runner,
        "System.Diagnostics.ProcessStartInfo",
        "$Process.Kill()",
        "$Marker.pid -ne $Process.Id",
        "after_ready_promote_before_index",
        "after_index_write_before_candidate_cleanup",
        "old_entry_ready = $OldReady",
        "cache_reconciliation_performs_release_rollback = $false",
    )
    require(
        runtime_validator,
        "EVAVO content cache process recovery validation passed",
        "validate_recovery_model",
        "content-addressed" if False else "cache_key",
        "cache_reconciliation_performs_release_rollback",
    )
    plugin_text = plugin.read_text(encoding="utf-8")
    assert 'version="0.8.0"' in plugin_text
    assert 'script="plugin.gd"' in plugin_text

    require(
        RUNNER,
        "runtime_clean",
        "test_lab_clean",
        "actual_process_kill_matrix",
        "runtime_receipt_path",
        "process_kill_is_simulated = $false",
        "cache_reconciliation_performs_release_rollback = $false",
    )
    require(
        DOC,
        "real child process",
        "content-addressed",
        "not an exported game build",
        "does not select the active release",
        "does not perform release rollback",
        "does not grant content availability",
        "does not grant scene activation",
        "does not grant simulation authority",
    )

    for path in (
        CONFIG,
        CONTRACT,
        Path(__file__),
        RUNNER,
        DOC,
        store,
        reconciler,
        host,
        factory,
        worker,
        runtime_runner,
        runtime_validator,
        plugin,
    ):
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
    assert (runtime / "project.godot").is_file(), (
        "runtime repository project.godot missing"
    )
    for path in (CONFIG, CONTRACT, RUNNER, DOC):
        assert path.is_file(), f"Test Lab path missing: {path}"
    validate(runtime)
    print(
        "EVAVO Game Runtime content cache process recovery "
        "integration validation passed"
    )


if __name__ == "__main__":
    main()
