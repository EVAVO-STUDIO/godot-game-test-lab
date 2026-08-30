from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Final, Iterable

from .native_qa_common import NativeQaError
from .visual_path_security import (
    canonical_non_link_directory,
    is_link_or_reparse,
    lexical_absolute,
    reject_link_components,
    relative_inside,
)

_LOGICAL_PACKAGE_PREFIX: Final[str] = "src/godot_game_test_lab/"
_PACKAGE_ROOT_REQUESTED: Final[Path] = lexical_absolute(Path(__file__).absolute().parent)
_PACKAGE_ROOT: Final[Path] = _PACKAGE_ROOT_REQUESTED.resolve(strict=True)
_CAPTURE_SOURCE_PATHS: Final[tuple[str, ...]] = (
    "src/godot_game_test_lab/movie_evidence.py",
    "src/godot_game_test_lab/movie_evidence_cli.py",
    "src/godot_game_test_lab/movie_source_identity.py",
    "src/godot_game_test_lab/visual_path_security.py",
)
_TEMPORAL_SOURCE_PATHS: Final[tuple[str, ...]] = (
    "src/godot_game_test_lab/movie_evidence.py",
    "src/godot_game_test_lab/movie_temporal.py",
    "src/godot_game_test_lab/movie_temporal_cli.py",
    "src/godot_game_test_lab/movie_source_identity.py",
    "src/godot_game_test_lab/visual_path_security.py",
)


def _ensure_source_root() -> tuple[Path, Path]:
    requested, actual = canonical_non_link_directory(
        _PACKAGE_ROOT_REQUESTED,
        label="movie provider package root",
    )
    if requested != _PACKAGE_ROOT_REQUESTED or actual != _PACKAGE_ROOT:
        raise NativeQaError("movie provider package root changed after import")
    return requested, actual


def _canonical_source_paths(paths: Iterable[str]) -> tuple[str, ...]:
    values = tuple(paths)
    if len(values) == 0:
        raise NativeQaError("movie provider source path list may not be empty")
    if len(values) > 256:
        raise NativeQaError("movie provider source path list is outside policy")
    if len(set(values)) != len(values):
        raise NativeQaError("movie provider source path list contains duplicates")
    for relative_path in values:
        if (
            not isinstance(relative_path, str)
            or not relative_path
            or len(relative_path) > 1024
            or "\\" in relative_path
            or relative_path.startswith("/")
            or any(part in {"", ".", ".."} for part in relative_path.split("/"))
            or not relative_path.startswith(_LOGICAL_PACKAGE_PREFIX)
        ):
            raise NativeQaError(
                f"movie provider source path is not canonical: {relative_path}"
            )
        package_relative = relative_path.removeprefix(_LOGICAL_PACKAGE_PREFIX)
        if not package_relative or "/" in package_relative:
            raise NativeQaError(
                f"movie provider source path is not a package file: {relative_path}"
            )
    return tuple(sorted(values))


def _package_relative_path(logical_path: str) -> str:
    return logical_path.removeprefix(_LOGICAL_PACKAGE_PREFIX)


def _source_identity(paths: Iterable[str]) -> str:
    requested_root, actual_root = _ensure_source_root()
    digest = hashlib.sha256()
    for logical_path in _canonical_source_paths(paths):
        package_relative = _package_relative_path(logical_path)
        requested = requested_root / package_relative
        expected_relative = relative_inside(
            requested_root,
            requested,
            label="movie provider package source path",
        )
        if expected_relative != package_relative:
            raise NativeQaError(
                f"movie provider source path is not canonical: {logical_path}"
            )
        reject_link_components(
            requested_root,
            requested,
            label=f"movie provider source path {logical_path}",
        )
        if is_link_or_reparse(requested):
            raise NativeQaError(
                f"movie provider source path may not be a link: {logical_path}"
            )
        try:
            actual = requested.resolve(strict=True)
        except OSError as error:
            raise NativeQaError(
                f"movie provider source file is missing: {logical_path}"
            ) from error
        try:
            canonical = actual.relative_to(actual_root).as_posix()
        except ValueError as error:
            raise NativeQaError(
                f"movie provider source path escapes the package: {logical_path}"
            ) from error
        if canonical != package_relative or not actual.is_file():
            raise NativeQaError(
                f"movie provider source path is not an admitted regular file: {logical_path}"
            )
        digest.update(logical_path.encode("utf-8"))
        digest.update(b"\0")
        with actual.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def capture_movie_source_identity() -> str:
    return _source_identity(_CAPTURE_SOURCE_PATHS)


def temporal_movie_source_identity() -> str:
    return _source_identity(_TEMPORAL_SOURCE_PATHS)


def movie_source_identities() -> dict[str, str]:
    return {
        "godot-game-test-lab.video-evidence": capture_movie_source_identity(),
        "godot-game-test-lab.movie-temporal": temporal_movie_source_identity(),
    }


CAPTURE_MOVIE_SOURCE_PATHS = _CAPTURE_SOURCE_PATHS
TEMPORAL_MOVIE_SOURCE_PATHS = _TEMPORAL_SOURCE_PATHS
MOVIE_SOURCE_REPOSITORY_ROOT = _PACKAGE_ROOT
MOVIE_SOURCE_REPOSITORY_ROOT_REQUESTED = _PACKAGE_ROOT_REQUESTED
