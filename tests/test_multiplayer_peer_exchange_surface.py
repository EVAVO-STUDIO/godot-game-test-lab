from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_multiplayer_launcher_cannot_drop_peer_exchange_verification() -> None:
    text = (ROOT / "scripts" / "Invoke-GodotLabMultiplayerAgentQA.ps1").read_text(
        encoding="utf-8"
    )
    for marker in (
        '"-m", "godot_game_test_lab.multiplayer_peer_exchange"',
        '"--summary", $SummaryPath',
        '"--artifacts", $ArtifactPath',
        "$PeerExchangeExitCode -ne 0",
        "Configured multiplayer peer-exchange evidence did not prove reciprocal session participation.",
        "Multiplayer peer-exchange verifier did not emit exactly one admissible evidence marker.",
    ):
        assert marker in text


def test_multiplayer_runner_uses_capture_capable_harness_without_changing_native_driver() -> None:
    runner = (ROOT / "src" / "godot_game_test_lab" / "multiplayer_qa.py").read_text(
        encoding="utf-8"
    )
    native_runner = (
        ROOT / "src" / "godot_game_test_lab" / "native_qa_runner.py"
    ).read_text(encoding="utf-8")
    harness = (ROOT / "scripts" / "godot_multiplayer_input_journey.gd").read_text(
        encoding="utf-8"
    )
    for marker in (
        'lab_root / "scripts" / "godot_input_journey.gd"',
        'lab_root / "scripts" / "godot_multiplayer_input_journey.gd"',
        '"res://.evavo-lab/godot_multiplayer_input_journey.gd"',
    ):
        assert marker in runner
    assert '"res://.evavo-lab/godot_input_journey.gd"' in native_runner
    assert 'godot_multiplayer_input_journey.gd' not in native_runner
    for marker in (
        'extends "res://.evavo-lab/godot_input_journey.gd"',
        'assertion_type == "metadata_capture"',
        'record["actual"] = capture.get("value")',
        '"capture_key_not_reserved"',
        'MAX_CAPTURE_OBSERVED_PEERS := 32',
        'MAX_CAPTURE_PEER_ID := 2147483647',
    ):
        assert marker in harness


def test_peer_exchange_reserved_contract_remains_narrow_and_explicit() -> None:
    verifier = (
        ROOT / "src" / "godot_game_test_lab" / "multiplayer_peer_exchange.py"
    ).read_text(encoding="utf-8")
    profile = (
        ROOT / "src" / "godot_game_test_lab" / "multiplayer_profile.py"
    ).read_text(encoding="utf-8")
    for marker in (
        '"evavo_peer_session_id"',
        '"evavo_local_peer_id"',
        '"evavo_observed_peer_ids"',
        '"evavo_authority_peer_id"',
        '"metadata_capture"',
        '"actual" not in observed',
        "return observed.get(\"actual\")",
        "local_peer in peers",
        "shared authority peer id is not a participating required peer",
        "EVAVO_MULTIPLAYER_PEER_EXCHANGE=NOT_CONFIGURED",
        "EVAVO_MULTIPLAYER_PEER_EXCHANGE=PASS",
        "EVAVO_MULTIPLAYER_PEER_EXCHANGE=FAIL",
        "required_remote_ids.issubset(observed)",
        "transport causality",
    ):
        assert marker in verifier
    for marker in (
        "_CAPTURE_ALLOWED_KEYS",
        "is not a reserved multiplayer evidence key",
        "without advertising metadata_capture to standalone native QA",
    ):
        assert marker in profile


def test_attended_receipt_reverifies_and_binds_peer_exchange() -> None:
    public_surface = (
        ROOT / "src" / "godot_game_test_lab" / "attended_multiplayer.py"
    ).read_text(encoding="utf-8")
    receipt = (
        ROOT / "src" / "godot_game_test_lab" / "attended_multiplayer_receipt.py"
    ).read_text(encoding="utf-8")
    common = (
        ROOT / "src" / "godot_game_test_lab" / "attended_multiplayer_common.py"
    ).read_text(encoding="utf-8")

    for marker in (
        "verify_peer_exchange",
        "ATTENDED_MULTIPLAYER_PEER_EXCHANGE_NOT_PROVEN",
        'evidence["peerExchange"] = peer_exchange',
    ):
        assert marker in public_surface
    for marker in (
        'schema_version=2',
        'body["peerExchange"] = peer_exchange',
        'body["sourceVerification"]["peerExchangeContractReverified"] = True',
        'body["authority"]["transportPathCertified"] = False',
        "RECEIPT_CONTRACT_V1",
        "ATTENDED_MULTIPLAYER_RECEIPT_SCHEMA_OR_CONTRACT_UNSUPPORTED",
    ):
        assert marker in receipt
    assert "attended-multiplayer-receipt.v1" in common
    assert "attended-multiplayer-receipt.v2" in common


def test_peer_exchange_is_discoverable_in_capability_registry() -> None:
    manifest = json.loads((ROOT / "evavo.capabilities.json").read_text(encoding="utf-8"))
    capability = next(
        item for item in manifest["capabilities"] if item["id"] == "testlab.qa.multiplayer"
    )
    assert "peer-exchange" in capability["tags"]
    assert "python -m godot_game_test_lab.multiplayer_peer_exchange" in capability["entrypoints"]
    assert "src/godot_game_test_lab/multiplayer_peer_exchange.py" in capability["entrypoints"]
    assert "docs/MULTIPLAYER_PEER_EXCHANGE.md" in capability["entrypoints"]
    assert (
        "Game-owned reserved metadata assertions on every required role when peer-exchange proof is requested"
        in capability["requires"]
    )
    assert "peer-exchange proof" in capability["description"].lower()


def test_authority_peer_exchange_is_discoverable_as_a_distinct_capability() -> None:
    manifest = json.loads((ROOT / "evavo.capabilities.json").read_text(encoding="utf-8"))
    capability = next(
        item
        for item in manifest["capabilities"]
        if item["id"] == "testlab.qa.authority-peer-exchange"
    )
    assert "authority" in capability["tags"]
    assert "peer-exchange" in capability["tags"]
    assert "lifecycle" in capability["tags"]
    assert "python -m godot_game_test_lab.authority_peer_exchange" in capability["entrypoints"]
    assert "src/godot_game_test_lab/authority_peer_exchange.py" in capability["entrypoints"]
    assert "scripts/Invoke-AuthorityPeerExchangeAcceptance.ps1" in capability["entrypoints"]
    assert "Exact clean target Git head" in capability["requires"]
    assert "Separate client-side QA for browser or native transport traversal" in capability["requires"]
    assert "not browser or native client transport certification" in capability["description"].lower()
