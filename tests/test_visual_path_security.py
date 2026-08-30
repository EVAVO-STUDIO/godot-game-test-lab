from __future__ import annotations

import os
from pathlib import Path

import pytest

from godot_game_test_lab.native_qa_common import NativeQaError
from godot_game_test_lab.visual_path_security import (
    canonical_non_link_directory,
    confined_output_file,
    confined_regular_file,
    is_link_or_reparse,
)


def test_confined_file_and_direct_root_output_are_supported(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    evidence = root / "movie.avi"
    evidence.write_bytes(b"evidence")
    actual, relative, size = confined_regular_file(
        root,
        Path("movie.avi"),
        label="movie",
        maximum_bytes=1024,
    )
    assert actual == evidence.resolve()
    assert relative == "movie.avi"
    assert size == len(b"evidence")

    output, output_relative = confined_output_file(
        root,
        Path("receipt.json"),
        label="receipt",
        required_suffix=".json",
    )
    assert output == root.resolve() / "receipt.json"
    assert output_relative == "receipt.json"
    assert not output.exists()


def test_confinement_rejects_escape_and_existing_output(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"outside")
    with pytest.raises(NativeQaError, match="escapes"):
        confined_regular_file(
            root,
            outside,
            label="evidence",
            maximum_bytes=1024,
        )

    existing = root / "receipt.json"
    existing.write_text("{}\n", encoding="utf-8")
    with pytest.raises(NativeQaError, match="overwrite"):
        confined_output_file(root, existing, label="receipt")


def test_confinement_rejects_non_directory_parent_components(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    blocker = root / "not-a-directory"
    blocker.write_text("blocked", encoding="utf-8")
    with pytest.raises(NativeQaError, match="non-directory"):
        confined_output_file(
            root,
            blocker / "receipt.json",
            label="receipt",
        )


def _symlink_or_skip(
    context: pytest.FixtureRequest,
    target: Path,
    alias: Path,
    *,
    directory: bool,
) -> None:
    try:
        alias.symlink_to(target, target_is_directory=directory)
    except OSError as error:
        pytest.skip(f"symbolic links are unavailable in this environment: {error}")
    if not is_link_or_reparse(alias):
        pytest.skip("the platform did not expose the test link as a link or reparse point")


def test_confined_reads_reject_a_linked_leaf(
    tmp_path: Path,
    request: pytest.FixtureRequest,
) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    target = root / "target.bin"
    target.write_bytes(b"target")
    alias = root / "alias.bin"
    _symlink_or_skip(request, target, alias, directory=False)
    with pytest.raises(NativeQaError, match="symbolic links|reparse points"):
        confined_regular_file(
            root,
            alias,
            label="evidence",
            maximum_bytes=1024,
        )


def test_confined_reads_and_outputs_reject_a_linked_parent(
    tmp_path: Path,
    request: pytest.FixtureRequest,
) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "evidence.bin").write_bytes(b"outside")
    alias = root / "linked"
    _symlink_or_skip(request, outside, alias, directory=True)

    with pytest.raises(NativeQaError, match="symbolic links|reparse points"):
        confined_regular_file(
            root,
            alias / "evidence.bin",
            label="evidence",
            maximum_bytes=1024,
        )
    with pytest.raises(NativeQaError, match="symbolic links|reparse points"):
        confined_output_file(
            root,
            alias / "receipt.json",
            label="receipt",
        )


def test_artifact_root_may_not_itself_be_a_link(
    tmp_path: Path,
    request: pytest.FixtureRequest,
) -> None:
    target = tmp_path / "target-root"
    target.mkdir()
    alias = tmp_path / "root-alias"
    _symlink_or_skip(request, target, alias, directory=True)
    with pytest.raises(NativeQaError, match="may not itself be"):
        canonical_non_link_directory(alias, label="artifact root")


def test_dangling_link_cannot_be_reused_as_an_output(
    tmp_path: Path,
    request: pytest.FixtureRequest,
) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    alias = root / "receipt.json"
    missing = root / "missing.json"
    _symlink_or_skip(request, missing, alias, directory=False)
    assert os.path.lexists(alias)
    with pytest.raises(NativeQaError, match="overwrite"):
        confined_output_file(root, alias, label="receipt")
