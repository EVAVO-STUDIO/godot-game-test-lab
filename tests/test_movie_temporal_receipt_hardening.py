from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from godot_game_test_lab.movie_temporal import (
    VerifiedMovieFrame,
    VerifiedMovieFrameSequence,
    build_temporal_adapter_receipt,
    verify_temporal_adapter_receipt,
)
from godot_game_test_lab.native_qa_common import NativeQaError


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _sequence(tmp_path: Path) -> VerifiedMovieFrameSequence:
    frames = tuple(
        VerifiedMovieFrame(
            frame_id=f"frame-{index}",
            timestamp_ms=index * 1000,
            relative_path=f"frames/frame-{index}.png",
            sha256=str(index + 1) * 64,
            size_bytes=100,
            absolute_path=tmp_path / "frames" / f"frame-{index}.png",
        )
        for index in range(3)
    )
    return VerifiedMovieFrameSequence(
        manifest_path=tmp_path / "sequence.json",
        manifest_relative_path="sequence.json",
        manifest_sha256="a" * 64,
        sequence_digest="b" * 64,
        movie_sha256="c" * 64,
        movie_bytes=4096,
        extraction_source_identity="d" * 64,
        extraction_command_sha256="e" * 64,
        created_at="2026-08-30T00:00:00+00:00",
        duration_ms=2000,
        frames_per_second=30.0,
        frames=frames,
    )


def _report(sequence: VerifiedMovieFrameSequence) -> dict[str, object]:
    partial: dict[str, object] = {
        "schema": "evavo.godot-movie-temporal-report.v1",
        "inputMovieSha256": sequence.movie_sha256,
        "sequenceDigest": sequence.sequence_digest,
        "sequenceManifestSha256": sequence.manifest_sha256,
        "sampledFrameCount": len(sequence.frames),
        "observedChange": True,
        "temporalVerdict": "pass",
        "policy": {
            "expectedChange": True,
            "minimumSamples": 3,
            "maximumGapMs": 2000,
            "maximumFrozenDurationMs": 2000,
            "boundaryToleranceMs": 1000,
        },
        "findings": [],
    }
    return {**partial, "reportDigest": _digest(partial)}


def _receipt(tmp_path: Path, issued: datetime) -> dict[str, object]:
    sequence = _sequence(tmp_path)
    return build_temporal_adapter_receipt(
        sequence=sequence,
        report=_report(sequence),
        source_identity="f" * 64,
        issued_at=issued.isoformat(),
    )


def _redigest(receipt: dict[str, object]) -> dict[str, object]:
    partial = dict(receipt)
    partial.pop("receiptDigest", None)
    return {**partial, "receiptDigest": _digest(partial)}


def test_fresh_receipt_accepts_only_the_expected_source_identity(tmp_path: Path) -> None:
    now = datetime(2026, 8, 30, 1, 0, tzinfo=UTC)
    receipt = _receipt(tmp_path, now)
    assert verify_temporal_adapter_receipt(
        receipt,
        now=now,
        expected_source_identity="f" * 64,
    )
    assert not verify_temporal_adapter_receipt(
        receipt,
        now=now,
        expected_source_identity="0" * 64,
    )


def test_recomputed_unknown_fields_and_partial_report_bindings_are_rejected(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 8, 30, 1, 0, tzinfo=UTC)
    receipt = _receipt(tmp_path, now)
    assert not verify_temporal_adapter_receipt(
        _redigest({**receipt, "inventedProof": True}),
        now=now,
    )
    assert not verify_temporal_adapter_receipt(
        _redigest({**receipt, "temporalReportRelativePath": "report.json"}),
        now=now,
    )


def test_recomputed_status_and_capability_forgery_is_rejected(tmp_path: Path) -> None:
    now = datetime(2026, 8, 30, 1, 0, tzinfo=UTC)
    receipt = _receipt(tmp_path, now)
    assert not verify_temporal_adapter_receipt(
        _redigest({**receipt, "status": "worker-admitted"}),
        now=now,
    )
    assert not verify_temporal_adapter_receipt(
        _redigest({
            **receipt,
            "capabilities": [*receipt["capabilities"], "human-review"],
        }),
        now=now,
    )


def test_recomputed_verdict_must_match_findings(tmp_path: Path) -> None:
    now = datetime(2026, 8, 30, 1, 0, tzinfo=UTC)
    receipt = _receipt(tmp_path, now)
    finding = {
        "code": "unexpected-freeze",
        "severity": "error",
        "detail": "The rendered pixels did not change.",
        "frameIds": ["frame-0", "frame-1"],
    }
    forged = _redigest({
        **receipt,
        "findings": [finding],
        "temporalVerdict": "pass",
    })
    assert not verify_temporal_adapter_receipt(forged, now=now)


def test_receipt_builder_rejects_findings_for_unknown_frames(tmp_path: Path) -> None:
    sequence = _sequence(tmp_path)
    report = _report(sequence)
    partial = dict(report)
    partial.pop("reportDigest")
    partial["temporalVerdict"] = "needs-review"
    partial["findings"] = [{
        "code": "sample-gap",
        "severity": "warning",
        "detail": "A sample gap exceeded policy.",
        "frameIds": ["not-in-sequence"],
    }]
    report = {**partial, "reportDigest": _digest(partial)}
    with pytest.raises(NativeQaError, match="unknown sampled frame"):
        build_temporal_adapter_receipt(
            sequence=sequence,
            report=report,
            source_identity="f" * 64,
            issued_at="2026-08-30T01:00:00+00:00",
        )


def test_receipt_lifetime_and_future_skew_are_enforced(tmp_path: Path) -> None:
    now = datetime(2026, 8, 30, 1, 0, tzinfo=UTC)
    expired = _receipt(tmp_path, now - timedelta(hours=1))
    future = _receipt(tmp_path, now + timedelta(minutes=6))
    assert not verify_temporal_adapter_receipt(expired, now=now)
    assert not verify_temporal_adapter_receipt(future, now=now)
