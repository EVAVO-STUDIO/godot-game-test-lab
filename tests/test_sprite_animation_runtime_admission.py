from __future__ import annotations

import copy

import pytest

from godot_game_test_lab.game_asset_delivery_common import hash_object
from godot_game_test_lab.sprite_animation_runtime_admission import (
    AUTHORITY,
    EVIDENCE_SCHEMA,
    EXPECTATION_SCHEMA,
    admit_sprite_animation_runtime,
)


def _self_hash(value: dict, key: str) -> dict:
    body = copy.deepcopy(value)
    body[key] = hash_object(body)
    body["runId"] = body[key][:20]
    return body


def expectation() -> dict:
    return _self_hash(
        {
            "schema": EXPECTATION_SCHEMA,
            "clipId": "hero-walk-right",
            "animationDirectorPlanSha256": "a" * 64,
            "godotDescriptorSha256": "b" * 64,
            "frameIds": [f"hero-walk-right:f{index:03d}" for index in range(1, 9)],
            "framesPerSecond": 8,
            "loopMode": "linear",
            "maximumFrameTimingErrorMs": 3,
            "maximumPivotDriftPixels": 0.25,
            "authority": AUTHORITY,
        },
        "expectationSha256",
    )


def evidence() -> dict:
    return _self_hash(
        {
            "schema": EVIDENCE_SCHEMA,
            "status": "passed",
            "clipId": "hero-walk-right",
            "godotVersion": "4.6.2.stable",
            "renderer": "Forward+",
            "spriteFramesLoaded": True,
            "animationStarted": True,
            "loopMode": "linear",
            "completeCyclesObserved": 2,
            "frames": [
                {
                    "frameId": f"hero-walk-right:f{index:03d}",
                    "observedDurationMs": 125.0,
                    "pivot": {"x": 48.0, "y": 120.0},
                    "rendered": True,
                }
                for index in range(1, 9)
            ],
            "importErrors": [],
            "consoleErrors": [],
            "authority": AUTHORITY,
        },
        "evidenceSha256",
    )


def test_accepts_exact_target_owned_runtime_telemetry() -> None:
    report = admit_sprite_animation_runtime(expectation(), evidence())
    assert report["status"] == "passed"
    assert report["frameIds"][0] == "hero-walk-right:f001"
    assert report["completeCyclesObserved"] == 2
    assert report["truthBoundary"]["runtimeTelemetryValidated"] is True
    assert report["truthBoundary"]["humanVisualApproval"] is False


def test_rejects_wrong_frame_order_and_missing_cycle() -> None:
    wrong_order = evidence()
    unsigned = {k: v for k, v in wrong_order.items() if k not in {"evidenceSha256", "runId"}}
    unsigned["frames"][0], unsigned["frames"][1] = unsigned["frames"][1], unsigned["frames"][0]
    wrong_order = _self_hash(unsigned, "evidenceSha256")
    with pytest.raises(ValueError, match="frame order"):
        admit_sprite_animation_runtime(expectation(), wrong_order)

    no_cycle = evidence()
    unsigned = {k: v for k, v in no_cycle.items() if k not in {"evidenceSha256", "runId"}}
    unsigned["completeCyclesObserved"] = 0
    no_cycle = _self_hash(unsigned, "evidenceSha256")
    with pytest.raises(ValueError, match="complete observed cycle"):
        admit_sprite_animation_runtime(expectation(), no_cycle)


def test_rejects_timing_or_pivot_drift() -> None:
    slow = evidence()
    unsigned = {k: v for k, v in slow.items() if k not in {"evidenceSha256", "runId"}}
    unsigned["frames"][3]["observedDurationMs"] = 140.0
    slow = _self_hash(unsigned, "evidenceSha256")
    with pytest.raises(ValueError, match="frame timing"):
        admit_sprite_animation_runtime(expectation(), slow)

    drifting = evidence()
    unsigned = {k: v for k, v in drifting.items() if k not in {"evidenceSha256", "runId"}}
    unsigned["frames"][5]["pivot"]["x"] = 49.0
    drifting = _self_hash(unsigned, "evidenceSha256")
    with pytest.raises(ValueError, match="pivot drift"):
        admit_sprite_animation_runtime(expectation(), drifting)


def test_rejects_mutated_self_hashed_inputs_and_false_authority() -> None:
    changed = evidence()
    changed["frames"][0]["rendered"] = False
    with pytest.raises(ValueError, match="does not match canonical content"):
        admit_sprite_animation_runtime(expectation(), changed)

    unsafe = expectation()
    unsigned = {k: v for k, v in unsafe.items() if k not in {"expectationSha256", "runId"}}
    unsigned["authority"] = {**AUTHORITY, "publication": True}
    unsafe = _self_hash(unsigned, "expectationSha256")
    with pytest.raises(ValueError, match="must remain all false"):
        admit_sprite_animation_runtime(unsafe, evidence())
