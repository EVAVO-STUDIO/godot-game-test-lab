from __future__ import annotations

import json
from pathlib import Path

import pytest

from godot_game_test_lab.native_qa import (
    NativeQaError,
    _safe_relative_path,
    normalize_profile,
)


def base_profile() -> dict:
    return {
        "schemaVersion": "1.0",
        "journeys": [
            {
                "id": "main-menu",
                "scene": "res://main.tscn",
                "steps": [{"type": "wait", "frames": 2}],
            }
        ],
    }


def test_profile_normalization_is_bounded_and_explicit() -> None:
    value = normalize_profile(base_profile())
    journey = value["journeys"][0]
    ux = journey["ux"]
    assert value["schemaVersion"] == "2.0"
    assert journey["required"] is True
    assert journey["fps"] == 30
    assert journey["width"] == 1280
    assert journey["renderingMethod"] == "forward_plus"
    assert journey["renderingDriver"] == "vulkan"
    assert journey["estimatedFrames"] == 34
    assert ux["captureControlTree"] is True
    assert ux["captureUiAtCheckpoints"] is True
    assert ux["failOnBlackFrame"] is False
    assert ux["failOnTruncatedLayoutAnalysis"] is False
    assert ux["minimumInteractiveGap"] == 8.0
    assert ux["maximumAncestorClippedInteractive"] == 0
    assert ux["maximumOccludedInteractive"] == 0
    assert ux["maximumCloseInteractivePairs"] == 32
    assert ux["maximumPairChecks"] == 50_000


def test_profile_accepts_semantic_layout_governance() -> None:
    profile = base_profile()
    profile["journeys"][0]["ux"] = {
        "captureUiAtCheckpoints": False,
        "failOnTruncatedLayoutAnalysis": True,
        "minimumInteractiveGap": 12.5,
        "maximumAncestorClippedInteractive": 2,
        "maximumOccludedInteractive": 3,
        "maximumCloseInteractivePairs": 4,
        "maximumPairChecks": 1_024,
    }

    ux = normalize_profile(profile)["journeys"][0]["ux"]

    assert ux["captureUiAtCheckpoints"] is False
    assert ux["failOnTruncatedLayoutAnalysis"] is True
    assert ux["minimumInteractiveGap"] == 12.5
    assert ux["maximumAncestorClippedInteractive"] == 2
    assert ux["maximumOccludedInteractive"] == 3
    assert ux["maximumCloseInteractivePairs"] == 4
    assert ux["maximumPairChecks"] == 1_024


def test_profile_rejects_unbounded_semantic_layout_governance() -> None:
    cases = (
        ("minimumInteractiveGap", -0.1),
        ("maximumAncestorClippedInteractive", 193),
        ("maximumOccludedInteractive", 193),
        ("maximumCloseInteractivePairs", 1_025),
        ("maximumPairChecks", 50_001),
        ("captureUiAtCheckpoints", "yes"),
        ("failOnTruncatedLayoutAnalysis", 1),
    )
    for key, invalid in cases:
        profile = base_profile()
        profile["journeys"][0]["ux"] = {key: invalid}
        with pytest.raises(NativeQaError, match=key):
            normalize_profile(profile)


def test_profile_rejects_duplicate_journeys_and_lifecycle_arguments() -> None:
    profile = base_profile()
    profile["journeys"].append(dict(profile["journeys"][0]))
    with pytest.raises(NativeQaError, match="duplicated"):
        normalize_profile(profile)

    profile = base_profile()
    profile["journeys"][0]["userArguments"] = ["--path=C:/escape"]
    with pytest.raises(NativeQaError, match="worker-owned"):
        normalize_profile(profile)


def test_profile_rejects_incompatible_renderer_driver() -> None:
    profile = base_profile()
    profile["journeys"][0].update(
        {"renderingMethod": "forward_plus", "renderingDriver": "opengl3"}
    )
    with pytest.raises(NativeQaError, match="vulkan or d3d12"):
        normalize_profile(profile)


def test_project_subpath_rejects_absolute_and_traversal() -> None:
    assert _safe_relative_path("games/demo", "project_subpath") == Path("games/demo")
    assert _safe_relative_path(".", "project_subpath") == Path(".")
    for value in ("../demo", "C:/demo", "/demo", "games/../demo"):
        with pytest.raises(NativeQaError):
            _safe_relative_path(value, "project_subpath")


def test_profile_json_examples_remain_standard_json() -> None:
    encoded = json.dumps(base_profile(), allow_nan=False)
    assert json.loads(encoded)["journeys"][0]["id"] == "main-menu"


def test_strict_profile_loader_rejects_duplicate_and_non_finite_json(tmp_path: Path) -> None:
    from godot_game_test_lab.native_qa import _load_json_object

    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text(
        '{"schemaVersion":"1.0","schemaVersion":"2.0"}', encoding="utf-8"
    )
    with pytest.raises(NativeQaError, match="Duplicate JSON key"):
        _load_json_object(duplicate, "profile")

    non_finite = tmp_path / "non-finite.json"
    non_finite.write_text('{"value":NaN}', encoding="utf-8")
    with pytest.raises(NativeQaError, match="Non-finite"):
        _load_json_object(non_finite, "profile")


def test_exact_git_archive_copy_is_link_free_and_bounded(tmp_path: Path) -> None:
    import subprocess

    from godot_game_test_lab.native_qa import _archive_checkout

    source = tmp_path / "source"
    source.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=source, check=True)
    subprocess.run(["git", "config", "user.name", "Fixture"], cwd=source, check=True)
    subprocess.run(
        ["git", "config", "user.email", "fixture@example.com"],
        cwd=source,
        check=True,
    )
    (source / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    (source / "main.tscn").write_text(
        '[gd_scene format=3]\n[node name="Main" type="Node"]\n', encoding="utf-8"
    )
    subprocess.run(["git", "add", "."], cwd=source, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "fixture"], cwd=source, check=True)
    sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=source, text=True
    ).strip()

    destination = tmp_path / "work" / "repository"
    receipt = _archive_checkout(source, sha, destination, 30)

    assert receipt["files"] == 2
    assert receipt["bytes"] > 0
    assert (destination / "project.godot").is_file()
    assert (destination / "main.tscn").is_file()
    assert not any(path.is_symlink() for path in destination.rglob("*"))


def test_artifact_inventory_excludes_work_copy_and_self_hash(tmp_path: Path) -> None:
    from godot_game_test_lab.native_qa import _artifact_inventory

    (tmp_path / "work").mkdir()
    (tmp_path / "work" / "source.txt").write_text("source", encoding="utf-8")
    (tmp_path / "evidence.txt").write_text("evidence", encoding="utf-8")
    (tmp_path / "native-agent-summary.json").write_text("{}\n", encoding="utf-8")

    records = _artifact_inventory(tmp_path)

    assert [record["path"] for record in records] == ["evidence.txt"]
    assert len(records[0]["sha256"]) == 64
