from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INITIALIZE = ROOT / "scripts" / "Initialize-GodotLabAgentHost.ps1"
ACCEPTANCE = ROOT / "scripts" / "Test-GodotLabAgentHost.ps1"


def test_agent_host_initializer_is_one_command_and_delegates_safely() -> None:
    source = INITIALIZE.read_text(encoding="utf-8")
    for token in (
        "Initialize-GodotLabAgentHost.ps1 must run on Windows",
        "scripts\\Install-GodotLab.ps1",
        "scripts\\Test-GodotLabAgentHost.ps1",
        "PrepareEstate",
        "PrepareLinuxSandboxImages",
        "InstallPrerequisites",
        "RequireFullMediaToolchain",
        "RegisterWorker = $true",
        "StartWorker = $true",
        "ExpectedLabSha = $labSha",
        "Agent host initialization and acceptance completed",
    ):
        assert token in source, token

    for forbidden in (
        "git commit",
        "git push",
        "git reset --hard",
        "gh pr",
        "wrangler deploy",
        "vercel deploy",
    ):
        assert forbidden not in source


def test_agent_host_acceptance_proves_interactive_worker_and_real_toolchain() -> None:
    source = ACCEPTANCE.read_text(encoding="utf-8")
    for token in (
        "Agent-host acceptance must run on Windows",
        "Explorer in the current nonzero Windows session",
        "Assert-NoReparsePoint",
        "EvidenceRoot must remain disjoint from the Lab checkout",
        "EngineRoot must remain disjoint from every allowed target root",
        '"scripts/check_repository_toolchain.py", "--native-family", "--installed"',
        "godot_game_test_lab.cli engine status",
        'flavors -notcontains "standard"',
        'flavors -notcontains "mono"',
        "godot_game_test_lab.cli doctor",
        "godot_game_test_lab.mcp_server",
        '"--self-test"',
        "Get-CimInstance Win32_VideoController",
        "Get-CimInstance Win32_SoundDevice",
        "nvidia-smi",
        "Register-GodotLabMcpWorker.ps1",
        "Test-LoopbackPort",
        'endpoint = "http://127.0.0.1:$Port/mcp"',
        "Invoke-GodotLabNativeValidation.ps1",
        "Invoke-GodotLabNativeAgentQA.ps1",
        "Invoke-GodotLabBotQA.ps1",
        "host-acceptance.json",
        "Write-AtomicJson -Path $receiptPath",
    ):
        assert token in source, token

    for forbidden in (
        "git commit",
        "git push",
        "git reset --hard",
        "gh pr",
        "Start-Process powershell -Verb RunAs",
        "0.0.0.0",
        "wrangler deploy",
        "vercel deploy",
    ):
        assert forbidden not in source
