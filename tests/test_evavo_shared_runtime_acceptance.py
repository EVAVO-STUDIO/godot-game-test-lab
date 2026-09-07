from __future__ import annotations

import importlib.util
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_PATH = ROOT / "scripts" / "validate-evavo-shared-runtime-acceptance.py"

EXPECTED_NETWORKING_CONTRACTS = [
    "res://tests/godot/validate_multiplayer_peer_factory.gd",
    "res://tests/godot/validate_network_clock_profile.gd",
    "res://tests/godot/validate_entity_replication_envelope.gd",
    "res://tests/godot/validate_entity_replication_receive_guard.gd",
    "res://tests/godot/validate_replication_authority_contract.gd",
    "res://tests/godot/validate_replication_visibility_policy.gd",
    "res://tests/godot/validate_partition_handoff_protocol.gd",
    "res://tests/godot/validate_network_state_buffers.gd",
    "res://tests/godot/validate_network_reconciliation_pipeline.gd",
]


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


def _networking_evidence(
    observed: list[str] | None = None,
    *,
    aggregate_occurrences: int = 1,
) -> dict[str, object]:
    observed_contracts = list(EXPECTED_NETWORKING_CONTRACTS if observed is None else observed)
    counts = {item: observed_contracts.count(item) for item in set(observed_contracts)}
    missing = [item for item in EXPECTED_NETWORKING_CONTRACTS if item not in counts]
    unexpected = sorted(item for item in counts if item not in EXPECTED_NETWORKING_CONTRACTS)
    duplicates = sorted(item for item, count in counts.items() if count != 1)
    valid = (
        aggregate_occurrences == 1
        and observed_contracts == EXPECTED_NETWORKING_CONTRACTS
        and not missing
        and not unexpected
        and not duplicates
    )
    return {
        "expected_contract_count": len(EXPECTED_NETWORKING_CONTRACTS),
        "observed_contract_count": len(observed_contracts),
        "aggregate_marker": f"EVAVO_NETWORKING_CONTRACTS=PASS count={len(EXPECTED_NETWORKING_CONTRACTS)}",
        "aggregate_marker_occurrences": aggregate_occurrences,
        "expected_contracts": list(EXPECTED_NETWORKING_CONTRACTS),
        "observed_contracts": observed_contracts,
        "missing_contracts": missing,
        "unexpected_contracts": unexpected,
        "duplicate_contracts": duplicates,
        "valid": valid,
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
        "networking_evidence": _networking_evidence(),
        "issues": [],
        "claims": {
            "source_only_is_executable_pass": False,
            "dirty_checkout_is_release_evidence": False,
            "networking_contracts_executed": True,
            "game_runtime_contracts_executed": True,
            "web_runtime_contracts_executed": True,
        },
    }


def _source_only_receipt() -> dict[str, object]:
    receipt = _receipt()
    receipt["status"] = "source_only"
    receipt["godot"] = None
    commands = receipt["commands"]
    assert isinstance(commands, list)
    engine = commands[0]
    assert isinstance(engine, dict)
    engine["status"] = "skipped"
    receipt["networking_evidence"] = _networking_evidence([], aggregate_occurrences=0)
    claims = receipt["claims"]
    assert isinstance(claims, dict)
    claims["networking_contracts_executed"] = False
    return receipt


def test_accepts_consistent_full_pass_receipt() -> None:
    validator = _load_validator()
    validator.validate_receipt(_receipt())


def test_accepts_consistent_source_only_receipt_without_network_markers() -> None:
    validator = _load_validator()
    validator.validate_receipt(_source_only_receipt())


def test_rejects_claim_that_disagrees_with_marker_evidence() -> None:
    validator = _load_validator()
    receipt = _receipt()
    claims = receipt["claims"]
    assert isinstance(claims, dict)
    claims["networking_contracts_executed"] = False
    with pytest.raises(ValueError, match="networking_contracts_executed"):
        validator.validate_receipt(receipt)


def test_rejects_dirty_full_pass_receipt() -> None:
    validator = _load_validator()
    receipt = _receipt()
    repositories = receipt["repositories"]
    assert isinstance(repositories, dict)
    engine_repo = repositories["engine_systems"]
    assert isinstance(engine_repo, dict)
    engine_repo["dirty"] = True
    with pytest.raises(ValueError, match="clean evidence"):
        validator.validate_receipt(receipt)


def test_source_only_cannot_claim_engine_networking_execution() -> None:
    validator = _load_validator()
    receipt = _source_only_receipt()
    claims = receipt["claims"]
    assert isinstance(claims, dict)
    claims["networking_contracts_executed"] = True
    with pytest.raises(ValueError, match="networking_contracts_executed|source_only"):
        validator.validate_receipt(receipt)


def test_rejects_forged_valid_flag_when_one_network_contract_is_missing() -> None:
    validator = _load_validator()
    receipt = _receipt()
    evidence = _networking_evidence(EXPECTED_NETWORKING_CONTRACTS[:-1])
    evidence["valid"] = True
    receipt["networking_evidence"] = evidence
    with pytest.raises(ValueError, match="valid disagrees"):
        validator.validate_receipt(receipt)


def test_rejects_inconsistent_observed_count() -> None:
    validator = _load_validator()
    receipt = _receipt()
    evidence = receipt["networking_evidence"]
    assert isinstance(evidence, dict)
    evidence["observed_contract_count"] = 8
    with pytest.raises(ValueError, match="observed_contract_count"):
        validator.validate_receipt(receipt)


def test_rejects_duplicate_network_contract_evidence() -> None:
    validator = _load_validator()
    receipt = _receipt()
    observed = list(EXPECTED_NETWORKING_CONTRACTS)
    observed.append(EXPECTED_NETWORKING_CONTRACTS[-1])
    evidence = _networking_evidence(observed)
    evidence["duplicate_contracts"] = []
    receipt["networking_evidence"] = evidence
    with pytest.raises(ValueError, match="duplicate_contracts"):
        validator.validate_receipt(receipt)


def test_rejects_wrong_networking_aggregate_marker() -> None:
    validator = _load_validator()
    receipt = _receipt()
    evidence = receipt["networking_evidence"]
    assert isinstance(evidence, dict)
    evidence["aggregate_marker"] = "EVAVO_NETWORKING_CONTRACTS=PASS count=8"
    with pytest.raises(ValueError, match="aggregate_marker"):
        validator.validate_receipt(receipt)


def test_accepts_failed_receipt_when_process_exits_zero_but_marker_evidence_is_incomplete() -> None:
    validator = _load_validator()
    receipt = deepcopy(_receipt())
    receipt["status"] = "failed"
    receipt["networking_evidence"] = _networking_evidence(EXPECTED_NETWORKING_CONTRACTS[:-1], aggregate_occurrences=0)
    receipt["issues"] = ["engine_networking_evidence_invalid"]
    claims = receipt["claims"]
    assert isinstance(claims, dict)
    claims["networking_contracts_executed"] = False
    validator.validate_receipt(receipt)


def test_rejects_passed_receipt_when_networking_marker_evidence_is_incomplete() -> None:
    validator = _load_validator()
    receipt = _receipt()
    receipt["networking_evidence"] = _networking_evidence(EXPECTED_NETWORKING_CONTRACTS[:-1], aggregate_occurrences=0)
    claims = receipt["claims"]
    assert isinstance(claims, dict)
    claims["networking_contracts_executed"] = False
    with pytest.raises(ValueError, match="evidence issue|non-failed"):
        validator.validate_receipt(receipt)
