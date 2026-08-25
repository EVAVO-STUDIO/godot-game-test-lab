"""Generic runtime admission for target-owned Godot sprite animation evidence."""
from __future__ import annotations

from typing import Any

from .game_asset_delivery_common import (
    _all_false,
    _hash,
    _object,
    _positive_int,
    _text,
    _version_tuple,
    hash_object,
)

EXPECTATION_SCHEMA = "evavo.godot-sprite-animation-runtime-expectation.v1"
EVIDENCE_SCHEMA = "evavo.godot-sprite-animation-runtime-evidence.v1"
REPORT_SCHEMA = "evavo.godot-sprite-animation-runtime-admission.v1"

AUTHORITY = {
    "automaticApproval": False,
    "creativeApproval": False,
    "nativeVisualApproval": False,
    "candidatePromotion": False,
    "gameRepositoryMutation": False,
    "gitCommit": False,
    "gitPush": False,
    "publication": False,
    "forcePush": False,
}

_LOOP_MODES = {"none", "linear", "ping-pong"}


def _positive_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ValueError(f"{label} must be a finite number greater than zero")
    result = float(value)
    if result != result or result in {float("inf"), float("-inf")}:
        raise ValueError(f"{label} must be finite")
    return result


def _non_negative_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ValueError(f"{label} must be a finite number greater than or equal to zero")
    result = float(value)
    if result != result or result in {float("inf"), float("-inf")}:
        raise ValueError(f"{label} must be finite")
    return result


def _string_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{label} must be a non-empty array")
    result: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        text = _text(item, f"{label}[{index}]", 256)
        if text in seen:
            raise ValueError(f"{label} contains duplicate value {text}")
        seen.add(text)
        result.append(text)
    return result


def _positive_int_list(value: Any, label: str) -> list[int]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{label} must be a non-empty array")
    return [_positive_int(item, f"{label}[{index}]") for index, item in enumerate(value)]


def _pivot(value: Any, label: str) -> tuple[float, float]:
    item = _object(value, label)
    x = item.get("x")
    y = item.get("y")
    for axis, coordinate in (("x", x), ("y", y)):
        if isinstance(coordinate, bool) or not isinstance(coordinate, (int, float)):
            raise ValueError(f"{label}.{axis} must be finite")
        number = float(coordinate)
        if number != number or number in {float("inf"), float("-inf")}:
            raise ValueError(f"{label}.{axis} must be finite")
    return float(x), float(y)


def _runtime_frames(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise ValueError("evidence.frames must be a non-empty array")
    result: list[dict[str, Any]] = []
    for index, raw in enumerate(value):
        frame = _object(raw, f"evidence.frames[{index}]")
        result.append(
            {
                "frameId": _text(frame.get("frameId"), f"evidence.frames[{index}].frameId", 256),
                "observedDurationMs": _positive_number(
                    frame.get("observedDurationMs"),
                    f"evidence.frames[{index}].observedDurationMs",
                ),
                "pivot": _pivot(frame.get("pivot"), f"evidence.frames[{index}].pivot"),
                "rendered": frame.get("rendered") is True,
            }
        )
    return result


def _verify_self_hash(value: dict[str, Any], key: str, label: str) -> str:
    stored = _hash(value.get(key), f"{label}.{key}")
    unsigned = dict(value)
    unsigned.pop(key, None)
    unsigned.pop("runId", None)
    if hash_object(unsigned) != stored:
        raise ValueError(f"{label}.{key} does not match canonical content")
    if value.get("runId") != stored[:20]:
        raise ValueError(f"{label}.runId does not match {key}")
    return stored


def admit_sprite_animation_runtime(
    expectation: dict[str, Any],
    evidence: dict[str, Any],
) -> dict[str, Any]:
    """Compare target-owned runtime telemetry with an exact animation expectation."""
    expected = _object(expectation, "expectation")
    observed = _object(evidence, "evidence")
    if expected.get("schema") != EXPECTATION_SCHEMA:
        raise ValueError(f"expectation.schema must be {EXPECTATION_SCHEMA}")
    if observed.get("schema") != EVIDENCE_SCHEMA:
        raise ValueError(f"evidence.schema must be {EVIDENCE_SCHEMA}")
    expectation_sha = _verify_self_hash(expected, "expectationSha256", "expectation")
    evidence_sha = _verify_self_hash(observed, "evidenceSha256", "evidence")
    _all_false(expected.get("authority"), "expectation.authority")
    _all_false(observed.get("authority"), "evidence.authority")

    clip_id = _text(expected.get("clipId"), "expectation.clipId", 256)
    frame_ids = _string_list(expected.get("frameIds"), "expectation.frameIds")
    frame_duration_micros = _positive_int_list(
        expected.get("frameDurationMicros"),
        "expectation.frameDurationMicros",
    )
    if len(frame_duration_micros) != len(frame_ids):
        raise ValueError("expectation.frameDurationMicros must match frameIds length")
    fps = _positive_number(expected.get("framesPerSecond"), "expectation.framesPerSecond")
    loop_mode = _text(expected.get("loopMode"), "expectation.loopMode", 32)
    if loop_mode not in _LOOP_MODES:
        raise ValueError("expectation.loopMode is unsupported")
    timing_tolerance = _positive_number(
        expected.get("maximumFrameTimingErrorMs", 2.0),
        "expectation.maximumFrameTimingErrorMs",
    )
    pivot_tolerance = _non_negative_number(
        expected.get("maximumPivotDriftPixels", 0.0),
        "expectation.maximumPivotDriftPixels",
    )

    if observed.get("status") != "passed":
        raise ValueError("runtime evidence did not pass")
    if observed.get("clipId") != clip_id:
        raise ValueError("runtime evidence clipId differs")
    godot_version = _text(observed.get("godotVersion"), "evidence.godotVersion", 256)
    if _version_tuple(godot_version) < (4, 6, 2):
        raise ValueError("runtime evidence uses unsupported Godot version")
    renderer = _text(observed.get("renderer"), "evidence.renderer", 256)
    if observed.get("spriteFramesLoaded") is not True:
        raise ValueError("runtime evidence did not load SpriteFrames")
    if observed.get("animationStarted") is not True:
        raise ValueError("runtime evidence did not start the animation")
    if observed.get("importErrors") not in ([], None):
        raise ValueError("runtime evidence contains import errors")
    if observed.get("consoleErrors") not in ([], None):
        raise ValueError("runtime evidence contains console errors")
    if observed.get("loopMode") != loop_mode:
        raise ValueError("runtime loop mode differs from expectation")

    frames = _runtime_frames(observed.get("frames"))
    observed_ids = [frame["frameId"] for frame in frames]
    if observed_ids != frame_ids:
        raise ValueError("runtime frame order differs from expectation")
    if not all(frame["rendered"] for frame in frames):
        raise ValueError("runtime evidence did not render every expected frame")

    timing_failures = []
    for index, frame in enumerate(frames):
        expected_duration_ms = frame_duration_micros[index] / 1000.0
        error_ms = abs(frame["observedDurationMs"] - expected_duration_ms)
        if error_ms > timing_tolerance:
            timing_failures.append(
                {
                    "frameId": frame["frameId"],
                    "observedDurationMs": frame["observedDurationMs"],
                    "expectedDurationMs": expected_duration_ms,
                    "absoluteErrorMs": error_ms,
                }
            )
    if timing_failures:
        raise ValueError("runtime frame timing differs beyond expectation tolerance")

    anchor = frames[0]["pivot"]
    pivot_failures = []
    for frame in frames[1:]:
        dx = abs(frame["pivot"][0] - anchor[0])
        dy = abs(frame["pivot"][1] - anchor[1])
        if dx > pivot_tolerance or dy > pivot_tolerance:
            pivot_failures.append({"frameId": frame["frameId"], "dx": dx, "dy": dy})
    if pivot_failures:
        raise ValueError("runtime pivot drift exceeds expectation tolerance")

    loops_observed = _positive_int(
        observed.get("completeCyclesObserved"),
        "evidence.completeCyclesObserved",
        allow_zero=True,
    )
    if loop_mode != "none" and loops_observed < 1:
        raise ValueError("looping animation evidence lacks a complete observed cycle")

    plan_sha = _hash(
        expected.get("animationDirectorPlanSha256"),
        "animationDirectorPlanSha256",
    )
    descriptor_sha = _hash(
        expected.get("godotDescriptorSha256"),
        "godotDescriptorSha256",
    )

    body = {
        "schema": REPORT_SCHEMA,
        "status": "passed",
        "clipId": clip_id,
        "expectationSha256": expectation_sha,
        "animationDirectorPlanSha256": plan_sha,
        "godotDescriptorSha256": descriptor_sha,
        "runtimeEvidenceSha256": evidence_sha,
        "godotVersion": godot_version,
        "renderer": renderer,
        "frameIds": frame_ids,
        "frameDurationMicros": frame_duration_micros,
        "framesPerSecond": fps,
        "loopMode": loop_mode,
        "completeCyclesObserved": loops_observed,
        "timingToleranceMs": timing_tolerance,
        "pivotTolerancePixels": pivot_tolerance,
        "truthBoundary": {
            "sourceContractValidated": True,
            "runtimeTelemetryValidated": True,
            "humanVisualApproval": False,
            "gameFeelApproval": False,
            "physicalControllerApproval": False,
        },
        "authority": AUTHORITY,
    }
    return {**body, "reportSha256": hash_object(body)}
