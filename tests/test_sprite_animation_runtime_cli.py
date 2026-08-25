from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from godot_game_test_lab.game_asset_delivery_common import hash_object
from godot_game_test_lab.sprite_animation_runtime_admission import AUTHORITY, EXPECTATION_SCHEMA
from godot_game_test_lab.sprite_animation_runtime_cli import run


def self_hash(value: dict, key: str) -> dict:
    value = json.loads(json.dumps(value))
    value[key] = hash_object(value)
    value["runId"] = value[key][:20]
    return value


def expectation() -> dict:
    return self_hash(
        {
            "schema": EXPECTATION_SCHEMA,
            "clipId": "walk-right",
            "animationDirectorPlanSha256": "a" * 64,
            "godotDescriptorSha256": "b" * 64,
            "frameIds": ["f1", "f2", "f3"],
            "frameDurationMicros": [125000, 250000, 125000],
            "framesPerSecond": 8,
            "loopMode": "linear",
            "maximumFrameTimingErrorMs": 20,
            "maximumPivotDriftPixels": 0,
            "authority": AUTHORITY,
        },
        "expectationSha256",
    )


def raw() -> dict:
    return {
        "status": "passed",
        "clipId": "walk-right",
        "godotVersion": "4.6.2.stable",
        "renderer": "gl_compatibility",
        "spriteFramesLoaded": True,
        "animationStarted": True,
        "configuredFramesPerSecond": 8.0,
        "loopMode": "linear",
        "completeCyclesObserved": 1,
        "frames": [
            {
                "frameId": "f1",
                "configuredDurationMicros": 125000,
                "observedDurationMs": 133.0,
                "pivot": {"x": 16.0, "y": 46.0},
                "rendered": True,
            },
            {
                "frameId": "f2",
                "configuredDurationMicros": 250000,
                "observedDurationMs": 258.0,
                "pivot": {"x": 16.0, "y": 46.0},
                "rendered": True,
            },
            {
                "frameId": "f3",
                "configuredDurationMicros": 125000,
                "observedDurationMs": 133.0,
                "pivot": {"x": 16.0, "y": 46.0},
                "rendered": True,
            },
        ],
        "importErrors": [],
        "consoleErrors": [],
    }


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def args(tmp_path: Path) -> argparse.Namespace:
    expectation_path = tmp_path / "expectation.json"
    raw_path = tmp_path / "raw.json"
    write_json(expectation_path, expectation())
    write_json(raw_path, raw())
    return argparse.Namespace(
        expectation=expectation_path,
        raw_telemetry=raw_path,
        evidence_output=tmp_path / "out" / "evidence.json",
        report_output=tmp_path / "out" / "report.json",
    )


def test_cli_run_creates_self_hashed_evidence_and_admission_report(tmp_path: Path) -> None:
    request = args(tmp_path)
    result = run(request)
    assert result["status"] == "passed"
    evidence = json.loads(request.evidence_output.read_text(encoding="utf-8"))
    report = json.loads(request.report_output.read_text(encoding="utf-8"))
    assert evidence["runId"] == evidence["evidenceSha256"][:20]
    assert report["runtimeEvidenceSha256"] == evidence["evidenceSha256"]
    assert report["expectationSha256"] == expectation()["expectationSha256"]


def test_cli_outputs_are_create_only_and_cannot_overwrite_inputs(tmp_path: Path) -> None:
    request = args(tmp_path)
    run(request)
    with pytest.raises(ValueError, match="output already exists"):
        run(request)

    request = args(tmp_path / "second")
    request.evidence_output = request.expectation
    with pytest.raises(ValueError, match="must not overwrite input evidence"):
        run(request)
