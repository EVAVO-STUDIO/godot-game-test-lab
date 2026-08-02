from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from godot_game_test_lab.agent_bridge import BridgeConfig, GodotAgentBridge
from godot_game_test_lab.native_qa_common import NativeQaError


def _git_repo(root: Path) -> None:
    root.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
    subprocess.run(
        ["git", "config", "user.name", "Fixture"], cwd=root, check=True
    )
    subprocess.run(
        ["git", "config", "user.email", "fixture@example.com"],
        cwd=root,
        check=True,
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
    subprocess.run(
        ["git", "commit", "-q", "-m", "fixture"], cwd=root, check=True
    )


def test_evidence_inside_lab_is_rejected_before_any_root_is_created(
    tmp_path: Path,
) -> None:
    lab = tmp_path / "lab"
    targets = tmp_path / "targets"
    lab.mkdir()
    targets.mkdir()
    evidence = lab / "evidence"
    engine = tmp_path / "engine"

    with pytest.raises(NativeQaError, match="Agent evidence root"):
        BridgeConfig.from_environment(
            lab_root=lab,
            allowed_target_roots=[targets],
            evidence_root=evidence,
            engine_root=engine,
        )

    assert not evidence.exists()
    assert not engine.exists()


def test_evidence_parent_of_protected_roots_is_rejected(tmp_path: Path) -> None:
    lab = tmp_path / "estate" / "lab"
    targets = tmp_path / "estate" / "targets"
    lab.mkdir(parents=True)
    targets.mkdir()
    engine = tmp_path / "engine"

    with pytest.raises(NativeQaError, match="Agent evidence root"):
        BridgeConfig.from_environment(
            lab_root=lab,
            allowed_target_roots=[targets],
            evidence_root=tmp_path / "estate",
            engine_root=engine,
        )

    assert not engine.exists()


def test_engine_inside_evidence_is_rejected_without_side_effects(
    tmp_path: Path,
) -> None:
    lab = tmp_path / "lab"
    targets = tmp_path / "targets"
    lab.mkdir()
    targets.mkdir()
    evidence = tmp_path / "evidence"
    engine = evidence / "engines"

    with pytest.raises(NativeQaError, match="Managed engine root"):
        BridgeConfig.from_environment(
            lab_root=lab,
            allowed_target_roots=[targets],
            evidence_root=evidence,
            engine_root=engine,
        )

    assert not evidence.exists()
    assert not engine.exists()


def test_disjoint_bridge_roots_are_created_and_reported(tmp_path: Path) -> None:
    lab = tmp_path / "lab"
    targets = tmp_path / "targets"
    lab.mkdir()
    targets.mkdir()
    evidence = tmp_path / "evidence"
    engine = tmp_path / "engine"

    config = BridgeConfig.from_environment(
        lab_root=lab,
        allowed_target_roots=[targets],
        evidence_root=evidence,
        engine_root=engine,
        require_interactive_desktop=False,
        auto_provision_engines=False,
    )
    capabilities = GodotAgentBridge(config).capabilities()

    assert evidence.is_dir()
    assert engine.is_dir()
    assert capabilities["evidenceRoot"] == str(evidence.resolve())
    assert capabilities["engineRoot"] == str(engine.resolve())
    assert any(
        "outside all source roots" in boundary
        for boundary in capabilities["truthBoundaries"]
    )


def test_lab_repository_cannot_be_selected_as_target(tmp_path: Path) -> None:
    estate = tmp_path / "estate"
    lab = estate / "godot-game-test-lab"
    _git_repo(lab)
    bridge = GodotAgentBridge(
        BridgeConfig.from_environment(
            lab_root=lab,
            allowed_target_roots=[estate],
            evidence_root=tmp_path / "evidence",
            engine_root=tmp_path / "engine",
            require_interactive_desktop=False,
            auto_provision_engines=False,
        )
    )

    with pytest.raises(NativeQaError, match="disjoint from the Lab"):
        bridge.target_record(str(lab))
