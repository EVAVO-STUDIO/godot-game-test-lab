from __future__ import annotations

from pathlib import Path

import pytest


def test_mcp_source_exposes_visual_audio_and_execution_tools() -> None:
    source = Path(__file__).resolve().parents[1] / "src" / "godot_game_test_lab" / "mcp_server.py"
    text = source.read_text(encoding="utf-8")
    for token in (
        'name="godot_ensure_engine"',
        'name="godot_run_bot_qa"',
        'name="godot_run_native_qa"',
        'name="godot_view_image"',
        'name="godot_hear_audio"',
        'name="godot_analyze_run_media"',
        "AudioContent",
        "Image(data=data",
        'choices=("stdio", "streamable-http")',
        "restricted to an explicit loopback host",
        'parser.add_argument("--engine-root"',
        '"--no-auto-provision"',
    ):
        assert token in text, token


def test_fastmcp_server_builds_when_optional_agent_extra_is_installed(tmp_path: Path) -> None:
    pytest.importorskip("mcp")
    from godot_game_test_lab.agent_bridge import BridgeConfig
    from godot_game_test_lab.mcp_server import build_server

    lab = tmp_path / "lab"
    games = tmp_path / "games"
    evidence = tmp_path / "evidence"
    lab.mkdir()
    games.mkdir()
    evidence.mkdir()
    server = build_server(
        BridgeConfig(
            lab_root=lab,
            allowed_target_roots=(games,),
            evidence_root=evidence,
            require_interactive_desktop=False,
        )
    )
    assert server.name == "EVAVO Godot Game Test Lab"
