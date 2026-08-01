from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from godot_game_test_lab.native_qa import (
    NativeQaError,
    _archive_checkout,
    _load_json_object,
    normalize_profile,
)
from godot_game_test_lab.native_qa_common import (
    _directory_usage,
    _native_desktop_lease,
    _require_clean_checkout,
    _run_process,
)
from godot_game_test_lab.native_qa_evidence import (
    _artifact_inventory,
    _parse_black_segments,
    _parse_freeze_segments,
)


def base_profile() -> dict:
    return {
        "schemaVersion": "2.0",
        "journeys": [
            {
                "id": "main-menu",
                "scene": "res://main.tscn",
                "device": "keyboard_mouse",
                "requiredActions": [
                    {"name": "ui_accept", "devices": ["keyboard"]}
                ],
                "steps": [
                    {"type": "wait", "frames": 2},
                    {"type": "checkpoint", "id": "menu-ready"},
                ],
                "assertions": [{"type": "scene_loaded"}],
            }
        ],
    }


def init_repo(root: Path) -> str:
    root.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Fixture"], cwd=root, check=True)
    subprocess.run(
        ["git", "config", "user.email", "fixture@example.com"], cwd=root, check=True
    )
    (root / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    (root / "main.tscn").write_text(
        '[gd_scene format=3]\n[node name="Main" type="Node"]\n', encoding="utf-8"
    )
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "fixture"], cwd=root, check=True)
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()


def test_profile_is_strict_and_normalizes_to_schema_two() -> None:
    value = normalize_profile(base_profile())
    journey = value["journeys"][0]
    assert value["schemaVersion"] == "2.0"
    assert journey["pixelFrames"] == 1280 * 720 * 900
    assert journey["requiredActions"][0]["devices"] == ["keyboard"]
    assert journey["ux"]["failOnBlackFrame"] is False


def test_profile_rejects_unknown_fields_type_confusion_and_checkpoint_escape() -> None:
    profile = base_profile()
    profile["unexpected"] = True
    with pytest.raises(NativeQaError, match="unsupported fields"):
        normalize_profile(profile)

    profile = base_profile()
    profile["journeys"][0]["renderingMethod"] = []
    with pytest.raises(NativeQaError, match="renderingMethod"):
        normalize_profile(profile)

    profile = base_profile()
    profile["journeys"][0]["steps"][1]["id"] = "../escape"
    with pytest.raises(NativeQaError, match="checkpoint"):
        normalize_profile(profile)


def test_profile_rejects_unbounded_movie_and_worker_arguments() -> None:
    profile = base_profile()
    profile["journeys"][0].update(
        {"width": 3840, "height": 2160, "maxFrames": 7200, "fps": 60}
    )
    with pytest.raises(NativeQaError, match="resolution-by-frame"):
        normalize_profile(profile)

    profile = base_profile()
    profile["journeys"][0]["userArguments"] = ["--write-movie=escape.avi"]
    with pytest.raises(NativeQaError, match="worker-owned"):
        normalize_profile(profile)



def test_profile_rejects_duplicate_actions_checkpoints_and_frame_overflow() -> None:
    profile = base_profile()
    profile["journeys"][0]["requiredActions"].append(
        {"name": "ui_accept", "devices": ["keyboard"]}
    )
    with pytest.raises(NativeQaError, match="duplicate action"):
        normalize_profile(profile)

    profile = base_profile()
    profile["journeys"][0]["steps"].append(
        {"type": "checkpoint", "id": "menu-ready"}
    )
    with pytest.raises(NativeQaError, match="duplicate checkpoint"):
        normalize_profile(profile)

    profile = base_profile()
    profile["journeys"][0].update(
        {"settleFrames": 29, "maxFrames": 30, "steps": [{"type": "wait", "frames": 5}]}
    )
    with pytest.raises(NativeQaError, match="maxFrames"):
        normalize_profile(profile)

def test_json_loader_rejects_oversized_duplicate_and_non_finite_content(
    tmp_path: Path,
) -> None:
    path = tmp_path / "profile.json"
    path.write_text('{"value":1,"value":2}', encoding="utf-8")
    with pytest.raises(NativeQaError, match="Duplicate JSON key"):
        _load_json_object(path, "profile")

    path.write_text('{"value":NaN}', encoding="utf-8")
    with pytest.raises(NativeQaError, match="Non-finite"):
        _load_json_object(path, "profile")

    path.write_text(json.dumps({"value": "x" * 2048}), encoding="utf-8")
    with pytest.raises(NativeQaError, match="size limit"):
        _load_json_object(path, "profile", maximum_bytes=128)


def test_exact_checkout_requires_clean_source_and_rejects_gitlinks(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    init_repo(repo)
    _require_clean_checkout(repo, "fixture")

    (repo / "dirty.txt").write_text("dirty", encoding="utf-8")
    with pytest.raises(NativeQaError, match="must be clean"):
        _require_clean_checkout(repo, "fixture")
    (repo / "dirty.txt").unlink()

    child = tmp_path / "child"
    init_repo(child)
    subprocess.run(
        [
            "git",
            "-c",
            "protocol.file.allow=always",
            "submodule",
            "add",
            "-q",
            str(child),
            "vendor/child",
        ],
        cwd=repo,
        check=True,
    )
    subprocess.run(["git", "commit", "-q", "-am", "submodule"], cwd=repo, check=True)
    with pytest.raises(NativeQaError, match="submodules"):
        _require_clean_checkout(repo, "fixture")


def test_process_output_is_bounded_while_process_runs(tmp_path: Path) -> None:
    result = _run_process(
        [
            sys.executable,
            "-c",
            "import sys; sys.stdout.write('A'*200000); sys.stderr.write('B'*200000)",
        ],
        tmp_path,
        30,
        maximum_output_bytes=4096,
    )
    assert result["exitCode"] == 0
    assert "output truncated" in result["stdout"]
    assert "output truncated" in result["stderr"]
    assert len(result["stdout"]) < 5000


def test_process_is_terminated_when_artifact_budget_is_exceeded(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    script = (
        "import pathlib,time; p=pathlib.Path('artifacts/growing.bin'); "
        "p.write_bytes(b'x'*2000000); time.sleep(30)"
    )
    result = _run_process(
        [sys.executable, "-c", script],
        tmp_path,
        30,
        artifact_budget_root=artifacts,
        maximum_artifact_bytes=1024,
    )
    assert result["artifactBudgetExceeded"] is True
    assert result["exitCode"] is None


def test_archive_is_exact_link_free_and_reports_size(tmp_path: Path) -> None:
    source = tmp_path / "source"
    sha = init_repo(source)
    destination = tmp_path / "work" / "repository"
    receipt = _archive_checkout(source, sha, destination, 30)
    assert receipt["files"] == 2
    assert receipt["bytes"] > 0
    assert (destination / "project.godot").is_file()
    assert not any(path.is_symlink() for path in destination.rglob("*"))


def test_video_diagnostics_are_structured() -> None:
    black = _parse_black_segments(
        "[blackdetect] black_start:1.25 black_end:4.75 black_duration:3.5"
    )
    freeze = _parse_freeze_segments(
        "freeze_start: 2.0\nfreeze_end: 8.0 | freeze_duration: 6.0"
    )
    assert black == [
        {"startSeconds": 1.25, "endSeconds": 4.75, "durationSeconds": 3.5}
    ]
    assert freeze[0]["durationSeconds"] == 6.0


def test_artifact_inventory_rejects_symlinks_and_byte_overflow(tmp_path: Path) -> None:
    (tmp_path / "evidence.txt").write_text("evidence", encoding="utf-8")
    records = _artifact_inventory(tmp_path, maximum_total_bytes=64)
    assert records[0]["path"] == "evidence.txt"

    with pytest.raises(NativeQaError, match="byte limit"):
        _artifact_inventory(tmp_path, maximum_total_bytes=1)

    if hasattr(os, "symlink"):
        link = tmp_path / "link.txt"
        try:
            link.symlink_to(tmp_path / "evidence.txt")
        except OSError:
            return
        with pytest.raises(NativeQaError, match="symbolic link"):
            _artifact_inventory(tmp_path)


def test_directory_usage_and_non_windows_desktop_lease_are_bounded(tmp_path: Path) -> None:
    (tmp_path / "a").write_bytes(b"123")
    assert _directory_usage(tmp_path) == (3, 1, True)
    if os.name != "nt":
        with _native_desktop_lease() as lease:
            assert lease["acquired"] is False


def test_profile_schema_example_and_normalizer_agree() -> None:
    root = Path(__file__).resolve().parents[1]
    schema = json.loads(
        (root / "schemas" / "native-agent-qa-profile.schema.json").read_text(
            encoding="utf-8"
        )
    )
    example = json.loads(
        (root / "examples" / "native-agent-qa.profile.json").read_text(
            encoding="utf-8"
        )
    )
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["properties"]["journeys"]["maxItems"] == 16
    assert schema["$defs"]["journey"]["additionalProperties"] is False
    assert schema["$defs"]["ux"]["properties"]["failOnBlackFrame"]["default"] is False
    normalized = normalize_profile(example)
    assert normalized["schemaVersion"] == "2.0"
    assert normalized["journeys"][0]["id"] == "main-menu-keyboard"


def test_native_wrapper_exposes_budgets_and_interactive_session_guard() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "scripts" / "Invoke-GodotLabNativeAgentQA.ps1").read_text(
        encoding="utf-8"
    )
    for token in (
        "[int]$MaxTotalSeconds = 3600",
        "[int]$MaxArtifactGiB = 20",
        "--max-total-seconds",
        "--max-artifact-bytes",
        "Get-Process -Name explorer",
        "Session 0 service",
    ):
        assert token in source
