from __future__ import annotations

from pathlib import Path

from godot_game_test_lab.linux_sandbox import prepare_ephemeral_copy


def test_ephemeral_copy_skips_unreadable_transient_tool_caches(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "project.godot").write_text(
        '[application]\nconfig/name="Fixture"\n',
        encoding="utf-8",
    )
    (source / "keep.txt").write_text("keep", encoding="utf-8")

    transient_directories = (
        ".mypy_cache",
        ".nox",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        "__pycache__",
    )
    for name in transient_directories:
        directory = source / name
        directory.mkdir()
        (directory / "ignored.txt").write_text("ignored", encoding="utf-8")

    unreadable = source / ".ruff_cache" / "private-cache-entry"
    unreadable.write_text("private", encoding="utf-8")
    unreadable.chmod(0)
    (source / "stale.pyc").write_bytes(b"compiled")
    egg_info = source / "fixture.egg-info"
    egg_info.mkdir()
    (egg_info / "PKG-INFO").write_text("generated", encoding="utf-8")

    destination = prepare_ephemeral_copy(source, tmp_path / "work")

    assert (destination / "keep.txt").read_text(encoding="utf-8") == "keep"
    for name in transient_directories:
        assert not (destination / name).exists()
    assert not (destination / "stale.pyc").exists()
    assert not (destination / "fixture.egg-info").exists()
