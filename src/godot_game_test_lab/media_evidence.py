from __future__ import annotations

import json
import math
import re
import shutil
from pathlib import Path
from typing import Any

from .native_qa_common import (
    NativeQaError,
    _canonical_json,
    _process_findings,
    _run_process,
    _sha256_file,
    _write_process_evidence,
)

_MEDIA_SUFFIXES = {".avi", ".mkv", ".mov", ".mp4", ".ogv", ".webm"}
_MAX_MEDIA_FILES = 128
_MAX_MEDIA_BYTES = 64 * 1024 * 1024 * 1024
_MAX_PREVIEW_BYTES = 32 * 1024 * 1024
_NUMBER = r"(?:-?inf|[-+]?[0-9]+(?:\.[0-9]+)?)"
_VOLUME_RE = re.compile(
    rf"(?P<name>mean_volume|max_volume):\s*(?P<value>{_NUMBER})\s*dB",
    re.IGNORECASE,
)
_SILENCE_START_RE = re.compile(r"silence_start:\s*(?P<value>[0-9.]+)")
_SILENCE_END_RE = re.compile(
    r"silence_end:\s*(?P<end>[0-9.]+)\s*\|\s*silence_duration:\s*(?P<duration>[0-9.]+)"
)
_EBU_I_RE = re.compile(rf"^\s*I:\s*(?P<value>{_NUMBER})\s*LUFS", re.MULTILINE)
_EBU_LRA_RE = re.compile(rf"^\s*LRA:\s*(?P<value>{_NUMBER})\s*LU", re.MULTILINE)
_EBU_PEAK_RE = re.compile(rf"^\s*Peak:\s*(?P<value>{_NUMBER})\s*dBFS", re.MULTILINE)
_POLICY_KEYS = {
    "failOnAvSyncDrift",
    "failOnClipping",
    "failOnSilence",
    "maximumAvSyncDriftSeconds",
    "maximumPeakDbfs",
    "maximumSilenceRatio",
    "minimumAudiblePeakDbfs",
    "minimumSilenceDurationSeconds",
    "requireAudioTrack",
    "silenceNoiseDb",
}


def _finite_number(value: Any, label: str, minimum: float, maximum: float) -> float:
    if (
        not isinstance(value, int | float)
        or isinstance(value, bool)
        or not math.isfinite(float(value))
        or not minimum <= float(value) <= maximum
    ):
        raise NativeQaError(f"{label} must be a finite number between {minimum} and {maximum}")
    return float(value)


def _boolean(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise NativeQaError(f"{label} must be boolean")
    return value


def normalize_media_policy(value: dict[str, Any] | None = None) -> dict[str, Any]:
    raw = value or {}
    if not isinstance(raw, dict):
        raise NativeQaError("media policy must be an object")
    unknown = sorted(set(raw) - _POLICY_KEYS)
    if unknown:
        raise NativeQaError("media policy contains unsupported fields: " + ", ".join(unknown))
    return {
        "requireAudioTrack": _boolean(
            raw.get("requireAudioTrack", False), "media.requireAudioTrack"
        ),
        "failOnSilence": _boolean(raw.get("failOnSilence", False), "media.failOnSilence"),
        "failOnClipping": _boolean(
            raw.get("failOnClipping", False), "media.failOnClipping"
        ),
        "failOnAvSyncDrift": _boolean(
            raw.get("failOnAvSyncDrift", False), "media.failOnAvSyncDrift"
        ),
        "silenceNoiseDb": _finite_number(
            raw.get("silenceNoiseDb", -60.0), "media.silenceNoiseDb", -120.0, -1.0
        ),
        "minimumSilenceDurationSeconds": _finite_number(
            raw.get("minimumSilenceDurationSeconds", 0.75),
            "media.minimumSilenceDurationSeconds",
            0.05,
            120.0,
        ),
        "maximumSilenceRatio": _finite_number(
            raw.get("maximumSilenceRatio", 1.0),
            "media.maximumSilenceRatio",
            0.0,
            1.0,
        ),
        "minimumAudiblePeakDbfs": _finite_number(
            raw.get("minimumAudiblePeakDbfs", -70.0),
            "media.minimumAudiblePeakDbfs",
            -120.0,
            0.0,
        ),
        "maximumPeakDbfs": _finite_number(
            raw.get("maximumPeakDbfs", -0.1),
            "media.maximumPeakDbfs",
            -40.0,
            0.0,
        ),
        "maximumAvSyncDriftSeconds": _finite_number(
            raw.get("maximumAvSyncDriftSeconds", 0.25),
            "media.maximumAvSyncDriftSeconds",
            0.0,
            10.0,
        ),
    }


def _number(value: str | None) -> float | None:
    if value is None or value.casefold() in {"inf", "+inf", "-inf"}:
        return None
    try:
        parsed = float(value)
    except ValueError:
        return None
    return parsed if math.isfinite(parsed) else None


def _last_match(pattern: re.Pattern[str], text: str) -> float | None:
    matches = list(pattern.finditer(text))
    return _number(matches[-1].group("value")) if matches else None


def parse_volume_metrics(text: str) -> dict[str, float | None]:
    metrics: dict[str, float | None] = {"meanDbfs": None, "peakDbfs": None}
    for match in _VOLUME_RE.finditer(text):
        name = match.group("name").casefold()
        key = "meanDbfs" if name == "mean_volume" else "peakDbfs"
        metrics[key] = _number(match.group("value"))
    return metrics


def parse_loudness_metrics(text: str) -> dict[str, float | None]:
    return {
        "integratedLufs": _last_match(_EBU_I_RE, text),
        "loudnessRangeLu": _last_match(_EBU_LRA_RE, text),
        "truePeakDbfs": _last_match(_EBU_PEAK_RE, text),
    }


def parse_silence_segments(text: str, duration_seconds: float | None) -> list[dict[str, float]]:
    events: list[tuple[int, str, float, float | None]] = []
    for match in _SILENCE_START_RE.finditer(text):
        events.append((match.start(), "start", float(match.group("value")), None))
    for match in _SILENCE_END_RE.finditer(text):
        events.append(
            (
                match.start(),
                "end",
                float(match.group("end")),
                float(match.group("duration")),
            )
        )
    events.sort(key=lambda item: item[0])
    active: float | None = None
    segments: list[dict[str, float]] = []
    for _offset, event_type, value, reported_duration in events:
        if event_type == "start":
            active = value
            continue
        start = active if active is not None else max(0.0, value - float(reported_duration or 0))
        duration = max(0.0, float(reported_duration or (value - start)))
        segments.append(
            {
                "startSeconds": round(start, 6),
                "endSeconds": round(value, 6),
                "durationSeconds": round(duration, 6),
            }
        )
        active = None
    if active is not None and duration_seconds is not None and duration_seconds > active:
        segments.append(
            {
                "startSeconds": round(active, 6),
                "endSeconds": round(duration_seconds, 6),
                "durationSeconds": round(duration_seconds - active, 6),
            }
        )
    return segments


def _duration(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) and parsed >= 0.0 else None


def _probe_duration(probe: dict[str, Any], media_type: str | None = None) -> float | None:
    streams = probe.get("streams", [])
    if isinstance(streams, list):
        values = []
        for stream in streams:
            if not isinstance(stream, dict):
                continue
            if media_type is not None and stream.get("codec_type") != media_type:
                continue
            duration = _duration(stream.get("duration"))
            if duration is not None:
                values.append(duration)
        if values:
            return max(values)
    container = probe.get("format", {})
    return _duration(container.get("duration")) if isinstance(container, dict) else None


def _finding(severity: str, code: str, message: str) -> dict[str, str]:
    return {"severity": severity, "code": code, "message": message}


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _safe_output_root(path: Path) -> Path:
    resolved = path.expanduser().resolve(strict=False)
    if resolved.exists() and (resolved.is_symlink() or not resolved.is_dir()):
        raise NativeQaError(f"media evidence output must be a directory: {resolved}")
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def _tool_path(explicit: Path | None, name: str) -> str:
    if explicit is not None:
        resolved = explicit.expanduser().resolve(strict=True)
        if not resolved.is_file():
            raise NativeQaError(f"{name} path is not a file: {resolved}")
        return str(resolved)
    discovered = shutil.which(name)
    if not discovered:
        raise NativeQaError(f"{name} is required for synchronized media evidence")
    return discovered


def analyze_media_file(
    media: Path,
    output_root: Path,
    *,
    policy: dict[str, Any] | None = None,
    timeout_seconds: int = 300,
    ffmpeg: Path | None = None,
    ffprobe: Path | None = None,
) -> dict[str, Any]:
    governed = normalize_media_policy(policy)
    source = media.expanduser()
    if source.is_symlink():
        raise NativeQaError(f"media source may not be a symbolic link: {source}")
    source = source.resolve(strict=True)
    if not source.is_file() or source.suffix.casefold() not in _MEDIA_SUFFIXES:
        raise NativeQaError(f"media source is not a supported regular file: {source}")
    size = source.stat().st_size
    if size <= 0 or size > _MAX_MEDIA_BYTES:
        raise NativeQaError(f"media source size is outside the bounded range: {size}")
    if not isinstance(timeout_seconds, int) or isinstance(timeout_seconds, bool):
        raise NativeQaError("timeout_seconds must be an integer")
    if not 10 <= timeout_seconds <= 3600:
        raise NativeQaError("timeout_seconds must be between 10 and 3600")

    root = _safe_output_root(output_root)
    ffmpeg_bin = _tool_path(ffmpeg, "ffmpeg")
    ffprobe_bin = _tool_path(ffprobe, "ffprobe")
    evidence: list[str] = []
    findings: list[dict[str, str]] = []

    probe_result = _run_process(
        [
            ffprobe_bin,
            "-v",
            "error",
            "-show_format",
            "-show_streams",
            "-of",
            "json",
            str(source),
        ],
        source.parent,
        timeout_seconds,
    )
    evidence.extend(_write_process_evidence(probe_result, root, "ffprobe"))
    process_findings = _process_findings(probe_result, "ffprobe")
    if process_findings:
        for message in process_findings:
            findings.append(_finding("error", "media.ffprobe_failed", message))
        report = {
            "schemaVersion": "1.0",
            "status": "failed",
            "source": str(source),
            "sourceBytes": size,
            "sourceSha256": _sha256_file(source),
            "policy": governed,
            "findings": findings,
            "evidence": sorted(set(evidence)),
        }
        (root / "media-report.json").write_text(_canonical_json(report), encoding="utf-8")
        return report

    try:
        probe = json.loads(str(probe_result.get("stdout", "")))
    except json.JSONDecodeError as error:
        raise NativeQaError(f"ffprobe returned invalid JSON: {error}") from error
    if not isinstance(probe, dict):
        raise NativeQaError("ffprobe root must be an object")
    probe_path = root / "ffprobe.json"
    probe_path.write_text(_canonical_json(probe), encoding="utf-8")
    evidence.append(_relative(probe_path, root))

    streams = probe.get("streams", [])
    stream_list = streams if isinstance(streams, list) else []
    audio_streams = [
        stream
        for stream in stream_list
        if isinstance(stream, dict) and stream.get("codec_type") == "audio"
    ]
    video_streams = [
        stream
        for stream in stream_list
        if isinstance(stream, dict) and stream.get("codec_type") == "video"
    ]
    container_duration = _probe_duration(probe)
    audio_duration = _probe_duration(probe, "audio")
    video_duration = _probe_duration(probe, "video")

    if not audio_streams:
        severity = "error" if governed["requireAudioTrack"] else "warning"
        findings.append(
            _finding(severity, "audio.track_missing", "The recorded movie has no audio stream.")
        )
        report = {
            "schemaVersion": "1.0",
            "status": "failed" if severity == "error" else "passed",
            "source": str(source),
            "sourceBytes": size,
            "sourceSha256": _sha256_file(source),
            "policy": governed,
            "streams": {
                "audio": [],
                "video": video_streams,
                "containerDurationSeconds": container_duration,
            },
            "metrics": {},
            "findings": findings,
            "evidence": sorted(set(evidence)),
            "truthBoundary": (
                "No audio stream was available to audition or analyse. Visual evidence remains "
                "separate and does not prove sound output."
            ),
        }
        report_path = root / "media-report.json"
        report_path.write_text(_canonical_json(report), encoding="utf-8")
        return report

    audio_path = root / "audio.wav"
    extract_result = _run_process(
        [
            ffmpeg_bin,
            "-hide_banner",
            "-nostdin",
            "-y",
            "-i",
            str(source),
            "-map",
            "0:a:0",
            "-vn",
            "-c:a",
            "pcm_s16le",
            str(audio_path),
        ],
        root,
        timeout_seconds,
        artifact_budget_root=root,
        maximum_artifact_bytes=_MAX_MEDIA_BYTES,
    )
    evidence.extend(_write_process_evidence(extract_result, root, "audio-extract"))
    for message in _process_findings(extract_result, "audio extraction"):
        findings.append(_finding("error", "audio.extract_failed", message))
    if not audio_path.is_file() or audio_path.stat().st_size <= 44:
        findings.append(
            _finding("error", "audio.wav_missing", "FFmpeg did not produce a valid WAV track.")
        )
        report = {
            "schemaVersion": "1.0",
            "status": "failed",
            "source": str(source),
            "sourceBytes": size,
            "sourceSha256": _sha256_file(source),
            "policy": governed,
            "streams": {
                "audio": audio_streams,
                "video": video_streams,
                "containerDurationSeconds": container_duration,
                "audioDurationSeconds": audio_duration,
                "videoDurationSeconds": video_duration,
            },
            "metrics": {},
            "findings": findings,
            "evidence": sorted(set(evidence)),
            "truthBoundary": (
                "The recorded movie declared an audio stream, but a bounded WAV could not be "
                "extracted for audition or objective analysis."
            ),
        }
        report_path = root / "media-report.json"
        report_path.write_text(_canonical_json(report), encoding="utf-8")
        return report
    evidence.append(_relative(audio_path, root))

    preview_path = root / "audio-preview.wav"
    if audio_path.is_file():
        preview_result = _run_process(
            [
                ffmpeg_bin,
                "-hide_banner",
                "-nostdin",
                "-y",
                "-i",
                str(audio_path),
                "-t",
                "30",
                "-ar",
                "44100",
                "-ac",
                "2",
                "-c:a",
                "pcm_s16le",
                str(preview_path),
            ],
            root,
            timeout_seconds,
            artifact_budget_root=root,
            maximum_artifact_bytes=_MAX_MEDIA_BYTES,
        )
        evidence.extend(_write_process_evidence(preview_result, root, "audio-preview"))
        if not _process_findings(preview_result, "audio preview") and preview_path.is_file():
            if preview_path.stat().st_size <= _MAX_PREVIEW_BYTES:
                evidence.append(_relative(preview_path, root))
            else:
                preview_path.unlink(missing_ok=True)
                findings.append(
                    _finding(
                        "warning",
                        "audio.preview_too_large",
                        "The bounded MCP audio preview exceeded 32 MiB and was removed.",
                    )
                )

    volume_result = _run_process(
        [
            ffmpeg_bin,
            "-hide_banner",
            "-nostdin",
            "-i",
            str(audio_path),
            "-af",
            "volumedetect",
            "-f",
            "null",
            "-",
        ],
        root,
        timeout_seconds,
    )
    evidence.extend(_write_process_evidence(volume_result, root, "audio-volume"))
    volume_text = f"{volume_result.get('stdout', '')}\n{volume_result.get('stderr', '')}"
    volume = parse_volume_metrics(volume_text)
    for message in _process_findings(volume_result, "volume analysis"):
        findings.append(_finding("error", "audio.volume_analysis_failed", message))

    silence_filter = (
        f"silencedetect=noise={governed['silenceNoiseDb']}dB:"
        f"d={governed['minimumSilenceDurationSeconds']}"
    )
    silence_result = _run_process(
        [
            ffmpeg_bin,
            "-hide_banner",
            "-nostdin",
            "-i",
            str(audio_path),
            "-af",
            silence_filter,
            "-f",
            "null",
            "-",
        ],
        root,
        timeout_seconds,
    )
    evidence.extend(_write_process_evidence(silence_result, root, "audio-silence"))
    silence_text = f"{silence_result.get('stdout', '')}\n{silence_result.get('stderr', '')}"
    silence_segments = parse_silence_segments(silence_text, audio_duration or container_duration)
    for message in _process_findings(silence_result, "silence analysis"):
        findings.append(_finding("error", "audio.silence_analysis_failed", message))

    loudness_result = _run_process(
        [
            ffmpeg_bin,
            "-hide_banner",
            "-nostdin",
            "-i",
            str(audio_path),
            "-filter_complex",
            "ebur128=peak=true",
            "-f",
            "null",
            "-",
        ],
        root,
        timeout_seconds,
    )
    evidence.extend(_write_process_evidence(loudness_result, root, "audio-loudness"))
    loudness_text = (
        f"{loudness_result.get('stdout', '')}\n{loudness_result.get('stderr', '')}"
    )
    loudness = parse_loudness_metrics(loudness_text)
    for message in _process_findings(loudness_result, "loudness analysis"):
        findings.append(_finding("warning", "audio.loudness_analysis_failed", message))

    waveform = root / "waveform.png"
    waveform_result = _run_process(
        [
            ffmpeg_bin,
            "-hide_banner",
            "-nostdin",
            "-y",
            "-i",
            str(audio_path),
            "-filter_complex",
            "showwavespic=s=1200x320:split_channels=1",
            "-frames:v",
            "1",
            str(waveform),
        ],
        root,
        timeout_seconds,
    )
    evidence.extend(_write_process_evidence(waveform_result, root, "audio-waveform"))
    if waveform.is_file() and waveform.stat().st_size > 8:
        evidence.append(_relative(waveform, root))
    else:
        findings.append(
            _finding("warning", "audio.waveform_missing", "Audio waveform was not produced.")
        )

    spectrogram = root / "spectrogram.png"
    spectrum_result = _run_process(
        [
            ffmpeg_bin,
            "-hide_banner",
            "-nostdin",
            "-y",
            "-i",
            str(audio_path),
            "-lavfi",
            "showspectrumpic=s=1200x640:legend=1:scale=log",
            "-frames:v",
            "1",
            str(spectrogram),
        ],
        root,
        timeout_seconds,
    )
    evidence.extend(_write_process_evidence(spectrum_result, root, "audio-spectrogram"))
    if spectrogram.is_file() and spectrogram.stat().st_size > 8:
        evidence.append(_relative(spectrogram, root))
    else:
        findings.append(
            _finding(
                "warning", "audio.spectrogram_missing", "Audio spectrogram was not produced."
            )
        )

    duration_for_ratio = audio_duration or container_duration
    silence_seconds = sum(segment["durationSeconds"] for segment in silence_segments)
    silence_ratio = (
        min(1.0, silence_seconds / duration_for_ratio)
        if duration_for_ratio and duration_for_ratio > 0.0
        else None
    )
    measured_peaks = [
        value
        for value in (volume["peakDbfs"], loudness["truePeakDbfs"])
        if value is not None
    ]
    peak = max(measured_peaks) if measured_peaks else None
    audible = peak is not None and peak >= governed["minimumAudiblePeakDbfs"]
    if not audible:
        severity = "error" if governed["failOnSilence"] else "warning"
        findings.append(
            _finding(
                severity,
                "audio.effectively_silent",
                "The captured audio peak is below the governed audible threshold.",
            )
        )
    if peak is not None and peak > governed["maximumPeakDbfs"]:
        severity = "error" if governed["failOnClipping"] else "warning"
        findings.append(
            _finding(
                severity,
                "audio.peak_too_high",
                "The captured audio peak exceeds the governed clipping threshold.",
            )
        )
    if silence_ratio is not None and silence_ratio > governed["maximumSilenceRatio"]:
        severity = "error" if governed["failOnSilence"] else "warning"
        findings.append(
            _finding(
                severity,
                "audio.silence_ratio_high",
                "The captured audio contains more silence than the profile allows.",
            )
        )
    av_drift = (
        abs(audio_duration - video_duration)
        if audio_duration is not None and video_duration is not None
        else None
    )
    if av_drift is not None and av_drift > governed["maximumAvSyncDriftSeconds"]:
        severity = "error" if governed["failOnAvSyncDrift"] else "warning"
        findings.append(
            _finding(
                severity,
                "media.av_sync_drift",
                "Audio and video durations differ beyond the governed tolerance.",
            )
        )

    status = "failed" if any(item["severity"] == "error" for item in findings) else "passed"
    report = {
        "schemaVersion": "1.0",
        "status": status,
        "source": str(source),
        "sourceBytes": size,
        "sourceSha256": _sha256_file(source),
        "policy": governed,
        "streams": {
            "audio": audio_streams,
            "video": video_streams,
            "containerDurationSeconds": container_duration,
            "audioDurationSeconds": audio_duration,
            "videoDurationSeconds": video_duration,
            "avSyncDriftSeconds": av_drift,
        },
        "metrics": {
            **volume,
            **loudness,
            "audible": audible,
            "silenceSeconds": round(silence_seconds, 6),
            "silenceRatio": round(silence_ratio, 6) if silence_ratio is not None else None,
            "silenceSegments": silence_segments,
        },
        "findings": findings,
        "evidence": sorted(set(evidence)),
        "truthBoundary": (
            "The report measures the recorded Godot movie audio track, loudness, silence, peak "
            "and A/V duration. It supports audition and debugging but does not replace human "
            "judgment of mix, musical quality, spatialization, dialogue clarity or game feel."
        ),
    }
    report_path = root / "media-report.json"
    report_path.write_text(_canonical_json(report), encoding="utf-8")
    return report


def _is_within(candidate: Path, parent: Path) -> bool:
    try:
        candidate.relative_to(parent)
        return True
    except ValueError:
        return False


def scan_run_media(
    run_root: Path,
    output_root: Path | None = None,
    *,
    policy: dict[str, Any] | None = None,
    timeout_seconds: int = 300,
    ffmpeg: Path | None = None,
    ffprobe: Path | None = None,
) -> dict[str, Any]:
    source_root = run_root.expanduser().resolve(strict=True)
    if not source_root.is_dir() or source_root.is_symlink():
        raise NativeQaError(f"run root must be a regular directory: {source_root}")
    review_root = _safe_output_root(output_root or (source_root / "media-review"))
    media_files: list[Path] = []
    total_bytes = 0
    for path in sorted(source_root.rglob("*"), key=lambda item: item.as_posix().casefold()):
        if path.is_symlink() or not path.is_file():
            continue
        resolved = path.resolve()
        if _is_within(resolved, review_root):
            continue
        if path.suffix.casefold() not in _MEDIA_SUFFIXES:
            continue
        total_bytes += path.stat().st_size
        media_files.append(path)
        if len(media_files) > _MAX_MEDIA_FILES or total_bytes > _MAX_MEDIA_BYTES:
            raise NativeQaError("run media exceeds the bounded scan limits")

    items: list[dict[str, Any]] = []
    for index, media in enumerate(media_files):
        relative = media.relative_to(source_root).as_posix()
        item_root = review_root / "items" / f"{index:03d}-{media.stem[:48]}"
        result = analyze_media_file(
            media,
            item_root,
            policy=policy,
            timeout_seconds=timeout_seconds,
            ffmpeg=ffmpeg,
            ffprobe=ffprobe,
        )
        items.append(
            {
                "source": relative,
                "status": result["status"],
                "review": item_root.relative_to(review_root).as_posix(),
                "report": (item_root / "media-report.json").relative_to(review_root).as_posix(),
                "audioPreview": (
                    (item_root / "audio-preview.wav").relative_to(review_root).as_posix()
                    if (item_root / "audio-preview.wav").is_file()
                    else None
                ),
                "waveform": (
                    (item_root / "waveform.png").relative_to(review_root).as_posix()
                    if (item_root / "waveform.png").is_file()
                    else None
                ),
                "spectrogram": (
                    (item_root / "spectrogram.png").relative_to(review_root).as_posix()
                    if (item_root / "spectrogram.png").is_file()
                    else None
                ),
                "findings": result.get("findings", []),
            }
        )

    if not items:
        status = "blocked"
        findings = [
            _finding(
                "warning",
                "media.none_found",
                "No supported recorded movie was found beneath the run root.",
            )
        ]
    else:
        status = "failed" if any(item["status"] == "failed" for item in items) else "passed"
        findings = []
    summary = {
        "schemaVersion": "1.0",
        "status": status,
        "runRoot": str(source_root),
        "mediaFiles": len(items),
        "mediaBytes": total_bytes,
        "policy": normalize_media_policy(policy),
        "items": items,
        "findings": findings,
        "truthBoundary": (
            "Media review covers retained recordings only. A path that was not recorded cannot "
            "be visually or audibly assessed from this summary."
        ),
    }
    summary_path = review_root / "media-agent-summary.json"
    summary_path.write_text(_canonical_json(summary), encoding="utf-8")
    return summary


__all__ = [
    "analyze_media_file",
    "normalize_media_policy",
    "parse_loudness_metrics",
    "parse_silence_segments",
    "parse_volume_metrics",
    "scan_run_media",
]
