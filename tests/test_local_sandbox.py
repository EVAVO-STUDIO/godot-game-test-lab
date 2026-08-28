from __future__ import annotations

from pathlib import Path

import pytest

from godot_game_test_lab.local_sandbox import (
    SandboxError,
    SandboxProfile,
    _docker_run_command,
    _resolve_external_artifacts,
    _safe_mount_path,
    _select_sandbox_engine_version,
)


def _profile(tmp_path: Path) -> SandboxProfile:
    return SandboxProfile(
        source_path=str(tmp_path / "profile.json"),
        normalized_path=str(tmp_path / "normalized.json"),
        schema_version="2.0",
        project_subpath="game",
        minimum_godot_version="4.6.2",
        engine_version="4.6.3",
        engine_flavor="standard",
        visual_scene="res://main.tscn",
        visual_frames=180,
        visual_fps=30,
        visual_width=1280,
        visual_height=720,
        rendering_method="gl_compatibility",
        visual_arguments_json="[]",
        export_preset="",
    )


def test_sandbox_uses_governed_maintenance_release() -> None:
    assert _select_sandbox_engine_version("4.6.2") == "4.6.3"
    assert _select_sandbox_engine_version("4.7.0") == "4.7.2"
    with pytest.raises(SandboxError, match="unmapped Godot branch 4.8"):
        _select_sandbox_engine_version("4.8.0")
    with pytest.raises(SandboxError, match="older than the profile minimum"):
        _select_sandbox_engine_version("4.6.4")


def test_docker_mount_paths_reject_ambiguous_delimiters(tmp_path: Path) -> None:
    with pytest.raises(SandboxError, match="unsupported by Docker --mount"):
        _safe_mount_path(tmp_path / "comma,path", "fixture")


def test_artifacts_must_remain_beneath_allowed_root(tmp_path: Path) -> None:
    lab = tmp_path / "lab"
    target = tmp_path / "target"
    allowed = tmp_path / "evidence"
    for path in (lab, target, allowed):
        path.mkdir()

    accepted = _resolve_external_artifacts(
        allowed / "run",
        lab_root=lab,
        target_root=target,
        allowed_root=allowed,
    )
    assert accepted == (allowed / "run").resolve()

    with pytest.raises(SandboxError, match="beneath the allowed root"):
        _resolve_external_artifacts(
            tmp_path / "outside" / "run",
            lab_root=lab,
            target_root=target,
            allowed_root=allowed,
        )


def test_docker_run_command_is_no_network_read_only_and_bounded(tmp_path: Path) -> None:
    target = tmp_path / "target"
    profile = tmp_path / "normalized.json"
    work = tmp_path / "work"
    artifacts = tmp_path / "artifacts"
    for path in (target, work, artifacts):
        path.mkdir()
    profile.write_text("{}\n", encoding="utf-8")

    command = _docker_run_command(
        docker="docker",
        container_name="evavo-fixture",
        image="evavo-godot-lab:fixture",
        target=target,
        normalized_profile=profile,
        work_root=work,
        artifacts=artifacts,
        target_name="game",
        target_sha="a" * 40,
        lab_sha="b" * 40,
        profile=_profile(tmp_path),
        timeout_seconds=600,
        boot_frames=30,
        cpus=4.0,
        memory="10g",
        memory_swap="10g",
        pids_limit=1024,
        nofile_limit=4096,
        shm_size="1g",
    )

    joined = " ".join(command)
    assert "--network none" in joined
    assert "--user 10001:10001" in joined
    assert "--ipc private" in joined
    assert "--ulimit core=0" in joined
    assert "--read-only" in command
    assert "--cap-drop ALL" in joined
    assert "--security-opt no-new-privileges" in joined
    assert "--pids-limit 1024" in joined
    assert "--memory 10g" in joined
    assert "EVAVO_TIMEOUT_SECONDS=600" in joined
    assert "EVAVO_BOOT_FRAMES=30" in joined
    assert "target=/workspace/source,readonly" in joined
    assert "target=/workspace/profile.normalized.json,readonly" in joined
    assert "docker.sock" not in joined
    assert "--privileged" not in command
    assert "--device" not in command


def test_process_output_is_bounded_without_pipe_buffering(tmp_path: Path) -> None:
    import sys

    from godot_game_test_lab.local_sandbox import _run_process

    receipt = _run_process(
        [
            sys.executable,
            "-c",
            "import sys; sys.stdout.write('A' * 5000); sys.stderr.write('B' * 5000)",
        ],
        cwd=tmp_path,
        timeout_seconds=30,
        maximum_output_bytes=1024,
    )

    assert receipt.exit_code == 0
    assert "byte(s) omitted" in receipt.stdout
    assert "byte(s) omitted" in receipt.stderr
    assert len(receipt.stdout.encode()) < 1200
    assert len(receipt.stderr.encode()) < 1200


def test_relative_artifacts_are_resolved_beneath_allowed_root(tmp_path: Path) -> None:
    lab = tmp_path / "lab"
    target = tmp_path / "target"
    allowed = tmp_path / "evidence"
    for path in (lab, target, allowed):
        path.mkdir()

    accepted = _resolve_external_artifacts(
        Path("game/run-001"),
        lab_root=lab,
        target_root=target,
        allowed_root=allowed,
    )

    assert accepted == (allowed / "game" / "run-001").resolve()


def test_docker_image_identity_labels_are_exact() -> None:
    from godot_game_test_lab.local_sandbox import (
        _expected_image_labels,
        _image_labels_match,
    )

    expected = _expected_image_labels("4.6.3", "standard", "a" * 40)
    metadata = {"Id": "sha256:fixture", "Config": {"Labels": dict(expected)}}

    assert _image_labels_match(metadata, expected)
    metadata["Config"]["Labels"]["org.evavo.lab.sha"] = "b" * 40
    assert not _image_labels_match(metadata, expected)
