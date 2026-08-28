from __future__ import annotations

import copy

import pytest

from godot_game_test_lab.game_asset_delivery_common import hash_object
from godot_game_test_lab.sprite_animation_runtime_admission import (
    AUTHORITY,
    EXPECTATION_SCHEMA,
    admit_sprite_animation_runtime,
    compile_sprite_animation_runtime_evidence,
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
            "frameDurationMicros": [
                125000,
                125000,
                250000,
                125000,
                125000,
                125000,
                250000,
                125000,
            ],
            "framesPerSecond": 8,
            "loopMode": "linear",
            "maximumFrameTimingErrorMs": 20,
            "maximumPivotDriftPixels": 0,
            "authority": AUTHORITY,
        },
        "expectationSha256",
    )


def raw_telemetry() -> dict:
    duration_micros = [
        125000,
        125000,
        250000,
        125000,
        125000,
        125000,
        250000,
        125000,
    ]
    observed = [133.0, 124.0, 258.0, 126.0, 133.0, 124.0, 258.0, 126.0]
    return {
        "status": "passed",
        "clipId": "hero-walk-right",
        "godotVersion": "4.6.2.stable",
        "renderer": "Forward+",
        "spriteFramesLoaded": True,
        "animationStarted": True,
        "configuredFramesPerSecond": 8.0,
        "loopMode": "linear",
        "completeCyclesObserved": 2,
        "frames": [
            {
                "frameId": f"hero-walk-right:f{index:03d}",
                "configuredDurationMicros": duration_micros[index - 1],
                "observedDurationMs": observed[index - 1],
                "pivot": {"x": 48.0, "y": 120.0},
                "rendered": True,
            }
            for index in range(1, 9)
        ],
        "importErrors": [],
        "consoleErrors": [],
    }


def evidence(expectation_doc: dict | None = None) -> dict:
    expected = expectation_doc or expectation()
    return compile_sprite_animation_runtime_evidence(
        raw_telemetry(),
        expected["expectationSha256"],
    )


def test_compiles_self_hashed_evidence_bound_to_exact_expectation() -> None:
    expected = expectation()
    compiled = evidence(expected)
    assert compiled["expectationSha256"] == expected["expectationSha256"]
    assert compiled["runId"] == compiled["evidenceSha256"][:20]
    assert compiled["authority"] == AUTHORITY
    assert compiled["configuredFramesPerSecond"] == 8.0
    assert compiled["frames"][2]["configuredDurationMicros"] == 250000


def test_accepts_exact_runtime_configuration_with_scheduler_tolerant_cadence(
) -> None:
    expected = expectation()
    report = admit_sprite_animation_runtime(expected, evidence(expected))
    assert report["status"] == "passed"
    assert report["frameIds"][0] == "hero-walk-right:f001"
    assert report["frameDurationMicros"][2] == 250000
    assert report["configuredFramesPerSecond"] == 8.0
    assert report["completeCyclesObserved"] == 2
    assert report["truthBoundary"]["spriteFramesConfigurationValidated"] is True
    assert report["truthBoundary"]["runtimeTelemetryValidated"] is True
    assert report["truthBoundary"]["humanVisualApproval"] is False


def test_rejects_wrong_frame_order_and_missing_cycle() -> None:
    expected = expectation()
    wrong = raw_telemetry()
    wrong["frames"][0], wrong["frames"][1] = wrong["frames"][1], wrong["frames"][0]
    with pytest.raises(ValueError, match="frame order"):
        admit_sprite_animation_runtime(
            expected,
            compile_sprite_animation_runtime_evidence(
                wrong,
                expected["expectationSha256"],
            ),
        )

    no_cycle = raw_telemetry()
    no_cycle["completeCyclesObserved"] = 0
    with pytest.raises(ValueError, match="complete observed cycle"):
        admit_sprite_animation_runtime(
            expected,
            compile_sprite_animation_runtime_evidence(
                no_cycle,
                expected["expectationSha256"],
            ),
        )


def test_rejects_wrong_configured_fps_or_frame_duration() -> None:
    expected = expectation()
    wrong_fps = raw_telemetry()
    wrong_fps["configuredFramesPerSecond"] = 9.0
    with pytest.raises(ValueError, match="FPS differs"):
        admit_sprite_animation_runtime(
            expected,
            compile_sprite_animation_runtime_evidence(
                wrong_fps,
                expected["expectationSha256"],
            ),
        )

    wrong_duration = raw_telemetry()
    wrong_duration["frames"][2]["configuredDurationMicros"] = 125000
    with pytest.raises(ValueError, match="configured durations differ"):
        admit_sprite_animation_runtime(
            expected,
            compile_sprite_animation_runtime_evidence(
                wrong_duration,
                expected["expectationSha256"],
            ),
        )


def test_rejects_large_observed_cadence_error_or_pivot_drift() -> None:
    expected = expectation()
    slow = raw_telemetry()
    slow["frames"][2]["observedDurationMs"] = 300.0
    with pytest.raises(ValueError, match="observed frame cadence"):
        admit_sprite_animation_runtime(
            expected,
            compile_sprite_animation_runtime_evidence(
                slow,
                expected["expectationSha256"],
            ),
        )

    drifting = raw_telemetry()
    drifting["frames"][5]["pivot"]["x"] = 49.0
    with pytest.raises(ValueError, match="pivot drift"):
        admit_sprite_animation_runtime(
            expected,
            compile_sprite_animation_runtime_evidence(
                drifting,
                expected["expectationSha256"],
            ),
        )


def test_rejects_duration_count_and_expectation_binding_mismatch() -> None:
    broken = expectation()
    unsigned = {
        key: value
        for key, value in broken.items()
        if key not in {"expectationSha256", "runId"}
    }
    unsigned["frameDurationMicros"] = unsigned["frameDurationMicros"][:-1]
    broken = _self_hash(unsigned, "expectationSha256")
    with pytest.raises(ValueError, match="must match frameIds length"):
        admit_sprite_animation_runtime(broken, evidence(broken))

    expected = expectation()
    other = _self_hash(
        {
            **{
                key: value
                for key, value in expected.items()
                if key not in {"expectationSha256", "runId"}
            },
            "clipId": "different-clip",
        },
        "expectationSha256",
    )
    with pytest.raises(ValueError, match="different expectation"):
        admit_sprite_animation_runtime(other, evidence(expected))


def test_rejects_mutated_self_hashed_inputs_and_bad_raw_data() -> None:
    expected = expectation()
    changed = evidence(expected)
    changed["frames"][0]["rendered"] = False
    with pytest.raises(ValueError, match="does not match canonical content"):
        admit_sprite_animation_runtime(expected, changed)

    with pytest.raises(ValueError, match="raw.status"):
        compile_sprite_animation_runtime_evidence(
            {**raw_telemetry(), "status": "maybe"},
            expected["expectationSha256"],
        )
