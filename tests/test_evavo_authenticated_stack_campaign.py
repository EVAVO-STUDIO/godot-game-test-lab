from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest


def load_module() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "tools" / "run_evavo_authenticated_stack_campaign.py"
    spec = importlib.util.spec_from_file_location("evavo_authenticated_stack_campaign", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


campaign = load_module()


def valid_config(tmp_path: Path) -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "campaignId": "authenticated-lobby",
        "gameServicesRepo": str(tmp_path / "game-services"),
        "gameId": "reference-rts",
        "buildHash": "build1234",
        "protocolVersion": 1,
        "players": [
            {
                "playerId": "player_one",
                "displayName": "Player One",
                "deviceId": "device-one",
            },
            {
                "playerId": "player_two",
                "displayName": "Player Two",
                "deviceId": "device-two",
            },
        ],
        "lobby": {
            "lobbyId": "lobby-one",
            "visibility": "public",
            "maxPlayers": 2,
            "region": "local",
            "mode": "conformance",
        },
        "timeouts": {
            "buildSeconds": 30,
            "startupSeconds": 10,
            "commandSeconds": 5,
            "shutdownSeconds": 2,
        },
        "evidenceDirectory": str(tmp_path / "evidence"),
        "buildBeforeRun": False,
    }


def test_campaign_config_is_strict_and_resolves_paths(tmp_path: Path) -> None:
    parsed = campaign.parse_campaign_config(valid_config(tmp_path), base_directory=tmp_path)
    assert parsed.schema_version == 1
    assert parsed.campaign_id == "authenticated-lobby"
    assert parsed.game_services_repo == (tmp_path / "game-services").resolve()
    assert parsed.evidence_directory == (tmp_path / "evidence").resolve()
    assert [player.player_id for player in parsed.players] == ["player_one", "player_two"]
    assert parsed.lobby.max_players == 2
    assert parsed.build_before_run is False

    unknown = valid_config(tmp_path)
    unknown["surprise"] = True
    with pytest.raises(ValueError, match="unknown keys"):
        campaign.parse_campaign_config(unknown, base_directory=tmp_path)


def test_campaign_rejects_duplicate_or_invalid_player_identity(tmp_path: Path) -> None:
    duplicate = valid_config(tmp_path)
    duplicate["players"] = [
        {
            "playerId": "player_one",
            "displayName": "Player One",
            "deviceId": "device-one",
        },
        {
            "playerId": "player_one",
            "displayName": "Other",
            "deviceId": "device-two",
        },
    ]
    with pytest.raises(ValueError, match="duplicate playerId"):
        campaign.parse_campaign_config(duplicate, base_directory=tmp_path)

    invalid = valid_config(tmp_path)
    invalid["gameId"] = "INVALID GAME"
    with pytest.raises(ValueError, match="gameId is invalid"):
        campaign.parse_campaign_config(invalid, base_directory=tmp_path)


def test_campaign_requires_enough_lobby_capacity(tmp_path: Path) -> None:
    value = valid_config(tmp_path)
    lobby = dict(value["lobby"])
    lobby["maxPlayers"] = 1
    value["lobby"] = lobby
    with pytest.raises(ValueError, match="maxPlayers"):
        campaign.parse_campaign_config(value, base_directory=tmp_path)


def test_redaction_removes_tokens_signatures_and_long_secret_values() -> None:
    redacted = campaign.redact(
        {
            "sessionToken": "visible-token",
            "nested": {
                "signature": "visible-signature",
                "ordinary": "safe",
                "opaque": "A" * 64,
            },
            "list": [{"privateKey": "private"}],
        }
    )
    assert redacted["sessionToken"] == "[redacted]"
    assert redacted["nested"]["signature"] == "[redacted]"
    assert redacted["nested"]["ordinary"] == "safe"
    assert redacted["nested"]["opaque"] == "[redacted-long-value]"
    assert redacted["list"][0]["privateKey"] == "[redacted]"


def test_minimal_environment_does_not_inherit_unrelated_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("EVAVO_UNRELATED_SECRET", "do-not-inherit")
    monkeypatch.setenv("RANDOM_API_TOKEN", "do-not-inherit")
    environment = campaign.minimal_environment({"EXPLICIT_VALUE": "yes"})
    assert environment["PATH"] == "/usr/bin"
    assert environment["EXPLICIT_VALUE"] == "yes"
    assert "EVAVO_UNRELATED_SECRET" not in environment
    assert "RANDOM_API_TOKEN" not in environment


def test_atomic_evidence_writer_replaces_complete_json(tmp_path: Path) -> None:
    path = tmp_path / "evidence.json"
    campaign.write_json_atomic(path, {"status": "passed", "steps": [1, 2]})
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "status": "passed",
        "steps": [1, 2],
    }
    assert list(tmp_path.glob("*.tmp")) == []


def test_manifest_example_parses_without_running_external_services() -> None:
    root = Path(__file__).resolve().parents[1]
    manifest = root / "campaigns" / "evavo-authenticated-stack.example.json"
    parsed = campaign.load_config(manifest)
    assert parsed.campaign_id == "evavo-authenticated-lobby-refresh-reconnect"
    assert parsed.game_id == "reference-rts"
    assert len(parsed.players) == 2
