from __future__ import annotations

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
        "Multiplayer peer-exchange verification failed",
    ):
        assert marker in text


def test_peer_exchange_reserved_contract_remains_narrow_and_explicit() -> None:
    text = (
        ROOT / "src" / "godot_game_test_lab" / "multiplayer_peer_exchange.py"
    ).read_text(encoding="utf-8")
    for marker in (
        '"evavo_peer_session_id"',
        '"evavo_local_peer_id"',
        '"evavo_observed_peer_ids"',
        '"evavo_authority_peer_id"',
        "EVAVO_MULTIPLAYER_PEER_EXCHANGE=NOT_CONFIGURED",
        "EVAVO_MULTIPLAYER_PEER_EXCHANGE=PASS",
        "EVAVO_MULTIPLAYER_PEER_EXCHANGE=FAIL",
        "reciprocal peer observation",
        "transport causality",
    ):
        assert marker in text


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
