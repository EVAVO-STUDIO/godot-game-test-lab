from __future__ import annotations

import re
from argparse import Namespace
from hashlib import sha256
from pathlib import Path

import pytest

from godot_game_test_lab.native_qa_common import NativeQaError
from godot_game_test_lab.native_qa_motion_evidence import (
    augment_native_qa_motion_evidence,
    canonical_sha256,
    visual_motion_source_identity,
)

PNG_PREFIX = b"\x89PNG\r\n\x1a\n"
OBSERVATION_ID = re.compile(r"^godot:[a-z0-9._-]+:[a-f0-9]{24}$")


def _journey_artifacts(root: Path) -> None:
    journey = root / "journeys" / "menu"
    screenshots = journey / "screenshots"
    screenshots.mkdir(parents=True)
    (journey / "gameplay.avi").write_bytes(b"RIFF" + b"\x00" * 128)
    (screenshots / "frame-01.png").write_bytes(PNG_PREFIX + b"first-frame")
    (screenshots / "frame-02.png").write_bytes(PNG_PREFIX + b"second-frame")


def _summary(native: bool = True, run_id: str = "run-1") -> dict[str, object]:
    return {
        "schemaVersion": "2.0",
        "runId": run_id,
        "status": "passed",
        "generatedAt": "2026-08-30T00:00:00+00:00",
        "labSha": "a" * 40,
        "nativeDesktopEvidence": native,
        "executionBudget": {},
        "truthBoundary": "Existing boundary.",
        "journeys": [
            {
                "id": "menu",
                "required": True,
                "status": "passed",
                "scene": "res://MainMenu.tscn",
                "visual": {
                    "status": "passed",
                    "diagnostics": {
                        "ffprobe": {
                            "format": {"duration": "2.500"},
                            "streams": [{"codec_type": "video"}],
                        },
                        "blackSegments": [],
                        "freezeSegments": [],
                    },
                },
                "evidence": [],
            }
        ],
    }


def _args(artifacts: Path) -> Namespace:
    repository = Path(__file__).resolve().parents[1]
    return Namespace(
        artifacts=artifacts,
        max_artifact_bytes=64 * 1024 * 1024,
        lab_root=repository,
        expected_lab_sha="a" * 40,
    )


def _file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def test_motion_package_binds_movie_frames_analysis_and_adapter_receipt(
    tmp_path: Path,
) -> None:
    _journey_artifacts(tmp_path)
    result = augment_native_qa_motion_evidence(_args(tmp_path), _summary())
    receipt = result["visualAdapterReceipt"]
    assert isinstance(receipt, dict)
    assert receipt["adapterId"] == "godot-game-test-lab.video-evidence"
    assert receipt["ready"] is True
    assert receipt["status"] == "locally-verified"
    assert {
        "screen-recording",
        "screenshot-sequence",
        "temporal-analysis",
        "layout-analysis",
        "native-control-tree",
    }.issubset(set(receipt["capabilities"]))
    assert result["visualAdapterReceiptSha256"] == canonical_sha256(receipt)

    journey = result["journeys"][0]
    evidence = journey["motionEvidence"]
    analysis_path = tmp_path / "journeys" / "menu" / "motion-analysis.json"
    assert evidence["mediaType"] == "video/x-msvideo"
    assert evidence["durationSeconds"] == 2.5
    assert evidence["sampledFrameCount"] == 2
    assert evidence["observedChange"] is True
    assert evidence["temporalVerdict"] == "pass"
    assert evidence["captureReceiptSha256"] == canonical_sha256(receipt)
    assert evidence["temporalAnalysisSha256"] == _file_sha256(analysis_path)
    assert OBSERVATION_ID.fullmatch(journey["motionObservationId"])
    assert journey["motionObservationId"] == evidence["observationIds"][0]
    assert journey["motionAnalysis"]["runId"] == "run-1"
    assert journey["motionAnalysis"]["journeyId"] == "menu"
    unsigned = dict(evidence)
    unsigned.pop("motionEvidenceDigest")
    assert evidence["motionEvidenceDigest"] == canonical_sha256(unsigned)
    assert analysis_path.is_file()
    assert (tmp_path / "journeys" / "menu" / "motion-frame-sequence.json").is_file()
    assert (tmp_path / "journeys" / "menu" / "motion-evidence.json").is_file()
    assert (tmp_path / "godot-visual-adapter-receipt.json").is_file()
    assert any(
        item["path"] == "journeys/menu/motion-evidence.json"
        for item in result["artifacts"]
    )
    assert all(
        item["path"] != "native-agent-summary.json"
        for item in result["artifacts"]
    )


def test_run_identity_prevents_retest_observation_collisions(tmp_path: Path) -> None:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    same_root = tmp_path / "same"
    for root in (first_root, second_root, same_root):
        root.mkdir()
        _journey_artifacts(root)
    first = augment_native_qa_motion_evidence(
        _args(first_root), _summary(run_id="run-1")
    )
    second = augment_native_qa_motion_evidence(
        _args(second_root), _summary(run_id="run-2")
    )
    same = augment_native_qa_motion_evidence(
        _args(same_root), _summary(run_id="run-1")
    )
    first_id = first["journeys"][0]["motionObservationId"]
    second_id = second["journeys"][0]["motionObservationId"]
    same_id = same["journeys"][0]["motionObservationId"]
    assert first_id != second_id
    assert first_id == same_id
    assert OBSERVATION_ID.fullmatch(first_id)
    assert OBSERVATION_ID.fullmatch(second_id)


def test_noninteractive_run_cannot_manufacture_a_verified_adapter(tmp_path: Path) -> None:
    _journey_artifacts(tmp_path)
    result = augment_native_qa_motion_evidence(_args(tmp_path), _summary(native=False))
    receipt = result["visualAdapterReceipt"]
    assert receipt["ready"] is False
    assert receipt["status"] == "source-present"
    assert result["journeys"][0]["motionEvidence"]["temporalVerdict"] == "pass"


def test_missing_sample_frames_retains_video_but_marks_temporal_review_pending(
    tmp_path: Path,
) -> None:
    journey = tmp_path / "journeys" / "menu"
    journey.mkdir(parents=True)
    (journey / "gameplay.avi").write_bytes(b"RIFF" + b"\x00" * 128)
    result = augment_native_qa_motion_evidence(_args(tmp_path), _summary())
    evidence = result["journeys"][0]["motionEvidence"]
    assert evidence["sampledFrameCount"] == 0
    assert evidence["observedChange"] is False
    assert evidence["temporalVerdict"] == "needs-review"
    assert "screenshot-sequence" not in result["visualAdapterReceipt"]["capabilities"]


def test_source_identity_is_stable_and_rejects_invalid_git_identity() -> None:
    repository = Path(__file__).resolve().parents[1]
    first = visual_motion_source_identity(repository, "a" * 40)
    second = visual_motion_source_identity(repository, "a" * 40)
    assert first == second
    assert len(first) == 64
    with pytest.raises(NativeQaError, match="full lowercase Git SHA"):
        visual_motion_source_identity(repository, "main")


def test_unsafe_journey_identity_is_rejected(tmp_path: Path) -> None:
    summary = _summary()
    summary["journeys"][0]["id"] = "../escape"
    with pytest.raises(NativeQaError, match="unsafe id"):
        augment_native_qa_motion_evidence(_args(tmp_path), summary)


def test_missing_or_unbounded_run_identity_is_rejected(tmp_path: Path) -> None:
    summary = _summary()
    summary.pop("runId")
    with pytest.raises(NativeQaError, match="runId"):
        augment_native_qa_motion_evidence(_args(tmp_path), summary)
    summary = _summary(run_id="x" * 257)
    with pytest.raises(NativeQaError, match="runId"):
        augment_native_qa_motion_evidence(_args(tmp_path), summary)


def test_motion_evidence_is_create_once(tmp_path: Path) -> None:
    _journey_artifacts(tmp_path)
    args = _args(tmp_path)
    augment_native_qa_motion_evidence(args, _summary())
    with pytest.raises(NativeQaError, match="Refusing to overwrite"):
        augment_native_qa_motion_evidence(args, _summary())
