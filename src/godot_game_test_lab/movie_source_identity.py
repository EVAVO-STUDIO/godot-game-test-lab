from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Final, Iterable

from .native_qa_common import NativeQaError

_REPOSITORY_ROOT_REQUESTED: Final[Path] = Path(
    os.path.abspath(os.fspath(Path(__file__).absolute().parents[2]))
)
_REPOSITORY_ROOT: Final[Path] = _REPOSITORY_ROOT_REQUESTED.resolve(strict=True)
_CAPTURE_SOURCE_PATHS: Final[tuple[str, ...]] = (
    "src/godot_game_test_lab/movie_evidence.py",
    "src/godot_game_test_lab/movie_evidence_cli.py",
    "src/godot_game_test_lab/movie_source_identity.py",
)
_TEMPORAL_SOURCE_PATHS: Final[tuple[str, ...]] = (
    "src/godot_game_test_lab/movie_evidence.py",
    "src/godot_game_test_lab/movie_temporal.py",
    "src/godot_game_test_lab/movie_temporal_cli.py",
    "src/godot_game_test_lab/movie_source_identity.py",
)


def _ensure_source_root() -> None:
    if (
        _REPOSITORY_ROOT_REQUESTED.is_symlink()
        or not _REPOSITORY_ROOT_REQUESTED.is_dir()
        or _REPOSITORY_ROOT_REQUESTED != _REPOSITORY_ROOT
    ):
        raise NativeQaError(
            "movie provider repository root must be a canonical non-symlink directory"
        )


def _relative_inside(root: Path, candidate: Path, *, label: str) -> str:
    try:
        relative = candidate.relative_to(root)
    except ValueError as error:
        raise NativeQaError(f"{label} escapes the repository root") from error
    if relative == Path("."):
        raise NativeQaError(f"{label} may not be the repository root itself")
    return relative.as_posix()


def _reject_symlink_components(root: Path, candidate: Path, *, label: str) -> None:
    relative = Path(_relative_inside(root, candidate, label=label))
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise NativeQaError(f"{label} may not traverse symbolic links")


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
        ):
            raise NativeQaError(
                f"movie provider source path is not canonical: {relative_path}"
            )
    return tuple(sorted(values))


def _source_identity(paths: Iterable[str]) -> str:
    _ensure_source_root()
    digest = hashlib.sha256()
    for relative_path in _canonical_source_paths(paths):
        requested = _REPOSITORY_ROOT_REQUESTED.joinpath(*relative_path.split("/"))
        _relative_inside(
            _REPOSITORY_ROOT_REQUESTED,
            requested,
            label="movie provider source path",
        )
        _reject_symlink_components(
            _REPOSITORY_ROOT_REQUESTED,
            requested,
            label=f"movie provider source path {relative_path}",
        )
        actual = requested.resolve(strict=True)
        try:
            canonical = actual.relative_to(_REPOSITORY_ROOT).as_posix()
        except ValueError as error:
            raise NativeQaError(
                f"movie provider source path escapes the repository: {relative_path}"
            ) from error
        if canonical != relative_path or not actual.is_file():
            raise NativeQaError(
                f"movie provider source path is not an admitted regular file: {relative_path}"
            )
        digest.update(relative_path.encode("utf-8"))
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
MOVIE_SOURCE_REPOSITORY_ROOT = _REPOSITORY_ROOT
MOVIE_SOURCE_REPOSITORY_ROOT_REQUESTED = _REPOSITORY_ROOT_REQUESTED
