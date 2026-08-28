from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from godot_game_test_lab import sprite_animation_probe_runner as runner
from godot_game_test_lab.core import CommandResult
from godot_game_test_lab.game_asset_delivery_common import hash_object
from godot_game_test_lab.sprite_animation_runtime_admission import (
    AUTHORITY,
    EXPECTATION_SCHEMA,
)


def self_hash(value: dict, key: str) -> dict:
    result = json.loads(json.dumps(value))
    result[key] = hash_object(result)
    result["runId"] = result[key][:20]
    return result


def expectation() -> dict:
    return self_hash(
        {
            "schema": EXPECTATION_SCHEMA,
            "clipId": "walk-right",
            "animationDirectorPlanSha256": "a" * 64,
            "godotDescriptorSha256": "b" * 64,
            "frameIds": ["f1", "f2"],
            "frameDurationMicros": [125000, 125000],
            "framesPerSecond": 8,
            "loopMode": "linear",
            "maximumFrameTimingErrorMs": 20,
            "maximumPivotDriftPixels": 0,
            "authority": AUTHORITY,
        },
        "expectationSha256",
    )


def raw() -> dict:
    return {
        "status": "passed",
        "clipId": "walk-right",
        "godotVersion": "4.6.2.stable",
        "renderer": "gl_compatibility",
        "spriteFramesLoaded": True,
        "animationStarted": True,
        "configuredFramesPerSecond": 8,
        "loopMode": "linear",
        "completeCyclesObserved": 1,
        "frames": [
            {
                "frameId": "f1",
                "configuredDurationMicros": 125000,
                "observedDurationMs": 133,
                "pivot": {"x": 4, "y": 7},
                "rendered": True,
            },
            {
                "frameId": "f2",
                "configuredDurationMicros": 125000,
                "observedDurationMs": 133,
                "pivot": {"x": 4, "y": 7},
                "rendered": True,
            },
        ],
        "importErrors": [],
        "consoleErrors": [],
    }


def fixture(tmp_path: Path) -> tuple[Path, Path, str]:
    project = tmp_path / "game"
    project.mkdir()
    (project / "project.godot").write_text(
        '[application]\nconfig/name="Probe"\n',
        encoding="utf-8",
    )
    scene = project / "probe.tscn"
    scene.write_text('[gd_scene format=3]\n', encoding="utf-8")
    resource = project / "hero.tres"
    resource.write_text('[gd_resource format=3]\n[resource]\n', encoding="utf-8")
    expected = "a" * 40
    return project, tmp_path / "external", expected


def test_runner_binds_clean_target_and_restores_probe_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, external, expected_sha = fixture(tmp_path)
    expectation_path = external / "expectation.json"
    expectation_path.parent.mkdir(parents=True)
    expectation_path.write_text(json.dumps(expectation()), encoding="utf-8")

    monkeypatch.setattr(runner, "find_project_root", lambda _: project)
    monkeypatch.setattr(
        runner,
        "read_git_state",
        lambda _: SimpleNamespace(
            available=True,
            target_sha=expected_sha,
            dirty=False,
        ),
    )
    monkeypatch.setattr(
        runner,
        "discover_godot_binary",
        lambda *_args, **_kwargs: Path("C:/Godot/godot.exe"),
    )

    previous = "preserve-me"
    monkeypatch.setenv("EVAVO_SPRITE_ANIMATION_CLIP", previous)

    def fake_run(command, cwd, timeout):
        assert cwd == project
        assert timeout == 30
        assert os.environ["EVAVO_SPRITE_ANIMATION_RESOURCE"] == "res://hero.tres"
        assert os.environ["EVAVO_SPRITE_ANIMATION_CLIP"] == "walk-right"
        raw_path = Path(os.environ["EVAVO_SPRITE_ANIMATION_RAW_TELEMETRY"])
        raw_path.write_text(json.dumps(raw()), encoding="utf-8")
        return CommandResult(
            command=list(command),
            exit_code=0,
            duration_seconds=0.2,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(runner, "run_command", fake_run)
    result = runner.run_sprite_animation_probe(
        project=project,
        expected_target_sha=expected_sha,
        expectation_path=expectation_path,
        scene="res://probe.tscn",
        resource="res://hero.tres",
        clip="walk-right",
        raw_output=external / "raw.json",
        evidence_output=external / "evidence.json",
        report_output=external / "report.json",
    )
    assert result["status"] == "passed"
    assert result["targetSha"] == expected_sha
    assert os.environ["EVAVO_SPRITE_ANIMATION_CLIP"] == previous
    assert "EVAVO_SPRITE_ANIMATION_RESOURCE" not in os.environ
    assert (external / "evidence.json").is_file()
    assert (external / "report.json").is_file()


def test_runner_refuses_dirty_or_drifting_target_before_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, external, expected_sha = fixture(tmp_path)
    expectation_path = external / "expectation.json"
    expectation_path.parent.mkdir(parents=True)
    expectation_path.write_text(json.dumps(expectation()), encoding="utf-8")
    monkeypatch.setattr(runner, "find_project_root", lambda _: project)

    monkeypatch.setattr(
        runner,
        "read_git_state",
        lambda _: SimpleNamespace(
            available=True,
            target_sha=expected_sha,
            dirty=True,
        ),
    )
    with pytest.raises(ValueError, match="must be clean"):
        runner.run_sprite_animation_probe(
            project=project,
            expected_target_sha=expected_sha,
            expectation_path=expectation_path,
            scene="res://probe.tscn",
            resource="res://hero.tres",
            clip="walk-right",
            raw_output=external / "raw.json",
            evidence_output=external / "evidence.json",
            report_output=external / "report.json",
        )

    monkeypatch.setattr(
        runner,
        "read_git_state",
        lambda _: SimpleNamespace(
            available=True,
            target_sha="b" * 40,
            dirty=False,
        ),
    )
    with pytest.raises(ValueError, match="HEAD differs"):
        runner.run_sprite_animation_probe(
            project=project,
            expected_target_sha=expected_sha,
            expectation_path=expectation_path,
            scene="res://probe.tscn",
            resource="res://hero.tres",
            clip="walk-right",
            raw_output=external / "raw2.json",
            evidence_output=external / "evidence2.json",
            report_output=external / "report2.json",
        )
