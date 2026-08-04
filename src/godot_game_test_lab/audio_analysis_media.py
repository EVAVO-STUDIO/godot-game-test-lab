from __future__ import annotations

import json
import math
import shutil
import wave
from pathlib import Path, PurePosixPath
from typing import Any

from .audio_analysis_io import _read_regular, _run
from .audio_analysis_types import AudioAnalysisVerificationError


def _wav_metadata(path_value: Path) -> dict[str, Any]:
    try:
        with wave.open(str(path_value), "rb") as source:
            channels = source.getnchannels()
            sample_rate = source.getframerate()
            sample_width = source.getsampwidth()
            frame_count = source.getnframes()
            compression = source.getcomptype()
    except (OSError, EOFError, wave.Error) as error:
        raise AudioAnalysisVerificationError(
            f"WAV metadata could not be decoded: {path_value}"
        ) from error
    if compression != "NONE" or channels < 1 or sample_rate < 1 or frame_count < 1:
        raise AudioAnalysisVerificationError("WAV metadata is invalid")
    bit_depth = sample_width * 8
    codec = {
        8: "pcm_u8",
        16: "pcm_s16le",
        24: "pcm_s24le",
        32: "pcm_s32le",
    }.get(bit_depth, f"pcm_{bit_depth}")
    return {
        "codec": codec,
        "format": "wav",
        "sampleRateHz": sample_rate,
        "bitDepth": bit_depth,
        "channels": channels,
        "durationSeconds": frame_count / sample_rate,
    }


def _ffprobe_metadata(path_value: Path) -> dict[str, Any]:
    executable = shutil.which("ffprobe")
    if executable is None:
        raise AudioAnalysisVerificationError(
            "FFprobe is required to verify compressed runtime audio"
        )
    output, _ = _run(
        [
            executable,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path_value),
        ],
        timeout=90,
    )
    try:
        document = json.loads(str(output))
    except json.JSONDecodeError as error:
        raise AudioAnalysisVerificationError(
            "FFprobe did not return valid JSON"
        ) from error
    streams = document.get("streams")
    format_row = document.get("format")
    if not isinstance(streams, list) or not isinstance(format_row, dict):
        raise AudioAnalysisVerificationError("FFprobe response is incomplete")
    audio = [
        row
        for row in streams
        if isinstance(row, dict) and row.get("codec_type") == "audio"
    ]
    if len(audio) != 1:
        raise AudioAnalysisVerificationError(
            "Selected runtime audio must contain exactly one audio stream"
        )
    row = audio[0]
    duration_source = row.get("duration") or format_row.get("duration")
    try:
        duration = float(duration_source)
        sample_rate = int(row.get("sample_rate"))
        channels = int(row.get("channels"))
    except (TypeError, ValueError) as error:
        raise AudioAnalysisVerificationError(
            "FFprobe numeric metadata is invalid"
        ) from error
    if not math.isfinite(duration) or duration <= 0 or sample_rate <= 0 or channels <= 0:
        raise AudioAnalysisVerificationError("FFprobe metadata is invalid")
    bit_depth_source = row.get("bits_per_raw_sample") or row.get("bits_per_sample")
    try:
        bit_depth = int(bit_depth_source or 0)
    except (TypeError, ValueError):
        bit_depth = 0
    return {
        "codec": str(row.get("codec_name") or "unknown"),
        "format": str(format_row.get("format_name") or "unknown"),
        "sampleRateHz": sample_rate,
        "bitDepth": max(bit_depth, 0),
        "channels": channels,
        "durationSeconds": duration,
    }


def _metadata(path_value: Path) -> dict[str, Any]:
    if path_value.suffix.casefold() == ".wav":
        return _wav_metadata(path_value)
    return _ffprobe_metadata(path_value)


def _parse_godot_import(source: str) -> dict[str, str]:
    section: str | None = None
    values: dict[str, str] = {}
    for raw in source.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip().casefold()
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().casefold()
        value = value.strip().strip('"')
        if section == "params":
            values[key] = value
        elif section == "deps" and key == "source_file":
            values["__source_file"] = value
        elif section == "remap" and key == "importer":
            values["__importer"] = value
    return values


def _import_evidence(repository: Path, relative: str) -> dict[str, Any]:
    relative_import = f"{relative}.import"
    path_value = repository.joinpath(*PurePosixPath(relative_import).parts)
    if not path_value.exists():
        return {
            "path": relative_import,
            "present": False,
            "sha256": None,
            "bytes": 0,
            "parameters": {},
        }
    _, size, digest, payload = _read_regular(
        path_value,
        f"Godot import {relative_import}",
        1024 * 1024,
        retain_payload=True,
    )
    assert payload is not None
    try:
        parameters = _parse_godot_import(payload.decode("utf-8", errors="strict"))
    except UnicodeError as error:
        raise AudioAnalysisVerificationError(
            f"Godot import is not UTF-8: {relative_import}"
        ) from error
    return {
        "path": relative_import,
        "present": True,
        "sha256": digest,
        "bytes": size,
        "parameters": parameters,
    }


def _import_blockers(
    relative: str,
    role: dict[str, Any],
    evidence: dict[str, Any],
) -> list[str]:
    if not evidence["present"]:
        return ["godot-import-settings-missing"]
    parameters = evidence["parameters"]
    blockers: list[str] = []
    if parameters.get("__source_file") != f"res://{relative}":
        blockers.append("godot-import-source-identity-mismatch")
    suffix = PurePosixPath(relative).suffix.casefold()
    if suffix == ".wav":
        if parameters.get("__importer") != "wav":
            blockers.append("godot-wav-importer-required")
        if parameters.get("compress/mode", "0") != "0":
            blockers.append("godot-wav-pcm-import-required")
        for key in (
            "force/8_bit",
            "force/mono",
            "force/max_rate",
            "edit/trim",
            "edit/normalize",
        ):
            if parameters.get(key, "false").casefold() != "false":
                blockers.append(
                    f"godot-import-{key.replace('/', '-')}-must-be-false"
                )
        try:
            loop_enabled = int(parameters.get("edit/loop_mode", "0")) >= 2
        except ValueError:
            loop_enabled = False
    else:
        loop_enabled = parameters.get("loop", "false").casefold() == "true"
    if role["loopRequired"] and not loop_enabled:
        blockers.append("godot-loop-import-disabled")
    if not role["loopRequired"] and loop_enabled:
        blockers.append("unexpected-godot-loop-import")
    return blockers


def _close(left: Any, right: Any, *, tolerance: float = 1e-6) -> bool:
    if left is None or right is None:
        return left is right
    if isinstance(left, bool) or isinstance(right, bool):
        return left is right
    if not isinstance(left, int | float) or not isinstance(right, int | float):
        return left == right
    return abs(float(left) - float(right)) <= tolerance
