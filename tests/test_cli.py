from __future__ import annotations

import json
from pathlib import Path

from godot_game_test_lab import cli
from godot_game_test_lab.cli import main


def make_project(root: Path, *, broken: bool = False) -> Path:
    root.mkdir()
    (root / "project.godot").write_text(
        'config_version=5\n[application]\n'
        'config/name="CLI Fixture"\n'
        'run/main_scene="res://main.tscn"\n',
        encoding="utf-8",
    )
    scene = (
        '[gd_scene format=3]\n[node name="One" type="Node"]\n'
        '[node name="Two" type="Node"]\n'
        if broken
        else '[gd_scene format=3]\n[node name="Main" type="Node"]\n'
    )
    (root / "main.tscn").write_text(scene, encoding="utf-8")
    return root


def test_inspect_command_outputs_json(tmp_path: Path, capsys) -> None:
    project = make_project(tmp_path / "game")

    exit_code = main(["inspect", str(project)])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["project_name"] == "CLI Fixture"


def test_audit_command_passes_valid_project(tmp_path: Path, capsys) -> None:
    project = make_project(tmp_path / "game")

    exit_code = main(["audit", str(project)])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["status"] == "passed"
    assert payload["errors"] == 0


def test_audit_command_fails_corrupt_scene_and_writes_report(tmp_path: Path, capsys) -> None:
    project = make_project(tmp_path / "game", broken=True)
    output = tmp_path / "audit.json"

    exit_code = main(["audit", str(project), "--output", str(output)])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert payload["status"] == "failed"
    assert output.is_file()
    assert json.loads(output.read_text(encoding="utf-8"))["errors"] > 0


def test_audit_command_rejects_invalid_limits(tmp_path: Path, capsys) -> None:
    project = make_project(tmp_path / "game")

    exit_code = main(["audit", str(project), "--max-files", "0"])
    captured = capsys.readouterr()

    assert exit_code == 2
    assert "max_files" in captured.err


def test_capabilities_command_is_machine_readable(capsys) -> None:
    exit_code = main(["capabilities"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["schemaVersion"] == "1.2"
    assert payload["toolVersion"] == "0.7.0"
    assert "audit" in payload["commands"]
    assert payload["automationEntrypoints"] == {
        "profileBootstrap": "godot-lab-init-qa",
        "nativeAuthoredQa": "godot-lab-native-qa",
        "nativeBotQa": "godot-lab-bot-qa",
        "mediaQa": "godot-lab-media-qa",
        "mcpAgentBridge": "godot-lab-mcp",
        "engineProvisioning": "godot-lab engine bootstrap|ensure|status|env",
        "localLinuxSandbox": "godot-lab sandbox status|image|run",
        "nativeValidationWrapper": "scripts/Invoke-GodotLabNativeValidation.ps1",
        "nativeAuthoredQaWrapper": "scripts/Invoke-GodotLabNativeAgentQA.ps1",
        "nativeBotQaWrapper": "scripts/Invoke-GodotLabBotQA.ps1",
        "localLinuxSandboxWrapper": "scripts/Invoke-GodotLabLinuxSandbox.ps1",
        "linuxWorkflow": ".github/workflows/reusable-godot-linux-sandbox.yml",
    }
    assert "authoritative Godot --import" in payload["validationStages"]
    assert "deterministic fresh-process bot state exploration" in payload["validationStages"]
    assert "bot-agent-summary.json" in payload["evidence"]
    assert "engine-installation.json receipts and official SHA512 identities" in payload[
        "evidence"
    ]


def test_audit_warnings_as_errors_exposes_policy_status(tmp_path: Path, capsys) -> None:
    project = make_project(tmp_path / "game")
    (project / "tool.gd").write_text("@tool\nextends Node\n", encoding="utf-8")

    exit_code = main(["audit", str(project), "--warnings-as-errors"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert payload["status"] == "passed"
    assert payload["policy_status"] == "failed"
    assert payload["warnings_as_errors"] is True


def test_linux_sandbox_retains_static_integrity_sidecar(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    project = make_project(tmp_path / "game")
    artifacts = tmp_path / "artifacts"

    class DummyReport:
        def __init__(self) -> None:
            self.status = "passed"
            self.findings: list[str] = []
            self.artifacts: list[str] = []

        def to_json(self) -> str:
            return json.dumps(
                {
                    "status": self.status,
                    "findings": self.findings,
                    "artifacts": self.artifacts,
                }
            )

    monkeypatch.setattr(cli, "run_linux_sandbox", lambda *args, **kwargs: DummyReport())

    exit_code = main(
        [
            "linux-sandbox",
            str(project),
            "--working-root",
            str(tmp_path / "work"),
            "--artifacts",
            str(artifacts),
            "--godot",
            str(tmp_path / "godot"),
            "--visual-frames",
            "0",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert (artifacts / "integrity-report.json").is_file()
    assert (artifacts / "sandbox-report.json").is_file()
    assert "integrity-report.json" in payload["artifacts"]
    assert payload["findings"][0].startswith("static-integrity:")


def test_linux_sandbox_blocks_path_escape_before_runner(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    project = tmp_path / "game"
    project.mkdir()
    (project / "project.godot").write_text(
        'config_version=5\n\n[application]\nrun/main_scene="res://../outside.tscn"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        cli,
        "run_linux_sandbox",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("unsafe project must not reach Godot runner")
        ),
    )
    artifacts = tmp_path / "evidence"

    exit_code = cli.main(
        [
            "linux-sandbox",
            str(project),
            "--working-root",
            str(tmp_path / "work"),
            "--artifacts",
            str(artifacts),
            "--godot",
            str(tmp_path / "godot"),
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert payload["status"] == "blocked"
    assert "project.main_scene_escape" in payload["findings"][1]
    assert (artifacts / "integrity-report.json").is_file()
    assert (artifacts / "sandbox-report.json").is_file()
