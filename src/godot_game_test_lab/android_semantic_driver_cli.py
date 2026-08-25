from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from .android_semantic_driver import AndroidSemanticDriverClient

SCHEMA = "evavo.godot.android-semantic-journey.v1"
MAX_STEPS = 256
MAX_WAIT_MS = 10_000
MAX_TOTAL_WAIT_MS = 120_000
MAX_EXPECTED_STATE_KEYS = 32
MAX_STATE_STRING_LENGTH = 128


def _valid_expected_value(value: Any) -> bool:
    if value is None or isinstance(value, (bool, int, float)):
        return True
    return isinstance(value, str) and len(value) <= MAX_STATE_STRING_LENGTH


def _validate_expected_state(value: Any, index: int) -> dict[str, Any]:
    if not isinstance(value, dict) or not 1 <= len(value) <= MAX_EXPECTED_STATE_KEYS:
        raise ValueError(f"step {index} assert-state expected must contain 1..{MAX_EXPECTED_STATE_KEYS} keys")
    normalized: dict[str, Any] = {}
    for key, expected in value.items():
        if not isinstance(key, str) or not 1 <= len(key) <= 64 or any(not (ch.isalnum() or ch in "_.:-") for ch in key):
            raise ValueError(f"step {index} assert-state key is invalid")
        if not _valid_expected_value(expected):
            raise ValueError(f"step {index} assert-state value for {key} is not a bounded scalar")
        normalized[key] = expected
    return normalized


def _load_journey(path: Path) -> list[dict[str, Any]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema") != SCHEMA:
        raise ValueError(f"journey schema must be {SCHEMA}")
    steps = value.get("steps")
    if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_STEPS:
        raise ValueError(f"journey steps must contain 1..{MAX_STEPS} entries")
    normalized: list[dict[str, Any]] = []
    total_wait = 0
    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            raise ValueError(f"step {index} must be an object")
        kind = step.get("type")
        if kind not in {"press", "release", "pulse", "wait", "state", "assert-state"}:
            raise ValueError(f"step {index} has unsupported type")
        current = dict(step)
        if kind == "wait":
            milliseconds = step.get("milliseconds", 0)
            if not isinstance(milliseconds, int) or isinstance(milliseconds, bool):
                raise ValueError(f"step {index} wait must use integer milliseconds")
            if not 0 <= milliseconds <= MAX_WAIT_MS:
                raise ValueError(f"step {index} wait exceeds {MAX_WAIT_MS}ms")
            total_wait += milliseconds
            if total_wait > MAX_TOTAL_WAIT_MS:
                raise ValueError("journey cumulative wait exceeds 120 seconds")
        if kind == "assert-state":
            current["expected"] = _validate_expected_state(step.get("expected"), index)
        normalized.append(current)
    return normalized


def _assert_project_state(response: dict[str, Any], expected: dict[str, Any], index: int) -> dict[str, Any]:
    observed = response.get("projectState")
    if not isinstance(observed, dict):
        raise AssertionError(f"step {index} target did not expose projectState")
    mismatches: list[dict[str, Any]] = []
    for key, expected_value in expected.items():
        if key not in observed:
            mismatches.append({"key": key, "reason": "missing"})
            continue
        if observed[key] != expected_value:
            mismatches.append({"key": key, "reason": "not_equal", "expected": expected_value, "observed": observed[key]})
    if mismatches:
        compact = ", ".join(f"{entry['key']}:{entry['reason']}" for entry in mismatches)
        raise AssertionError(f"step {index} project-state assertion failed: {compact}")
    return {"matched": True, "expected": expected, "observed": {key: observed[key] for key in expected}}


def run_journey(port: int, steps: list[dict[str, Any]]) -> dict[str, Any]:
    started = time.monotonic()
    records: list[dict[str, Any]] = []
    assertion_count = 0
    with AndroidSemanticDriverClient(port) as client:
        records.append({"index": -1, "type": "initial-state", "response": client.state()})
        for index, step in enumerate(steps):
            kind = str(step["type"])
            if kind == "wait":
                milliseconds = int(step.get("milliseconds", 0))
                time.sleep(milliseconds / 1000.0)
                response: dict[str, Any] = {"waitedMs": milliseconds}
            elif kind == "state":
                response = client.state()
            elif kind == "assert-state":
                state = client.state()
                response = {"state": state, "assertion": _assert_project_state(state, dict(step["expected"]), index)}
                assertion_count += 1
            elif kind == "press":
                response = client.press(
                    str(step.get("action", "")),
                    strength=float(step.get("strength", 1.0)),
                )
            elif kind == "release":
                response = client.release(str(step.get("action", "")))
            else:
                response = client.pulse(
                    str(step.get("action", "")),
                    duration_ms=int(step.get("durationMs", 100)),
                    strength=float(step.get("strength", 1.0)),
                )
            records.append({"index": index, "type": kind, "response": response})
        final_state = client.state()
    return {
        "schema": "evavo.godot.android-semantic-journey-result.v1",
        "ok": True,
        "port": port,
        "stepCount": len(steps),
        "assertionCount": assertion_count,
        "elapsedMs": round((time.monotonic() - started) * 1000),
        "records": records,
        "finalState": final_state,
        "truth": {
            "physicalAndroidBuild": True,
            "semanticInput": True,
            "projectStateAssertions": assertion_count > 0,
            "rawCoordinatesUsed": False,
            "androidShellExposed": False,
            "arbitraryNodeInspection": False,
            "physicalTouchscreenErgonomicsClaimed": False,
            "releaseBuildClaimed": False,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a bounded Godot semantic journey over loopback.")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--journey", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    steps = _load_journey(args.journey)
    result = run_journey(args.port, steps)
    encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
