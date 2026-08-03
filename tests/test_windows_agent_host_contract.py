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
        "scripts\\Register-GodotLabMcpWorker.ps1",
        "scripts\\Test-GodotLabAgentHost.ps1",
        "AdditionalTargetRoots",
        "PrepareEstate",
        "PrepareLinuxSandboxImages",
        "InstallPrerequisites",
        "RequireFullMediaToolchain",
        "AllowedTargetRoots = @($allTargetRoots)",
        "StartNow = $true",
        "ExpectedLabSha = $labSha",
        "EngineOffline = $true",
        "& $acceptance @acceptanceParameters",
        "Agent host initialization and acceptance completed",
    ):
        assert token in source, token

    for forbidden in (
        "scripts\\Test-GodotLabMcpWorker.ps1",
        "$workerProbeParameters",
        "& $testWorker",
        "SkipWorkerProbe",
        "RegisterWorker = $true",
        "StartWorker = $true",
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
        "EngineRoot must remain disjoint from Lab, target, and evidence roots.",
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
        "Test-GodotLabMcpWorker.ps1",
        "RequireScheduledTask = $true",
        "The retained MCP worker receipt has invalid authority types.",
        'endpoint = "http://127.0.0.1:$Port/mcp"',
        "Invoke-GodotLabNativeValidation.ps1",
        "Invoke-GodotLabNativeAgentQA.ps1",
        "Invoke-GodotLabBotQA.ps1",
        '[string]$HostRunRoot = ""',
        "HostRunRoot must be an absolute path.",
        "HostRunRoot must remain beneath EvidenceRoot.",
        "HostRunRoot must not already exist",
        "HostRunRoot parent must already exist",
        "Resolved HostRunRoot must remain beneath EvidenceRoot.",
        "Evidence receipt already exists",
        'schemaVersion = "1.1"',
        "sourceChecks = $sourceChecks",
        "Read complete acceptance target status",
        "Final host Lab SHA",
        "Final host Lab status",
        "Final host target SHA",
        "Final host target status",
        "Final host source verification failed",
        "host-acceptance.json",
        "Write-AtomicJson -Path $receiptPath",
        "Receipt write failed",
    ):
        assert token in source, token

    for forbidden in (
        "SkipWorkerProbe",
        "if ($RegisterWorker -or $StartWorker)",
        "[bool]$probe.capabilities.autoProvisionEngines",
        "git commit",
        "git push",
        "git reset --hard",
        "gh pr",
        "Start-Process powershell -Verb RunAs",
        "0.0.0.0",
        "wrangler deploy",
        "vercel deploy",
        "Move-Item -LiteralPath $temporary -Destination $Path -Force",
    ):
        assert forbidden not in source


def test_protocol_proof_is_single_unconditional_and_precedes_target_work() -> None:
    source = ACCEPTANCE.read_text(encoding="utf-8")
    stage = 'Invoke-Stage -Id "worker-protocol-acceptance"'

    assert source.count(stage) == 1
    assert source.index(stage) < source.index('Invoke-Stage -Id "target-validation"')
    assert "if (-not $SkipWorkerProbe)" not in source
    assert "RequireScheduledTask = $true" in source


def test_host_final_source_checks_precede_receipt_publication() -> None:
    source = ACCEPTANCE.read_text(encoding="utf-8")
    final_lab = source.index("Final host Lab SHA")
    final_target = source.index("Final host target SHA")
    final_error = source.index("Final host source verification failed")
    write_receipt = source.index("Write-AtomicJson -Path $receiptPath")

    assert final_lab < final_target < final_error < write_receipt
    assert source.count("sourceChecks = $sourceChecks") == 1
    assert 'schemaVersion = "1.1"' in source
