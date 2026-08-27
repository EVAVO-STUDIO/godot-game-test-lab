from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _servers() -> dict[str, dict[str, object]]:
    document = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))
    servers = document.get("mcpServers")
    assert isinstance(servers, dict)
    return servers


def _normalise(value: object) -> str:
    return str(value).replace("\\", "/").casefold()


def test_native_godot_execution_uses_the_workstation_bridge() -> None:
    bridge = _servers()["evavo-windows-workstation-bridge"]

    assert _normalise(bridge["command"]).endswith(
        "evavo-local-compute/.venv/scripts/evavo-windows-workstation-bridge.exe"
    )
    assert bridge["args"] == ["mcp"]

    env = bridge["env"]
    assert isinstance(env, dict)
    for key in (
        "EVAVO_LOCAL_EXECUTION_PREPARE_ENABLED",
        "EVAVO_LOCAL_EXECUTION_MCP_ENABLED",
        "EVAVO_LOCAL_EXECUTION_ENABLED",
        "EVAVO_LOCAL_NETWORK_ENABLED",
        "EVAVO_LOCAL_SCRIPT_EXECUTION_ENABLED",
        "EVAVO_LOCAL_REPOSITORY_CODE_ENABLED",
        "EVAVO_LOCAL_FILESYSTEM_WRITE_ENABLED",
        "EVAVO_LOCAL_CONTAINER_ENABLED",
        "EVAVO_LOCAL_ARCHIVE_ENABLED",
    ):
        assert env[key] == "enabled"
    assert env["EVAVO_LOCAL_GIT_MUTATION_ENABLED"] == "disabled"

    allowed_roots = str(env["EVAVO_LOCAL_EXECUTION_ALLOWED_ROOTS"])
    assert r"C:\GodotLabEvidence" in allowed_roots
    assert r"C:\GitRepos" in allowed_roots


def test_policy_adapter_is_read_only_and_publication_operator_is_absent() -> None:
    servers = _servers()
    provider = servers["evavo-windows-workstation-execution-provider"]

    assert provider["command"] == "node"
    assert provider["args"] == [
        "../evavo-development-studio/scripts/"
        "windows-workstation-execution-provider-mcp.mjs"
    ]
    assert "evavo-local-execution" not in servers
    assert "evavo-windows-chat-execution" not in servers
    assert "evavo-windows-workstation-operator" not in servers


def test_project_mcp_does_not_embed_provider_credentials() -> None:
    servers = _servers()
    forbidden = {
        "ANTHROPIC_API_KEY",
        "CONTROL_PLANE_API_KEY",
        "GH_TOKEN",
        "GITHUB_TOKEN",
        "OPENAI_API_KEY",
        "VERCEL_TOKEN",
    }

    for name, server in servers.items():
        env = server.get("env", {})
        assert isinstance(env, dict), name
        assert forbidden.isdisjoint(env), name
        assert "EVAVO_WINDOWS_CHAT_EXECUTION_ENABLED" not in env, name


def test_agent_rules_keep_target_mutation_and_publication_external() -> None:
    rules = (ROOT / "AGENTS.md").read_text(encoding="utf-8")

    assert "Development Studio owns" in rules
    assert "must never edit, commit, push, deploy, sign, or publish" in rules
    assert "separate Development Studio execution grant" in rules
