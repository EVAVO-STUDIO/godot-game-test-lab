#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

TEST_LAB = Path(__file__).resolve().parents[1]
CONFIG = TEST_LAB / "config" / "evavo-game-runtime-native-provider-transfer.v1.json"
CONTRACT = TEST_LAB / "contracts" / "evavo-game-runtime-native-provider-transfer-receipt-v1.json"
RUNNER = TEST_LAB / "scripts" / "run-evavo-game-runtime-native-provider-transfer.py"
POWERSHELL = TEST_LAB / "scripts" / "run-evavo-game-runtime-native-provider-transfer.ps1"
DOC = TEST_LAB / "docs" / "EVAVO_GAME_RUNTIME_NATIVE_PROVIDER_TRANSFER.md"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
FALSE_CLAIMS = {
    "native_dispatch_is_transfer_completion",
    "chunk_handle_is_chunk_bytes",
    "provider_completion_is_cache_verification",
    "cancel_request_is_terminal_cancellation",
    "transfer_provider_ready_grants_content_availability",
    "transfer_provider_ready_grants_scene_activation",
    "transfer_provider_ready_grants_simulation_authority",
    "portable_resume_contains_native_request_id",
    "portable_resume_contains_chunk_handles",
    "platform_mapping_proves_native_sdk_available",
}


def load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict), f"{path} must contain an object"
    return value


def require(path: Path, *needles: str) -> None:
    source = path.read_text(encoding="utf-8")
    for needle in needles:
        assert needle in source, f"{path} missing {needle!r}"


def validate(runtime: Path) -> None:
    config = load(CONFIG)
    contract = load(CONTRACT)
    assert config["version"] == 1
    assert config["suite_id"] == "evavo_game_runtime_native_provider_transfer"
    assert config["runtime_repository"] == "EVAVO-STUDIO/evavo-game-runtime"
    assert {row["id"] for row in config["scenarios"]} == {
        "dependency_free_validator",
        "headless_import_parse",
        "native_provider_transfer_behavior",
    }
    assert set(config["required_false_claims"]) == FALSE_CLAIMS

    props = contract["properties"]
    assert props["version"]["const"] == 1
    assert props["suite_id"]["const"] == config["suite_id"]
    assert props["runtime_sha"]["pattern"] == "^[0-9a-f]{40}$"
    assert props["test_lab_sha"]["pattern"] == "^[0-9a-f]{40}$"
    claims = props["claims"]
    assert set(claims["required"]) == FALSE_CLAIMS
    assert all(claims["properties"][claim]["const"] is False for claim in FALSE_CLAIMS)
    assert contract["additionalProperties"] is False

    for relative in config["required_runtime_paths"]:
        assert (runtime / relative).is_file(), f"runtime path missing: {relative}"

    world = runtime / "addons" / "evavo_game_runtime" / "world"
    state = world / "native_callback_content_provider_state.gd"
    provider = world / "native_callback_content_package_transfer_provider.gd"
    bridge = world / "delegated_content_native_provider_bridge.gd"
    journal = world / "content_native_provider_event_journal.gd"
    wrapper = world / "native_callback_content_package_transfer_runtime.gd"
    smoke = runtime / "tests" / "godot" / "test_content_native_provider_transfer.gd"
    validator = runtime / "tests" / "validate_content_native_provider_transfer.py"
    plugin = runtime / "addons" / "evavo_game_runtime" / "plugin.cfg"

    require(
        state,
        "func validate_protected_receipt(",
        "native_callback_protected_pending_index_duplicate",
        "native_callback_protected_pending_handle_duplicate",
        "native_callback_protected_pending_sequence_unproven",
        "native_callback_protected_terminal_event_unexpected",
        "func prepend_pending(",
    )
    require(
        provider,
        "DEFAULT_EVENT_BATCH_LIMIT := 1",
        "released_pending_count",
        "preserved_pending_count",
        "tail_restore_ok",
        "func _release_existing_request_best_effort()",
        "STATE_COMPLETED",
        "native_callback_chunk_event_digest_mismatch",
        "native_callback_chunk_manifest_digest_mismatch",
    )
    provider_source = provider.read_text(encoding="utf-8")
    cancel = provider_source.split("func cancel_request(", 1)[1].split(
        "func release_request(", 1
    )[0]
    assert cancel.index("_release_pending_handles()") < cancel.index('"cancel_request"')
    drain = provider_source.split("func drain_chunks(", 1)[1].split(
        "func cancel_request(", 1
    )[0]
    assert "prepend_pending" in drain and "range(index + 1, batch.size())" in drain

    require(
        bridge,
        "native_content_read_chunk",
        "native_content_release_chunk",
        "native_content_reconcile",
        "native_content_platform_bridge_missing_method",
    )
    require(
        journal,
        "native_provider_journal_sequence_conflict",
        "native_provider_journal_sequence_gap",
        "native_provider_journal_event_after_terminal",
        "native_provider_journal_receipt_hash_invalid",
        "native_provider_journal_receipt_hash_duplicate",
        "native_provider_journal_receipt_last_hash_missing",
    )
    require(
        wrapper,
        "requires_protected_state_store",
        "provider.stage_protected_resume",
        "transfer_runtime.portable_resume_receipt",
    )
    require(
        smoke,
        "EVAVO_CONTENT_NATIVE_PROVIDER_TRANSFER_TEST=PASS",
        "_test_provider_reuse",
        "_test_cancel_with_pending_handle",
        "_test_batch_failure_preserves_tail",
        "_test_protected_receipt_validation",
        "duplicate_pending_resume_row_was_accepted",
        "unproven_terminal_resume_event_was_accepted",
        "non_hex_resume_event_hash_was_accepted",
        "var _failed := false",
        "if _failed:",
    )
    require(
        validator,
        "EVAVO native provider transfer validation passed",
        "validate_contracts",
        "validate_sources",
        "validate_receipt_model",
    )
    require(plugin, 'version="0.9.0"')

    require(
        RUNNER,
        "dependency_free_validator",
        "headless_import_parse",
        "native_provider_transfer_behavior",
        "EVAVO_CONTENT_NATIVE_PROVIDER_TRANSFER_TEST=PASS",
        '"status", "--porcelain"',
    )
    require(
        POWERSHELL,
        "run-evavo-game-runtime-native-provider-transfer.py",
        "RuntimeRepo",
        "GodotPath",
    )
    require(
        DOC,
        "content availability",
        "scene activation",
        "simulation authority",
        "does not prove that a native SDK is installed",
    )

    paths = [
        CONFIG, CONTRACT, RUNNER, POWERSHELL, DOC, Path(__file__),
        state, provider, bridge, journal, wrapper, smoke, validator, plugin,
    ]
    for path in paths:
        source = path.read_text(encoding="utf-8")
        assert "\t" not in source, f"{path} contains tabs"
        assert not any(line.rstrip() != line for line in source.splitlines()), (
            f"{path} contains trailing whitespace"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-repo", type=Path, required=True)
    args = parser.parse_args()
    runtime = args.runtime_repo.resolve()
    assert (runtime / "project.godot").is_file(), "runtime repository project.godot missing"
    validate(runtime)
    print("EVAVO Game Runtime native provider transfer integration validation passed")


if __name__ == "__main__":
    main()
