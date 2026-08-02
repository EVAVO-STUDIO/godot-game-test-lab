from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTER = ROOT / "scripts" / "Register-GodotLabMcpWorker.ps1"
START = ROOT / "scripts" / "Start-GodotLabMcp.ps1"
PROBE = ROOT / "scripts" / "Test-GodotLabMcpWorker.ps1"


def test_worker_registration_is_multi_root_config_bound_and_replacement_safe() -> None:
    source = REGISTER.read_text(encoding="utf-8")
    for token in (
        '[Alias("TargetRoot")]',
        '[string[]]$AllowedTargetRoots = @("C:\\GitRepos")',
        '"status", "--porcelain=v1", "--untracked-files=all"',
        "The Lab checkout has tracked or untracked source changes",
        'schemaVersion = "2.0"',
        "allowedTargetRoots = @($resolvedRoots)",
        "labSha = $labSha",
        "autoProvisionEngines = -not [bool]$EngineOffline",
        "godot-lab-mcp-worker-config.json",
        "configurationSha256",
        "Stop-ScheduledTask",
        "The previous MCP worker task did not stop within the timeout",
        "Loopback port $Port is already occupied after stopping the managed task",
        "Refusing to mistake an unrelated listener",
        "-ConfigurationPath",
        "LogonType Interactive",
        "RunLevel Limited",
    ):
        assert token in source, token

    for forbidden in (
        "0.0.0.0",
        "git commit",
        "git push",
        "git reset --hard",
        "Start-Process powershell -Verb RunAs",
        "wrangler deploy",
        "vercel deploy",
    ):
        assert forbidden not in source


def test_worker_start_is_exact_sha_clean_loopback_and_config_driven() -> None:
    source = START.read_text(encoding="utf-8")
    for token in (
        '[string]$ConfigurationPath = ""',
        'schemaVersion -ne "2.0"',
        "allowedTargetRoots",
        "autoProvisionEngines",
        "The MCP worker host must be an explicit loopback address",
        '"status", "--porcelain=v1", "--untracked-files=all"',
        "refuses a Lab checkout with tracked or untracked changes",
        "does not match the checked-out Lab SHA",
        "Explorer in the current nonzero Windows session",
        '"--transport", "streamable-http"',
        '"--no-auto-provision"',
        '@("--allowed-root", $root)',
    ):
        assert token in source, token

    assert "0.0.0.0" not in source
    assert "git push" not in source


def test_worker_acceptance_uses_mcp_protocol_not_only_a_tcp_socket() -> None:
    source = PROBE.read_text(encoding="utf-8")
    for token in (
        "godot_game_test_lab.mcp_probe",
        '"--expected-lab-root", $lab',
        '"--expected-evidence-root", $evidence',
        '"--expected-engine-root", $engines',
        '@("--expected-allowed-root", $root)',
        '"--expect-no-auto-provision"',
        "The loopback endpoint did not prove the expected Godot Lab MCP identity",
        'bridge -ne "evavo-godot-lab-agent"',
        "mcp-worker-acceptance.json",
        '"status", "--porcelain=v1", "--untracked-files=all"',
        "RequireScheduledTask",
    ):
        assert token in source, token

    for forbidden in (
        "0.0.0.0",
        "git commit",
        "git push",
        "Invoke-WebRequest",
        "Test-NetConnection",
    ):
        assert forbidden not in source
