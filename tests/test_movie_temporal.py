from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from godot_game_test_lab.movie_temporal import (
    analyse_movie_frame_sequence,
    build_movie_frame_sequence_manifest,
    build_temporal_adapter_receipt,
    load_verified_movie_frame_sequence,
    source_identity,
    verify_temporal_adapter_receipt,
)
from godot_game_test_lab.native_qa_common import NativeQaError

_PNG_A = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
_PNG_B = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl9Zz8AAAAASUVORK5CYII="
)


def _frame(root: Path, name: str, content: bytes, timestamp_ms: int) -> dict[str, object]:
    path = root / "frames" / f"{name}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return {
        "id": name,
        "timestampMs": timestamp_ms,
        "relativePath": path.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(content).hexdigest(),
        "bytes": len(content),
    }


def _sequence(
    root: Path,
    frames: list[dict[str, object]],
    *,
    duration_ms: int,
) -> Path:
    value = build_movie_frame_sequence_manifest(
        movie_sha256="a" * 64,
        movie_bytes=4096,
        extraction_source_identity="b" * 64,
        extraction_command_sha256="c" * 64,
        created_at=datetime.now(UTC).isoformat(),
        duration_ms=duration_ms,
        frames_per_second=30,
        frames=frames,
    )
    path = root / "sequence.json"
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def test_reopens_every_png_and_binds_sequence_to_movie_and_extractor(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    manifest = _sequence(
        root,
        [
            _frame(root, "frame-0", _PNG_A, 0),
            _frame(root, "frame-1", _PNG_B, 1000),
            _frame(root, "frame-2", _PNG_A, 2000),
        ],
        duration_ms=2000,
    )
    loaded = load_verified_movie_frame_sequence(
        root,
        manifest,
        expected_movie_sha256="a" * 64,
        expected_extraction_source_identity="b" * 64,
    )
    assert loaded.movie_sha256 == "a" * 64
    assert loaded.extraction_source_identity == "b" * 64
    assert loaded.manifest_relative_path == "sequence.json"
    assert len(loaded.frames) == 3
    assert all(frame.absolute_path.is_file() for frame in loaded.frames)


def test_detects_two_frame_flicker_without_inventing_a_pass(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    manifest = _sequence(
        root,
        [
            _frame(root, "frame-0", _PNG_A, 0),
            _frame(root, "frame-1", _PNG_B, 1000),
            _frame(root, "frame-2", _PNG_A, 2000),
        ],
        duration_ms=2000,
    )
    loaded = load_verified_movie_frame_sequence(root, manifest)
    report = analyse_movie_frame_sequence(
        loaded,
        expected_change=True,
        maximum_gap_ms=1500,
        maximum_frozen_duration_ms=1500,
        boundary_tolerance_ms=0,
    )
    assert report["temporalVerdict"] == "needs-review"
    assert report["observedChange"] is True
    assert any(finding["code"] == "two-frame-flicker" for finding in report["findings"])
    assert re_digest(report) == report["reportDigest"]


def test_detects_freeze_and_missing_end_boundary(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    manifest = _sequence(
        root,
        [
            _frame(root, "frame-0", _PNG_A, 0),
            _frame(root, "frame-1", _PNG_A, 1000),
            _frame(root, "frame-2", _PNG_A, 3000),
        ],
        duration_ms=5000,
    )
    loaded = load_verified_movie_frame_sequence(root, manifest)
    report = analyse_movie_frame_sequence(
        loaded,
        expected_change=True,
        maximum_gap_ms=5000,
        maximum_frozen_duration_ms=1500,
        boundary_tolerance_ms=500,
    )
    codes = {finding["code"] for finding in report["findings"]}
    assert report["temporalVerdict"] == "fail"
    assert "unexpected-freeze" in codes
    assert "missing-end-boundary" in codes


def test_rejects_frame_tampering_and_sequence_digest_tampering(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    first = _frame(root, "frame-0", _PNG_A, 0)
    second = _frame(root, "frame-1", _PNG_B, 1000)
    third = _frame(root, "frame-2", _PNG_A, 2000)
    manifest = _sequence(root, [first, second, third], duration_ms=2000)
    (root / str(second["relativePath"])).write_bytes(_PNG_A)
    with pytest.raises(NativeQaError, match="byte count|digest"):
        load_verified_movie_frame_sequence(root, manifest)

    manifest = _sequence(
        root,
        [
            _frame(root, "new-0", _PNG_A, 0),
            _frame(root, "new-1", _PNG_B, 1000),
            _frame(root, "new-2", _PNG_A, 2000),
        ],
        duration_ms=2000,
    )
    value = json.loads(manifest.read_text(encoding="utf-8"))
    value["durationMs"] = 3000
    manifest.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(NativeQaError, match="sequence digest"):
        load_verified_movie_frame_sequence(root, manifest)


def test_builds_shared_temporal_adapter_receipt_bound_to_movie_and_sequence(
    tmp_path: Path,
) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    manifest = _sequence(
        root,
        [
            _frame(root, "frame-0", _PNG_A, 0),
            _frame(root, "frame-1", _PNG_B, 1000),
            _frame(root, "frame-2", _PNG_B, 2000),
        ],
        duration_ms=2000,
    )
    loaded = load_verified_movie_frame_sequence(root, manifest)
    report = analyse_movie_frame_sequence(loaded, expected_change=True)
    now = datetime.now(UTC)
    receipt = build_temporal_adapter_receipt(
        sequence=loaded,
        report=report,
        source_identity="d" * 64,
        issued_at=now.isoformat(),
    )
    assert receipt["schema"] == "evavo.visual-qa-adapter-receipt.v1"
    assert receipt["adapterId"] == "godot-game-test-lab.movie-temporal"
    assert receipt["inputMovieSha256"] == loaded.movie_sha256
    assert receipt["sequenceDigest"] == loaded.sequence_digest
    assert receipt["temporalAnalysisSha256"] == report["reportDigest"]
    assert receipt["workerAdmitted"] is False
    assert verify_temporal_adapter_receipt(receipt, now=now) is True
    assert verify_temporal_adapter_receipt(
        {**receipt, "inputMovieSha256": "e" * 64},
        now=now,
    ) is False


def test_source_identity_is_stable_and_root_confined(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    first = root / "a.py"
    second = root / "b.py"
    first.write_text("a\n", encoding="utf-8")
    second.write_text("b\n", encoding="utf-8")
    identity_one = source_identity([second, first], root=root)
    identity_two = source_identity([first, second], root=root)
    assert identity_one == identity_two
    assert len(identity_one) == 64
    outside = tmp_path / "outside.py"
    outside.write_text("outside\n", encoding="utf-8")
    with pytest.raises(NativeQaError, match="escapes"):
        source_identity([outside], root=root)


def re_digest(report: dict[str, object]) -> str:
    partial = dict(report)
    partial.pop("reportDigest", None)
    return hashlib.sha256(
        json.dumps(
            partial,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
