#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

TEST_LAB = Path(__file__).resolve().parents[1]
CONFIG = TEST_LAB / "config/evavo-game-runtime-http-range-hardening.v1.json"
CONTRACT = TEST_LAB / "contracts/evavo-game-runtime-http-range-hardening-receipt-v1.json"
RUNNER = TEST_LAB / "scripts/run-evavo-game-runtime-http-range-hardening.py"
POWERSHELL = TEST_LAB / "scripts/run-evavo-game-runtime-http-range-hardening.ps1"
DOC = TEST_LAB / "docs/EVAVO_GAME_RUNTIME_HTTP_RANGE_HARDENING.md"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict), f"{path} must contain an object"
    return value


def require(path: Path, *needles: str) -> str:
    value = path.read_text(encoding="utf-8")
    for needle in needles:
        assert needle in value, f"{path} missing {needle!r}"
    return value


def validate(runtime: Path) -> None:
    config = load(CONFIG)
    contract = load(CONTRACT)
    assert config["version"] == 1
    assert config["suite_id"] == "evavo_game_runtime_http_range_hardening"
    assert config["runtime_repository"] == "EVAVO-STUDIO/evavo-game-runtime"
    scenario_ids = {row["id"] for row in config["scenarios"]}
    assert scenario_ids == {
        "integration_validator",
        "exact_godot_4_6_2_import",
        "http_range_hardening_behavior",
    }
    claims = set(config["required_false_claims"])
    assert contract["properties"]["suite_id"]["const"] == config["suite_id"]
    assert set(contract["properties"]["claims"]["required"]) == claims
    for claim in claims:
        assert contract["properties"]["claims"]["properties"][claim]["const"] is False
    assert contract["properties"]["godot_version"]["pattern"] == "^4\\.6\\.2(?:\\.|$)"
    assert contract["additionalProperties"] is False

    for relative in config["required_runtime_paths"]:
        assert (runtime / relative).is_file(), f"runtime path missing: {relative}"

    policy = runtime / "addons/evavo_game_runtime/world/content_http_range_source_policy.gd"
    runtime_contract = runtime / "contracts/content-http-range-source-v1.json"
    runtime_validator = runtime / "tests/validate_content_http_range_hardening.py"
    runtime_smoke = runtime / "tests/godot/test_content_http_range_hardening.gd"
    runtime_runner = runtime / "scripts/run-content-http-range-hardening-smoke.ps1"
    runtime_doc = runtime / "docs/CONTENT_HTTP_RANGE_HARDENING.md"

    source = require(
        policy,
        "_valid_strong_etag",
        "http_range_strong_validator_not_configured",
        "content_http_range_duplicate_header_rejected",
        "content_http_range_allowed_host_duplicate",
        "strong_etag_configured",
        "Accept-Encoding: identity",
        '"https_without_strong_validator_is_production_ready": false',
    )
    production = source.split("var production_ready := (", 1)[1].split(")\n    if scheme", 1)[0]
    assert "strong_etag_configured" in production
    schema = load(runtime_contract)
    options = schema["properties"]["expected_etag"]["anyOf"]
    assert options[0]["const"] == ""
    assert options[1]["minLength"] == 3
    assert options[1]["maxLength"] == 256
    require(runtime_validator, "EVAVO HTTP range hardening validation passed")
    require(
        runtime_smoke,
        "EVAVO_CONTENT_HTTP_RANGE_HARDENING_TEST=PASS",
        "https_without_strong_validator_was_production_ready",
        "duplicate_headers_were_accepted",
        "invalid_host_was_accepted",
    )
    require(runtime_runner, "Expected Godot 4.6.2")
    require(runtime_doc, "strong quoted ETag", "If-Range", "simulation authority")
    require(
        RUNNER,
        "evavo_game_runtime_http_range_hardening",
        "EVAVO_CONTENT_HTTP_RANGE_HARDENING_TEST=PASS",
        '"status", "--porcelain"',
    )
    require(POWERSHELL, "RuntimeRepo", "GodotPath", "ArtifactRoot")
    require(DOC, "strong validator", "exact Godot 4.6.2", "simulation authority")
    assert SHA_RE.fullmatch("a" * 40)

    for path in (CONFIG, CONTRACT, RUNNER, POWERSHELL, DOC, Path(__file__), policy, runtime_contract, runtime_validator, runtime_smoke, runtime_runner, runtime_doc):
        value = path.read_text(encoding="utf-8")
        assert "\t" not in value, f"{path} contains tabs"
        assert not any(line.rstrip() != line for line in value.splitlines()), f"{path} contains trailing whitespace"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-repo", type=Path, required=True)
    args = parser.parse_args()
    runtime = args.runtime_repo.resolve()
    assert (runtime / "project.godot").is_file(), "runtime project.godot missing"
    validate(runtime)
    print("EVAVO Game Runtime HTTP range hardening integration validation passed")


if __name__ == "__main__":
    main()
