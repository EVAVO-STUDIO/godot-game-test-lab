#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "evavo-game-runtime-region-content-delivery.v1.json"
CONTRACT_PATH = (
    ROOT
    / "contracts"
    / "evavo-game-runtime-region-content-delivery-receipt-v1.json"
)
RUNNER_PATH = ROOT / "scripts" / "run-evavo-game-runtime-region-content-delivery.ps1"
DOC_PATH = ROOT / "docs" / "EVAVO_GAME_RUNTIME_REGION_CONTENT_DELIVERY.md"


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"{path.relative_to(ROOT)} must contain a JSON object")
    return value


def require_symbols(path: Path, symbols: tuple[str, ...]) -> None:
    source = path.read_text(encoding="utf-8")
    for symbol in symbols:
        if symbol not in source:
            raise AssertionError(f"{path.relative_to(ROOT)} missing {symbol}")


def validate_config() -> None:
    config = load_json(CONFIG_PATH)
    assert config.get("version") == 1
    assert config.get("suite_id") == "evavo_game_runtime_region_content_delivery"
    assert config.get("runtime_repository") == "EVAVO-STUDIO/evavo-game-runtime"
    assert config.get("runtime_branch") == "main"

    runtime_paths = config.get("runtime_paths")
    assert isinstance(runtime_paths, dict)
    assert set(runtime_paths) == {
        "source_validator",
        "binding_validator",
        "delivery_smoke",
        "region_driver_smoke",
        "catalog",
        "world_manifest",
    }
    for value in runtime_paths.values():
        assert isinstance(value, str) and value and not value.startswith(('/', '\\'))
        assert ".." not in Path(value).parts

    markers = config.get("required_markers")
    assert isinstance(markers, dict)
    assert markers == {
        "source": "EVAVO region content delivery validation passed",
        "binding": "EVAVO region package binding validation passed",
        "delivery_smoke": "EVAVO_CONTENT_DELIVERY_SESSION_TEST=PASS",
        "region_driver_smoke": "EVAVO_REGION_CONTENT_DRIVER_TEST=PASS",
    }

    claims = config.get("claims_policy")
    assert isinstance(claims, dict) and claims
    assert all(value is False for value in claims.values())

    execution = config.get("execution")
    assert isinstance(execution, dict)
    assert execution.get("local_only") is True
    assert execution.get("requires_paid_ci") is False
    assert execution.get("requires_vercel") is False
    assert execution.get("requires_github_actions") is False
    assert execution.get("godot_minimum") == "4.6.2"


def validate_contract() -> None:
    contract = load_json(CONTRACT_PATH)
    assert contract.get("properties", {}).get("version", {}).get("const") == 1
    assert (
        contract.get("properties", {}).get("suite_id", {}).get("const")
        == "evavo_game_runtime_region_content_delivery"
    )
    required = set(contract.get("required", []))
    assert {
        "runtime_sha",
        "test_lab_sha",
        "source_validation",
        "executable_validation",
        "claims",
    } <= required

    properties = contract["properties"]
    assert properties["runtime_sha"]["pattern"] == "^[0-9a-f]{40}$"
    assert properties["test_lab_sha"]["pattern"] == "^[0-9a-f]{40}$"
    assert set(properties["status"]["enum"]) == {"pass", "partial", "fail"}

    source_required = set(properties["source_validation"]["required"])
    assert source_required == {"content_delivery", "region_package_binding"}
    executable_required = set(properties["executable_validation"]["required"])
    assert executable_required == {
        "godot_import",
        "delivery_session_smoke",
        "region_driver_smoke",
    }

    claim_properties = properties["claims"]["properties"]
    assert claim_properties
    for schema in claim_properties.values():
        assert schema.get("const") is False

    check_schema = contract["$defs"]["check"]
    assert set(check_schema["properties"]["status"]["enum"]) == {
        "pass",
        "fail",
        "skipped",
        "unverified",
    }


def validate_runner_and_docs() -> None:
    require_symbols(
        RUNNER_PATH,
        (
            "git rev-parse HEAD",
            "validate_region_content_delivery.py",
            "validate_region_package_binding.py",
            "test_content_delivery_session.gd",
            "test_region_content_driver.gd",
            "EVAVO_CONTENT_DELIVERY_SESSION_TEST=PASS",
            "EVAVO_REGION_CONTENT_DRIVER_TEST=PASS",
            "real_storefront_install_verified",
            "real_network_transfer_verified",
            "measured_byte_progress_verified",
            "threaded_load_hard_cancel_verified",
            "resource_completion_grants_authority",
            "declared_bytes_are_measured_bytes",
            "ConvertTo-Json",
        ),
    )
    runner_source = RUNNER_PATH.read_text(encoding="utf-8")
    for forbidden in (
        "gh workflow run",
        "workflow_dispatch",
        "vercel deploy",
        "Invoke-WebRequest",
        "Start-BitsTransfer",
    ):
        assert forbidden not in runner_source, f"runner contains forbidden remote action: {forbidden}"

    require_symbols(
        DOC_PATH,
        (
            "local",
            "runtime SHA",
            "Test Lab SHA",
            "synthetic",
            "storefront",
            "measured",
            "GitHub Actions",
            "Vercel",
        ),
    )


def main() -> None:
    missing = [
        str(path.relative_to(ROOT))
        for path in (CONFIG_PATH, CONTRACT_PATH, RUNNER_PATH, DOC_PATH)
        if not path.is_file()
    ]
    if missing:
        raise AssertionError("Missing Test Lab region delivery files: " + ", ".join(missing))
    validate_config()
    validate_contract()
    validate_runner_and_docs()
    print("EVAVO Test Lab region content delivery contract validation passed")


if __name__ == "__main__":
    main()
