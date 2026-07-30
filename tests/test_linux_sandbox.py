from __future__ import annotations

from pathlib import Path

import pytest

from godot_game_test_lab.linux_sandbox import prepare_ephemeral_copy, safe_project_subpath


def test_safe_project_subpath_accepts_canonical_relative_path() -> None:
    assert safe_project_subpath("games/demo") == Path("games/demo")
    assert safe_project_subpath(".") == Path(".")


@pytest.mark.parametrize("value", ["../game", "/tmp/game", "C:\\game", "game/../other"])
def test_safe_project_subpath_rejects_escape(value: str) -> None:
    with pytest.raises(ValueError):
        safe_project_subpath(value)


def test_ephemeral_copy_excludes_generated_and_repository_metadata(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "project.godot").write_text(
        '[application]\nconfig/name="Fixture"\n', encoding="utf-8"
    )
    for excluded in [".git", ".godot", ".qa", ".cache", "artifacts"]:
        directory = source / excluded
        directory.mkdir()
        (directory / "ignored.txt").write_text("ignored", encoding="utf-8")
    (source / "keep.txt").write_text("keep", encoding="utf-8")

    destination = prepare_ephemeral_copy(source, tmp_path / "work")

    assert (destination / "keep.txt").read_text(encoding="utf-8") == "keep"
    for excluded in [".git", ".godot", ".qa", ".cache", "artifacts"]:
        assert not (destination / excluded).exists()


def test_ephemeral_copy_rejects_external_symlink(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    link = source / "outside-link"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable on this test platform")

    with pytest.raises(ValueError, match="symlink"):
        prepare_ephemeral_copy(source, tmp_path / "work")
