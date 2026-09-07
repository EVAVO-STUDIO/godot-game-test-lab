from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_PATH = ROOT / "scripts" / "validate-evavo-shared-runtime-acceptance.py"


def _load_validator():
    spec = importlib.util.spec_from_file_location("evavo_shared_runtime_acceptance", VALIDATOR_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _repo(name: str) -> dict[str, object]:
    return {
        "path": f"/workspace/{name}",
        "sha": "a" * 40,
        "branch": "main",
        "dirty": False,
    }


def _command(name: str, repository: str) -> dict[str, object]:
    return {
        "name": name,
        "repository": repository,
        "status": "passed",
        "exit_code": 0,
        "duration_ms": 12,
        "log_path": f"/tmp/{name}.log",
    }


def _receipt() -> dict[str, object]:
    return {
        "version": 1,
        "generated_utc": "2026-09-07T12:00:00Z",
        "status": "passed",
        "test_lab": _repo("godot-game-test-lab"),
        "repositories": {
            "game_runtime": _repo("evavo-game-runtime"),
            "engine_systems": _repo("godot-engine-systems"),
            "web_runtime": _repo("godot-web-runtime"),
        },
        "godot": {"path": "/tools/godot", "version": "4.6.3.stable"},
        "commands": [
            _command("engine-networking-contracts", "godot-engine-systems"),
            _command("game-runtime-contracts", "evavo-game-runtime"),
            _command("web-runtime-check", "godot-web-runtime"),
        ],
        "issues": [],
        "claims": {
            "source_only_is_executable_pass": False,
            "dirty_checkout_is_release_evidence": False,
            "networking_contracts_executed": True,
            "game_runtime_contracts_executed": True,
            "web_runtime_contracts_executed": True,
        },
    }


def test_accepts_consistent_full_pass_receipt() -> None:
    validator = _load_validator()
    validator.validate_receipt(_receipt())


def test_rejects_claim_that_disagrees_with_command_evidence() -> None:
    validator = _load_validator()
    receipt = _receipt()
    receipt["claims"]["networking_contracts_executed"] = False  # type: ignore[index]
    with pytest.raises(ValueError, match="networking_contracts_executed"):
        validator.validate_receipt(receipt)


def test_rejects_dirty_full_pass_receipt() -> None:
    validator = _load_validator()
    receipt = _receipt()
    receipt["repositories"]["engine_systems"]["dirty"] = True  # type: ignore[index]
    with pytest.raises(ValueError, match="clean evidence"):
        validator.validate_receipt(receipt)


def test_source_only_cannot_claim_engine_networking_execution() -> None:
    validator = _load_validator()
    receipt = _receipt()
    receipt["status"] = "source_only"
    with pytest.raises(ValueError, match="source_only"):
        validator.validate_receipt(receipt)
