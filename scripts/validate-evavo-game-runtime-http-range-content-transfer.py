#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

TEST_LAB = Path(__file__).resolve().parents[1]
CONFIG = (
    TEST_LAB
    / "config"
    / "evavo-game-runtime-http-range-content-transfer.v1.json"
)
CONTRACT = (
    TEST_LAB
    / "contracts"
    / "evavo-game-runtime-http-range-content-transfer-receipt-v1.json"
)
RUNNER = (
    TEST_LAB
    / "scripts"
    / "run-evavo-game-runtime-http-range-content-transfer.py"
)
POWERSHELL = (
    TEST_LAB
    / "scripts"
    / "run-evavo-game-runtime-http-range-content-transfer.ps1"
)
DOC = TEST_LAB / "docs" / "EVAVO_GAME_RUNTIME_HTTP_RANGE_CONTENT_TRANSFER.md"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
EXPECTED_RANGES = {
    "bytes=0-11",
    "bytes=12-23",
    "bytes=24-35",
    "bytes=36-47",
}
FALSE_CLAIMS = {
    "http_dispatch_is_transfer_completion",
    "range_response_is_cache_verification",
    "provider_completion_is_cache_verification",
    "cancel_request_is_terminal_cancellation",
    "runtime_ready_grants_content_availability",
    "runtime_ready_grants_scene_activation",
    "runtime_ready_grants_simulation_authority",
    "web_cors_configuration_is_verified",
    "process_local_handles_are_portable",
}


def load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict), f"{path} must contain an object"
    return value


def require(path: Path, *needles: str) -> None:
    value = path.read_text(encoding="utf-8")
    for needle in needles:
        assert needle in value, f"{path} missing {needle!r}"


def validate(runtime: Path) -> None:
    config = load(CONFIG)
    contract = load(CONTRACT)

    assert config["version"] == 1
    assert config["suite_id"] == (
        "evavo_game_runtime_http_range_content_transfer"
    )
    assert config["runtime_repository"] == "EVAVO-STUDIO/evavo-game-runtime"
    assert set(config["required_false_claims"]) == FALSE_CLAIMS
    assert set(config["expected_ranges"]) == EXPECTED_RANGES
    scenario_ids = {row["id"] for row in config["scenarios"]}
    assert scenario_ids == {
        "integration_validator",
        "exact_godot_4_6_2_import",
        "http_range_behavior",
        "range_server_evidence",
    }

    props = contract["properties"]
    assert props["version"]["const"] == 1
    assert props["suite_id"]["const"] == config["suite_id"]
    assert props["runtime_sha"]["$ref"] == "#/$defs/git_sha"
    assert props["test_lab_sha"]["$ref"] == "#/$defs/git_sha"
    assert contract["$defs"]["git_sha"]["pattern"] == "^[0-9a-f]{40}$"
    assert props["godot_version"]["pattern"] == "^4\\.6\\.2(?:\\.|$)"
    scenario_props = props["scenarios"]["properties"]
    assert set(scenario_props) == scenario_ids
    claim_contract = props["claims"]
    assert set(claim_contract["required"]) == FALSE_CLAIMS
    for claim in FALSE_CLAIMS:
        assert claim_contract["properties"][claim]["const"] is False
    range_enum = set(contract["$defs"]["ranges"]["items"]["enum"])
    assert range_enum == EXPECTED_RANGES
    assert props["range_server"]["properties"][
        "ranges_are_bounded"
    ]["const"] is True
    assert contract["additionalProperties"] is False

    for relative in config["required_runtime_paths"]:
        path = runtime / relative
        assert path.is_file(), f"runtime path missing: {relative}"

    world = runtime / "addons" / "evavo_game_runtime" / "world"
    source_policy = world / "content_http_range_source_policy.gd"
    bridge = world / "godot_http_range_native_provider_bridge.gd"
    wrapper = world / "http_range_content_package_transfer_runtime.gd"
    bridge_factory = world / "content_native_provider_bridge_factory.gd"
    runtime_runner = runtime / "scripts" / "run-content-http-range-transfer-smoke.py"
    runtime_validator = runtime / "tests" / "validate_content_http_range_transfer.py"
    runtime_smoke = runtime / "tests" / "godot" / "test_content_http_range_transfer.gd"
    fixture_server = runtime / "tests" / "http_range_fixture_server.py"
    runtime_doc = runtime / "docs" / "CONTENT_HTTP_RANGE_TRANSFER.md"
    plugin = runtime / "addons" / "evavo_game_runtime" / "plugin.cfg"

    require(
        source_policy,
        "class_name EVAVOContentHttpRangeSourcePolicy",
        "content_http_range_https_required",
        "content_http_range_origin_not_allowed",
        "content_http_range_reserved_header_rejected",
        "content_http_range_authorization_header_must_be_ephemeral",
        "content_http_range_content_range_mismatch",
        "content_http_range_response_ignored_range",
        '"declared_bytes_are_measured_network_bytes": false',
    )
    require(
        bridge,
        "class_name EVAVOGodotHttpRangeNativeProviderBridge",
        "HTTPClient.new()",
        "connect_to_host",
        "read_response_body_chunk",
        "content_http_range_chunk_digest_mismatch",
        "func reconcile_request(",
        '"replay_pending_chunks": true',
        '"measured_network_bytes": false',
    )
    require(
        wrapper,
        "class_name EVAVOHttpRangeContentPackageTransferRuntime",
        "func _prepare_resume(",
        'provider["pending_chunks"] = []',
        'provider["emitted_chunks"] = retained_emitted',
        "discarded_process_local_pending_count",
        "replayed_unverified_emitted_count",
        '"process_local_handles_are_portable": false',
    )
    require(
        bridge_factory,
        "func create_http_range(",
        "content_http_range_bridge_not_production_ready",
        '"built_in_http_range_available"',
    )
    require(
        fixture_server,
        "ThreadingHTTPServer",
        'mode == "retry"',
        'mode == "ignore-range"',
        'mode == "bad-content-range"',
        'mode == "corrupt"',
        "Content-Range",
        "ETag",
    )
    require(
        runtime_smoke,
        "EVAVO_CONTENT_HTTP_RANGE_TRANSFER_TEST=PASS",
        "server_ignoring_range_was_accepted",
        "mismatched_content_range_was_accepted",
        "corrupt_http_range_chunk_was_accepted",
        "http_range_resume_did_not_replay_process_local_state",
        "http_range_protected_resume_did_not_finish",
    )
    require(
        runtime_validator,
        "EVAVO HTTP range content transfer validation passed",
        "validate_contract",
        "validate_fixture",
        "validate_model",
        "validate_sources",
    )
    require(
        runtime_runner,
        "range_server_report",
        "EVAVO_HTTP_RANGE_BASE_URL",
        "EVAVO_CONTENT_HTTP_RANGE_TRANSFER_TEST=PASS",
        "validate_server_report",
    )
    require(
        runtime_doc,
        "HTTP range",
        "Content-Range",
        "process-local",
        "CORS",
        "simulation authority",
    )
    require(plugin, 'version="0.10.0"')

    require(
        RUNNER,
        "evavo_game_runtime_http_range_content_transfer",
        "run-content-http-range-transfer-smoke.py",
        "runtime_receipt_path",
        "range_server_evidence",
        "EVAVO Game Runtime HTTP range Test Lab suite passed",
        '"status", "--porcelain"',
    )
    require(
        POWERSHELL,
        "run-evavo-game-runtime-http-range-content-transfer.py",
        "RuntimeRepo",
        "GodotPath",
        "ArtifactRoot",
    )
    require(
        DOC,
        "exact Godot 4.6.2",
        "real local HTTP server",
        "HTTP 206",
        "content availability",
        "scene activation",
        "simulation authority",
        "does not prove production CORS",
    )

    assert SHA_RE.fullmatch("a" * 40)
    for value in EXPECTED_RANGES:
        first, last = value.removeprefix("bytes=").split("-", 1)
        assert int(last) >= int(first)

    paths = [
        CONFIG,
        CONTRACT,
        RUNNER,
        POWERSHELL,
        DOC,
        Path(__file__),
        source_policy,
        bridge,
        wrapper,
        bridge_factory,
        runtime_runner,
        runtime_validator,
        runtime_smoke,
        fixture_server,
        runtime_doc,
        plugin,
    ]
    for path in paths:
        value = path.read_text(encoding="utf-8")
        assert "\t" not in value, f"{path} contains tabs"
        assert not any(line.rstrip() != line for line in value.splitlines()), (
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
    validate(runtime)
    print(
        "EVAVO Game Runtime HTTP range content transfer "
        "integration validation passed"
    )


if __name__ == "__main__":
    main()
