from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from godot_game_test_lab.movie_evidence import (
    build_movie_adapter_receipt,
    command_digest,
    inject_movie_maker_arguments,
    validate_avi_movie,
    verify_movie_adapter_receipt,
)
from godot_game_test_lab.native_qa_common import NativeQaError


def avi_bytes(payload: bytes = b"frame-data") -> bytes:
    body = b"AVI " + b"LIST" + b"avih" + b"\0" * 32 + b"LIST" + b"movi" + payload
    return b"RIFF" + len(body).to_bytes(4, "little") + body


def test_injects_movie_maker_flags_before_project_arguments(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    command, output, relative = inject_movie_maker_arguments(
        ["godot.exe", "--path", "C:/game", "--", "--journey", "main-menu"],
        artifact_root=artifacts,
        output=Path("movies/main-menu.avi"),
        frames_per_second=30,
    )
    separator = command.index("--")
    assert command[separator - 5 : separator] == [
        "--write-movie",
        str(output),
        "--fixed-fps",
        "30",
        "--disable-vsync",
    ]
    assert relative == "movies/main-menu.avi"
    assert output.parent.is_dir()


def test_refuses_headless_duplicate_flags_non_avi_and_overwrite(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    with pytest.raises(NativeQaError, match="non-headless"):
        inject_movie_maker_arguments(
            ["godot", "--headless", "--path", "game"],
            artifact_root=artifacts,
            output=Path("movie.avi"),
        )
    with pytest.raises(NativeQaError, match="pre-existing"):
        inject_movie_maker_arguments(
            ["godot", "--write-movie", "old.avi"],
            artifact_root=artifacts,
            output=Path("movie.avi"),
        )
    with pytest.raises(NativeQaError, match=".avi"):
        inject_movie_maker_arguments(
            ["godot", "--path", "game"],
            artifact_root=artifacts,
            output=Path("movie.mp4"),
        )
    existing = artifacts / "existing.avi"
    existing.write_bytes(avi_bytes())
    with pytest.raises(NativeQaError, match="overwrite"):
        inject_movie_maker_arguments(
            ["godot", "--path", "game"],
            artifact_root=artifacts,
            output=existing,
        )


def test_validates_riff_avi_signature_chunks_size_and_hash(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    movie = artifacts / "movies" / "journey.avi"
    movie.parent.mkdir(parents=True)
    content = avi_bytes(b"rendered-frames")
    movie.write_bytes(content)
    evidence = validate_avi_movie(artifacts, movie)
    assert evidence.relative_path == "movies/journey.avi"
    assert evidence.size_bytes == len(content)
    assert evidence.sha256 == hashlib.sha256(content).hexdigest()
    assert evidence.container == "video/x-msvideo"


def test_rejects_non_avi_and_root_escape(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    invalid = artifacts / "invalid.avi"
    invalid.write_bytes(b"not-an-avi" * 20)
    with pytest.raises(NativeQaError, match="RIFF/AVI"):
        validate_avi_movie(artifacts, invalid)
    outside = tmp_path / "outside.avi"
    outside.write_bytes(avi_bytes())
    with pytest.raises(NativeQaError, match="escapes"):
        validate_avi_movie(artifacts, outside)


def test_builds_and_verifies_exact_source_movie_adapter_receipt(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    movie = artifacts / "movie.avi"
    artifacts.mkdir()
    movie.write_bytes(avi_bytes())
    evidence = validate_avi_movie(artifacts, movie)
    start = datetime.now(UTC)
    receipt = build_movie_adapter_receipt(
        evidence=evidence,
        journey_id="main-menu",
        source_identity="a" * 64,
        command_sha256=command_digest(["godot", "--path", "game"]),
        started_at=start.isoformat(),
        completed_at=(start + timedelta(seconds=5)).isoformat(),
        frames_per_second=30,
    )
    assert receipt["status"] == "locally-verified"
    assert receipt["headless"] is False
    assert receipt["arbitraryShellAccepted"] is False
    assert verify_movie_adapter_receipt(receipt) is True
    assert verify_movie_adapter_receipt({**receipt, "movieBytes": receipt["movieBytes"] + 1}) is False


def test_receipt_never_manufactures_worker_admission(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    movie = artifacts / "movie.avi"
    movie.write_bytes(avi_bytes())
    evidence = validate_avi_movie(artifacts, movie)
    started = datetime.now(UTC)
    receipt = build_movie_adapter_receipt(
        evidence=evidence,
        journey_id="journey-1",
        source_identity="b" * 64,
        command_sha256="c" * 64,
        started_at=started.isoformat(),
        completed_at=(started + timedelta(seconds=1)).isoformat(),
        frames_per_second=60,
        worker_admitted=False,
    )
    assert receipt["workerAdmitted"] is False
    assert receipt["status"] == "locally-verified"
