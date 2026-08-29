from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Final, Iterable

from .native_qa_common import NativeQaError

_REPOSITORY_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
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


def _source_identity(paths: Iterable[str]) -> str:
    digest = hashlib.sha256()
    for relative_path in sorted(paths):
        if (
            not relative_path
            or "\\" in relative_path
            or relative_path.startswith("/")
            or any(part in {"", ".", ".."} for part in relative_path.split("/"))
        ):
            raise NativeQaError(
                f"movie provider source path is not canonical: {relative_path}"
            )
        requested = _REPOSITORY_ROOT.joinpath(*relative_path.split("/"))
        actual = requested.resolve(strict=True)
        try:
            canonical = actual.relative_to(_REPOSITORY_ROOT).as_posix()
        except ValueError as error:
            raise NativeQaError(
                f"movie provider source path escapes the repository: {relative_path}"
            ) from error
        if canonical != relative_path or actual.is_symlink() or not actual.is_file():
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
