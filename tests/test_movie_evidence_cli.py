from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from godot_game_test_lab.movie_evidence_cli import main
from godot_game_test_lab.movie_source_identity import capture_movie_source_identity


def avi_bytes(payload: bytes = b"frame-data") -> bytes:
    body = b"AVI " + b"LIST" + b"avih" + b"\0" * 32 + b"LIST" + b"movi" + payload
    return b"RIFF" + len(body).to_bytes(4, "little") + body


def test_receipt_and_doctor_round_trip_exact_movie_bytes(
    tmp_path: Path,
    capsys,
) -> None:
    root = tmp_path / "artifacts"
    movie = root / "movies" / "journey.avi"
    receipt = root / "receipts" / "journey.json"
    movie.parent.mkdir(parents=True)
    content = avi_bytes(b"rendered-journey")
    movie.write_bytes(content)
    started = datetime.now(UTC)
    source_identity = capture_movie_source_identity()
    assert main([
        "receipt",
        "--artifact-root",
        str(root),
        "--movie",
        str(movie),
        "--journey-id",
        "main-menu",
        "--source-identity",
        source_identity,
        "--command-sha256",
        "b" * 64,
        "--started-at",
        started.isoformat(),
        "--completed-at",
        (started + timedelta(seconds=5)).isoformat(),
        "--frames-per-second",
        "30",
        "--output",
        str(receipt),
    ]) == 0
    created = json.loads(receipt.read_text(encoding="utf-8"))
    assert created["movieSha256"] == hashlib.sha256(content).hexdigest()
    assert created["videoSha256"] == created["movieSha256"]
    assert created["evidenceSha256"] == created["movieSha256"]
    assert created["sourceIdentity"] == source_identity
    assert created["workerAdmitted"] is False
    assert created["captureElapsedSeconds"] == 5
    assert "durationSeconds" not in created

    assert main([
        "doctor",
        "--artifact-root",
        str(root),
        "--receipt",
        str(receipt),
        "--expected-source-identity",
        source_identity,
    ]) == 0
    output = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    result = json.loads(output[-1])
    assert result["ready"] is True
    assert result["exactMovieBytesVerified"] is True
    assert result["currentSourceIdentityVerified"] is True
    assert result["captureElapsedSeconds"] == 5
    assert "durationSeconds" not in result
    assert result["movieSha256"] == hashlib.sha256(content).hexdigest()


def test_receipt_rejects_a_fabricated_source_identity(tmp_path: Path, capsys) -> None:
    root = tmp_path / "artifacts"
    movie = root / "movie.avi"
    root.mkdir()
    movie.write_bytes(avi_bytes())
    started = datetime.now(UTC)
    assert main([
        "receipt",
        "--artifact-root",
        str(root),
        "--movie",
        str(movie),
        "--journey-id",
        "journey-1",
        "--source-identity",
        "0" * 64,
        "--command-sha256",
        "d" * 64,
        "--started-at",
        started.isoformat(),
        "--completed-at",
        (started + timedelta(seconds=1)).isoformat(),
    ]) == 2
    result = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert result["ready"] is False
    assert "does not match the current implementation" in result["error"]


def test_doctor_rejects_movie_tampering(tmp_path: Path, capsys) -> None:
    root = tmp_path / "artifacts"
    movie = root / "movie.avi"
    receipt = root / "receipt.json"
    root.mkdir()
    movie.write_bytes(avi_bytes())
    started = datetime.now(UTC)
    assert main([
        "receipt",
        "--artifact-root",
        str(root),
        "--movie",
        str(movie),
        "--journey-id",
        "journey-1",
        "--command-sha256",
        "d" * 64,
        "--started-at",
        started.isoformat(),
        "--completed-at",
        (started + timedelta(seconds=1)).isoformat(),
        "--output",
        str(receipt),
    ]) == 0
    movie.write_bytes(avi_bytes(b"tampered"))
    assert main([
        "doctor",
        "--artifact-root",
        str(root),
        "--receipt",
        str(receipt),
    ]) == 2
    output = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    result = json.loads(output[-1])
    assert result["ready"] is False
    assert "digest" in result["error"] or "size" in result["error"]


def test_receipt_is_create_once(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    movie = root / "movie.avi"
    receipt = root / "receipt.json"
    root.mkdir()
    movie.write_bytes(avi_bytes())
    receipt.write_text("{}\n", encoding="utf-8")
    started = datetime.now(UTC)
    assert main([
        "receipt",
        "--artifact-root",
        str(root),
        "--movie",
        str(movie),
        "--journey-id",
        "journey-1",
        "--command-sha256",
        "f" * 64,
        "--started-at",
        started.isoformat(),
        "--completed-at",
        (started + timedelta(seconds=1)).isoformat(),
        "--output",
        str(receipt),
    ]) == 2
