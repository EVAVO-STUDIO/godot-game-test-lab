from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

import godot_game_test_lab.agent_bridge as agent_bridge_module
from godot_game_test_lab.agent_bridge import BridgeConfig, GodotAgentBridge
from godot_game_test_lab.native_qa_common import NativeQaError


def _git_repo(root: Path) -> str:
    root.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Fixture"], cwd=root, check=True)
    subprocess.run(
        ["git", "config", "user.email", "fixture@example.com"], cwd=root, check=True
    )
    (root / "project.godot").write_text(
        'config_version=5\n[application]\nrun/main_scene="res://main.tscn"\n',
        encoding="utf-8",
    )
    (root / "main.tscn").write_text(
        '[gd_scene format=3]\n[node name="Main" type="Node"]\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "fixture"], cwd=root, check=True)
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()


def test_bridge_resolves_only_allowed_projects_and_retains_external_evidence(
    tmp_path: Path,
) -> None:
    lab = tmp_path / "lab"
    games = tmp_path / "games"
    game = games / "demo"
    _git_repo(lab)
    target_sha = _git_repo(game)
    evidence = tmp_path / "evidence"

    bridge = GodotAgentBridge(
        BridgeConfig.from_environment(
            lab_root=lab,
            allowed_target_roots=[games],
            evidence_root=evidence,
            require_interactive_desktop=False,
            auto_provision_engines=False,
        )
    )
    record = bridge.target_record(str(game), require_clean=True)

    assert record.target_sha == target_sha
    assert record.project_subpath == "."
    assert Path(record.project_root) == game
    assert bridge.capabilities()["evidenceRoot"] == str(evidence.resolve())

    outside = tmp_path / "outside"
    _git_repo(outside)
    with pytest.raises(NativeQaError, match="outside"):
        bridge.target_record(str(outside))


def test_bridge_artifact_access_rejects_traversal_and_wrong_media_type(tmp_path: Path) -> None:
    lab = tmp_path / "lab"
    games = tmp_path / "games"
    _git_repo(lab)
    games.mkdir()
    evidence = tmp_path / "evidence"
    run = evidence / "20260801T000000Z-test-demo-1234567890"
    run.mkdir(parents=True)
    (run / "summary.json").write_text('{"status":"passed"}\n', encoding="utf-8")
    (run / "screen.png").write_bytes(b"\x89PNG\r\n\x1a\nfixture")
    (run / "audio.wav").write_bytes(b"RIFFfixture")

    bridge = GodotAgentBridge(
        BridgeConfig.from_environment(
            lab_root=lab,
            allowed_target_roots=[games],
            evidence_root=evidence,
            require_interactive_desktop=False,
            auto_provision_engines=False,
        )
    )

    assert bridge.read_json_artifact(run.name, "summary.json")["status"] == "passed"
    assert bridge.image_artifact(run.name, "screen.png")[1] == "png"
    assert bridge.audio_artifact(run.name, "audio.wav")[1] in {"audio/wav", "audio/x-wav"}
    with pytest.raises(NativeQaError):
        bridge.read_json_artifact(run.name, "../summary.json")
    with pytest.raises(NativeQaError, match="not a supported image"):
        bridge.image_artifact(run.name, "audio.wav")


def test_profile_proposal_stays_outside_target_checkout(tmp_path: Path) -> None:
    lab = tmp_path / "lab"
    games = tmp_path / "games"
    game = games / "demo"
    _git_repo(lab)
    _git_repo(game)
    evidence = tmp_path / "evidence"
    bridge = GodotAgentBridge(
        BridgeConfig.from_environment(
            lab_root=lab,
            allowed_target_roots=[games],
            evidence_root=evidence,
            require_interactive_desktop=False,
            auto_provision_engines=False,
        )
    )

    result = bridge.propose_bot_profile(str(game))

    assert result["status"] == "proposed"
    assert Path(result["profile"]).is_file()
    assert Path(result["discovery"]).is_file()
    assert not (game / ".evavo").exists()
    assert json.loads(Path(result["profile"]).read_text())["campaigns"]


class _DummyValidationReport:
    status = "passed"

    def to_json(self) -> str:
        return json.dumps({"status": "passed", "findings": [], "artifacts": []})


def test_bridge_validation_executes_exact_archive_not_target_checkout(
    monkeypatch, tmp_path: Path
) -> None:
    lab = tmp_path / "lab"
    games = tmp_path / "games"
    game = games / "demo"
    _git_repo(lab)
    _git_repo(game)
    evidence = tmp_path / "evidence"
    bridge = GodotAgentBridge(
        BridgeConfig.from_environment(
            lab_root=lab,
            allowed_target_roots=[games],
            evidence_root=evidence,
            require_interactive_desktop=False,
            auto_provision_engines=False,
        )
    )
    executed: list[Path] = []

    def fake_archive(
        git_root: Path, _sha: str, destination: Path, _timeout: int
    ) -> dict[str, int]:
        shutil.copytree(git_root, destination, ignore=shutil.ignore_patterns(".git"))
        return {"members": 2, "files": 2, "bytes": 128}

    def fake_validate(project: Path, **_kwargs) -> _DummyValidationReport:
        executed.append(project)
        (project / ".godot").mkdir()
        return _DummyValidationReport()

    monkeypatch.setattr(agent_bridge_module, "_archive_checkout", fake_archive)
    monkeypatch.setattr(agent_bridge_module, "validate_project_pipeline", fake_validate)
    monkeypatch.setattr(agent_bridge_module, "write_report_bundle", lambda *_args: None)

    result = bridge.validate(str(game))

    assert result["status"] == "passed"
    assert result["targetCheckoutExecuted"] is False
    assert result["sourceArchive"]["files"] == 2
    assert len(executed) == 1
    assert executed[0] != game
    assert not (game / ".godot").exists()
    assert not (Path(result["runRoot"]) / "work").exists()
    assert (Path(result["runRoot"]) / "source-archive.json").is_file()


def test_strict_media_failure_propagates_to_bot_summary(
    monkeypatch, tmp_path: Path
) -> None:
    lab = tmp_path / "lab"
    games = tmp_path / "games"
    game = games / "demo"
    _git_repo(lab)
    _git_repo(game)
    bridge = GodotAgentBridge(
        BridgeConfig.from_environment(
            lab_root=lab,
            allowed_target_roots=[games],
            evidence_root=tmp_path / "evidence",
            require_interactive_desktop=False,
            auto_provision_engines=False,
        )
    )
    monkeypatch.setattr(
        agent_bridge_module,
        "run_bot_qa",
        lambda _args: {"status": "passed", "findings": []},
    )
    monkeypatch.setattr(
        bridge,
        "_media_review",
        lambda _root, _policy: {"status": "blocked", "error": "no movie"},
    )

    result = bridge.run_bot_qa(
        str(game),
        ".evavo/godot-lab-bot.json",
        media_policy={"requireAudioTrack": True},
    )

    assert result["status"] == "failed"
    assert result["mediaReview"]["status"] == "blocked"
    assert any("media QA" in finding for finding in result["findings"])


def test_optional_missing_media_does_not_override_bot_pass(
    monkeypatch, tmp_path: Path
) -> None:
    lab = tmp_path / "lab"
    games = tmp_path / "games"
    game = games / "demo"
    _git_repo(lab)
    _git_repo(game)
    bridge = GodotAgentBridge(
        BridgeConfig.from_environment(
            lab_root=lab,
            allowed_target_roots=[games],
            evidence_root=tmp_path / "evidence",
            require_interactive_desktop=False,
            auto_provision_engines=False,
        )
    )
    monkeypatch.setattr(
        agent_bridge_module,
        "run_bot_qa",
        lambda _args: {"status": "passed", "findings": []},
    )
    monkeypatch.setattr(
        bridge,
        "_media_review",
        lambda _root, _policy: {"status": "blocked", "error": "no movie"},
    )

    result = bridge.run_bot_qa(str(game), ".evavo/godot-lab-bot.json")

    assert result["status"] == "passed"
    assert result["mediaReview"]["status"] == "blocked"


def test_bridge_can_provision_the_project_editor(
    monkeypatch, tmp_path: Path
) -> None:
    lab = tmp_path / "lab"
    games = tmp_path / "games"
    game = games / "demo"
    _git_repo(lab)
    _git_repo(game)
    engine_root = tmp_path / "engines"
    bridge = GodotAgentBridge(
        BridgeConfig.from_environment(
            lab_root=lab,
            allowed_target_roots=[games],
            evidence_root=tmp_path / "evidence",
            engine_root=engine_root,
            require_interactive_desktop=False,
        )
    )

    class Selection:
        version = "4.6.3"
        flavor = "standard"
        project_branch = "4.6"
        csharp = False
        reason = "project feature branch 4.6"

    class Installation:
        executable = str(engine_root / "godot")

        def to_dict(self) -> dict[str, str]:
            return {
                "version": "4.6.3",
                "flavor": "standard",
                "executable": self.executable,
            }

    monkeypatch.setattr(
        agent_bridge_module,
        "ensure_project_engine",
        lambda *_args, **_kwargs: (Selection(), Installation()),
    )

    result = bridge.ensure_engine(str(game))

    assert result["status"] == "ready"
    assert result["selection"]["version"] == "4.6.3"
    assert result["installation"]["flavor"] == "standard"


def test_bridge_rejects_target_paths_through_symlinked_parents(tmp_path: Path) -> None:
    lab = tmp_path / "lab"
    games = tmp_path / "games"
    game = games / "demo"
    _git_repo(lab)
    _git_repo(game)
    evidence = tmp_path / "evidence"
    alias = tmp_path / "games-alias"
    alias.symlink_to(games, target_is_directory=True)

    bridge = GodotAgentBridge(
        BridgeConfig.from_environment(
            lab_root=lab,
            allowed_target_roots=[games],
            evidence_root=evidence,
            require_interactive_desktop=False,
            auto_provision_engines=False,
        )
    )

    with pytest.raises(NativeQaError, match="symbolic link"):
        bridge.target_record(str(alias / "demo"))
