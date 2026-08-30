from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from godot_game_test_lab.movie_evidence import (
    build_movie_adapter_receipt,
    command_digest,
    validate_avi_movie,
)
from godot_game_test_lab.movie_source_identity import (
    capture_movie_source_identity,
    temporal_movie_source_identity,
)
from godot_game_test_lab.movie_temporal_cli import main

_PNG_A = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
_PNG_B = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl9Zz8AAAAASUVORK5CYII="
)


def _avi_bytes(payload: bytes = b"frame-data") -> bytes:
    body = b"AVI " + b"LIST" + b"avih" + b"\0" * 32 + b"LIST" + b"movi" + payload
    return b"RIFF" + len(body).to_bytes(4, "little") + body


def _capture_receipt(root: Path) -> Path:
    movie = root / "movies" / "journey.avi"
    movie.parent.mkdir(parents=True, exist_ok=True)
    movie.write_bytes(_avi_bytes(b"rendered-journey"))
    evidence = validate_avi_movie(root, movie)
    started = datetime.now(UTC)
    receipt = build_movie_adapter_receipt(
        evidence=evidence,
        journey_id="main-menu",
        source_identity=capture_movie_source_identity(),
        command_sha256=command_digest(["godot", "--path", "game"]),
        started_at=started.isoformat(),
        completed_at=(started + timedelta(seconds=2)).isoformat(),
        frames_per_second=30,
    )
    path = root / "receipts" / "capture.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _frames(root: Path) -> Path:
    entries = []
    for frame_id, timestamp_ms, content in (
        ("frame-0", 0, _PNG_A),
        ("frame-1", 1000, _PNG_B),
        ("frame-2", 2000, _PNG_B),
    ):
        path = root / "frames" / f"{frame_id}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        entries.append(
            {
                "id": frame_id,
                "timestampMs": timestamp_ms,
                "relativePath": path.relative_to(root).as_posix(),
            }
        )
    descriptor = {
        "schema": "evavo.godot-sampled-frame-input.v1",
        "frames": entries,
    }
    path = root / "frames" / "descriptor.json"
    path.write_text(json.dumps(descriptor, indent=2) + "\n", encoding="utf-8")
    return path


def _build_chain(root: Path) -> tuple[Path, Path, Path]:
    capture = _capture_receipt(root)
    frames = _frames(root)
    sequence = root / "temporal" / "sequence.json"
    report = root / "temporal" / "report.json"
    receipt = root / "temporal" / "receipt.json"
    assert main(
        [
            "manifest",
            "--artifact-root",
            str(root),
            "--movie-receipt",
            str(capture),
            "--frames",
            str(frames),
            "--duration-ms",
            "2000",
            "--frames-per-second",
            "30",
            "--extraction-source-identity",
            "b" * 64,
            "--extraction-command-sha256",
            "c" * 64,
            "--output",
            str(sequence),
        ]
    ) == 0
    temporal_identity = temporal_movie_source_identity()
    assert main(
        [
            "analyse",
            "--artifact-root",
            str(root),
            "--sequence",
            str(sequence),
            "--source-identity",
            temporal_identity,
            "--expected-change",
            "true",
            "--boundary-tolerance-ms",
            "0",
            "--report-output",
            str(report),
            "--receipt-output",
            str(receipt),
        ]
    ) == 0
    return sequence, report, receipt


def test_manifest_analysis_and_doctor_round_trip(tmp_path: Path, capsys) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    sequence, report, receipt = _build_chain(root)
    sequence_value = json.loads(sequence.read_text(encoding="utf-8"))
    report_value = json.loads(report.read_text(encoding="utf-8"))
    receipt_value = json.loads(receipt.read_text(encoding="utf-8"))
    assert sequence_value["movieSha256"] == receipt_value["inputMovieSha256"]
    assert report_value["temporalVerdict"] == "pass"
    assert report_value["observedChange"] is True
    assert receipt_value["adapterId"] == "godot-game-test-lab.movie-temporal"
    assert receipt_value["sourceIdentity"] == temporal_movie_source_identity()
    assert receipt_value["temporalAnalysisSha256"] == report_value["reportDigest"]
    assert receipt_value["temporalReportFileSha256"] == hashlib.sha256(
        report.read_bytes()
    ).hexdigest()

    assert main(
        [
            "doctor",
            "--artifact-root",
            str(root),
            "--receipt",
            str(receipt),
            "--expected-source-identity",
            temporal_movie_source_identity(),
        ]
    ) == 0
    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    result = json.loads(lines[-1])
    assert result["ready"] is True
    assert result["exactFrameBytesVerified"] is True
    assert result["currentSourceIdentityVerified"] is True
    assert result["temporalVerdict"] == "pass"
    assert result["sampledFrameCount"] == 3


def test_analysis_rejects_a_fabricated_temporal_source_identity(
    tmp_path: Path,
    capsys,
) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    capture = _capture_receipt(root)
    frames = _frames(root)
    sequence = root / "sequence.json"
    assert main([
        "manifest",
        "--artifact-root",
        str(root),
        "--movie-receipt",
        str(capture),
        "--frames",
        str(frames),
        "--duration-ms",
        "2000",
        "--frames-per-second",
        "30",
        "--extraction-source-identity",
        "b" * 64,
        "--extraction-command-sha256",
        "c" * 64,
        "--output",
        str(sequence),
    ]) == 0
    assert main([
        "analyse",
        "--artifact-root",
        str(root),
        "--sequence",
        str(sequence),
        "--source-identity",
        "0" * 64,
        "--expected-change",
        "true",
        "--report-output",
        str(root / "report.json"),
        "--receipt-output",
        str(root / "receipt.json"),
    ]) == 2
    result = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert result["ready"] is False
    assert "does not match the current implementation" in result["error"]


def test_doctor_rejects_report_tampering(tmp_path: Path, capsys) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    _, report, receipt = _build_chain(root)
    value = json.loads(report.read_text(encoding="utf-8"))
    value["temporalVerdict"] = "fail"
    report.write_text(json.dumps(value) + "\n", encoding="utf-8")
    assert main(
        [
            "doctor",
            "--artifact-root",
            str(root),
            "--receipt",
            str(receipt),
        ]
    ) == 2
    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    result = json.loads(lines[-1])
    assert result["ready"] is False
    assert "report file digest" in result["error"]


def test_doctor_rejects_sampled_frame_tampering(tmp_path: Path, capsys) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    _, _, receipt = _build_chain(root)
    frame = root / "frames" / "frame-1.png"
    frame.write_bytes(_PNG_A)
    assert main(
        [
            "doctor",
            "--artifact-root",
            str(root),
            "--receipt",
            str(receipt),
        ]
    ) == 2
    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    result = json.loads(lines[-1])
    assert result["ready"] is False
    assert "digest" in result["error"] or "byte count" in result["error"]


def test_outputs_are_create_once(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    sequence, report, receipt = _build_chain(root)
    capture = root / "receipts" / "capture.json"
    frames = root / "frames" / "descriptor.json"
    assert main(
        [
            "manifest",
            "--artifact-root",
            str(root),
            "--movie-receipt",
            str(capture),
            "--frames",
            str(frames),
            "--duration-ms",
            "2000",
            "--frames-per-second",
            "30",
            "--extraction-source-identity",
            "b" * 64,
            "--extraction-command-sha256",
            "c" * 64,
            "--output",
            str(sequence),
        ]
    ) == 2
    assert report.is_file()
    assert receipt.is_file()
