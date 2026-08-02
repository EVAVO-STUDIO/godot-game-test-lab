from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from godot_game_test_lab.media_evidence import (
    analyze_media_file,
    normalize_media_policy,
    parse_loudness_metrics,
    parse_silence_segments,
    parse_volume_metrics,
    scan_run_media,
)
from godot_game_test_lab.native_qa_common import NativeQaError


def test_media_policy_is_strict_and_bounded() -> None:
    policy = normalize_media_policy(
        {
            "requireAudioTrack": True,
            "failOnClipping": True,
            "maximumPeakDbfs": -0.5,
            "maximumSilenceRatio": 0.25,
        }
    )
    assert policy["requireAudioTrack"] is True
    assert policy["maximumPeakDbfs"] == -0.5
    assert policy["maximumSilenceRatio"] == 0.25

    with pytest.raises(NativeQaError, match="unsupported fields"):
        normalize_media_policy({"unknown": True})
    with pytest.raises(NativeQaError, match="finite number"):
        normalize_media_policy({"maximumSilenceRatio": float("nan")})


def test_ffmpeg_metric_parsers_keep_final_summary() -> None:
    volume = parse_volume_metrics("mean_volume: -22.1 dB\nmax_volume: -0.4 dB\n")
    assert volume == {"meanDbfs": -22.1, "peakDbfs": -0.4}

    loudness = parse_loudness_metrics(
        "I: -99.0 LUFS\nI: -18.2 LUFS\nLRA: 5.5 LU\nPeak: -0.8 dBFS\n"
    )
    assert loudness["integratedLufs"] == -18.2
    assert loudness["loudnessRangeLu"] == 5.5
    assert loudness["truePeakDbfs"] == -0.8

    segments = parse_silence_segments(
        "silence_start: 0\nsilence_end: 1.25 | silence_duration: 1.25\n"
        "silence_start: 3.5\n",
        5.0,
    )
    assert segments == [
        {"startSeconds": 0.0, "endSeconds": 1.25, "durationSeconds": 1.25},
        {"startSeconds": 3.5, "endSeconds": 5.0, "durationSeconds": 1.5},
    ]


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="FFmpeg is unavailable on this source-only runner",
)
def test_real_media_analysis_retains_audio_and_visual_review_assets(tmp_path: Path) -> None:
    movie = tmp_path / "gameplay.mkv"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x180:rate=30:duration=2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=44100:duration=2",
            "-shortest",
            "-c:v",
            "ffv1",
            "-c:a",
            "pcm_s16le",
            str(movie),
        ],
        check=True,
    )

    review = tmp_path / "review"
    report = analyze_media_file(
        movie,
        review,
        policy={"requireAudioTrack": True},
        timeout_seconds=60,
    )

    assert report["status"] == "passed"
    assert report["metrics"]["audible"] is True
    assert report["streams"]["audio"]
    assert (review / "audio.wav").is_file()
    assert (review / "audio-preview.wav").is_file()
    assert (review / "waveform.png").is_file()
    assert (review / "spectrogram.png").is_file()
    assert (review / "media-report.json").is_file()

    summary = scan_run_media(
        tmp_path,
        tmp_path / "run-media-review",
        policy={"requireAudioTrack": True},
        timeout_seconds=60,
    )
    assert summary["status"] == "passed"
    assert summary["mediaFiles"] == 1
    assert summary["items"][0]["audioPreview"] is not None
