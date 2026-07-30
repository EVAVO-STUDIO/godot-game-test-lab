#!/usr/bin/env python3
"""Extend the canonical agent QA runner with marker-bound process-exit journeys."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

HERE = Path(__file__).resolve().parent
BASE_RUNNER = HERE / "run_agent_godot_qa.py"
COMPLETION_ARGUMENT = "--evavo-agent-completion=process-exit"
REQUIRED_MARKER_PREFIX = "--evavo-agent-require-output="
FORBIDDEN_MARKER_PREFIX = "--evavo-agent-forbid-output="
MISSING_REPORT_FINDING = "journey report was not produced"
MAX_MARKER_BYTES = 192


def _load_base_runner() -> ModuleType:
    spec = importlib.util.spec_from_file_location("evavo_agent_qa_base", BASE_RUNNER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not import canonical agent QA runner: {BASE_RUNNER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BASE = _load_base_runner()
ORIGINAL_RUN_JOURNEY = BASE._run_journey


def _bounded_marker(value: str, label: str) -> str:
    marker = value.strip()
    if (
        not marker
        or "\x00" in marker
        or "\n" in marker
        or "\r" in marker
        or len(marker.encode("utf-8")) > MAX_MARKER_BYTES
    ):
        raise ValueError(f"{label} must be a non-empty bounded single-line marker.")
    return marker


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def split_process_exit_contract(
    journey: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    delegated = dict(journey)
    raw_arguments = journey.get("userArguments", [])
    if not isinstance(raw_arguments, list):
        raise ValueError("journey.userArguments must be an array.")

    passthrough: list[str] = []
    required_markers: list[str] = []
    forbidden_markers: list[str] = []
    process_exit = False

    for index, raw_argument in enumerate(raw_arguments):
        if not isinstance(raw_argument, str):
            raise ValueError(f"journey.userArguments[{index}] must be a string.")
        if raw_argument == COMPLETION_ARGUMENT:
            process_exit = True
            continue
        if raw_argument.startswith(REQUIRED_MARKER_PREFIX):
            marker = _bounded_marker(
                raw_argument[len(REQUIRED_MARKER_PREFIX) :],
                f"journey.userArguments[{index}] required marker",
            )
            _append_unique(required_markers, marker)
            continue
        if raw_argument.startswith(FORBIDDEN_MARKER_PREFIX):
            marker = _bounded_marker(
                raw_argument[len(FORBIDDEN_MARKER_PREFIX) :],
                f"journey.userArguments[{index}] forbidden marker",
            )
            _append_unique(forbidden_markers, marker)
            continue
        if raw_argument.startswith("--evavo-agent-"):
            raise ValueError(
                f"journey.userArguments[{index}] uses an unsupported EVAVO agent argument."
            )
        passthrough.append(raw_argument)

    if not process_exit:
        if required_markers or forbidden_markers:
            raise ValueError(
                "Process-exit output markers require "
                f"{COMPLETION_ARGUMENT}."
            )
        return delegated, None
    if not required_markers:
        raise ValueError("A process-exit journey requires at least one output marker.")

    delegated["userArguments"] = passthrough
    return delegated, {
        "mode": "process-exit",
        "requiredOutputMarkers": required_markers,
        "forbiddenOutputMarkers": forbidden_markers,
    }


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _output_lines(stdout: str, stderr: str) -> set[str]:
    return set(stdout.splitlines()) | set(stderr.splitlines())


def _without_missing_report(findings: list[Any]) -> list[str]:
    return [
        str(finding)
        for finding in findings
        if str(finding) != MISSING_REPORT_FINDING
    ]


def _apply_process_exit_contract(
    result: dict[str, Any],
    contract: dict[str, Any],
    artifacts: Path,
    journey_id: str,
) -> dict[str, Any]:
    root = artifacts / "journeys" / journey_id
    review_path = root / "visual-ux-review.json"
    review = _load_json(review_path)

    stdout = _read_text(root / "logs" / "journey.stdout.log")
    stderr = _read_text(root / "logs" / "journey.stderr.log")
    output_lines = _output_lines(stdout, stderr)
    required_markers = list(contract["requiredOutputMarkers"])
    forbidden_markers = list(contract["forbiddenOutputMarkers"])
    missing_markers = [marker for marker in required_markers if marker not in output_lines]
    observed_forbidden = [marker for marker in forbidden_markers if marker in output_lines]

    process = review.get("process", {})
    if not isinstance(process, dict):
        process = {}
    completion_findings: list[str] = []
    if process.get("timedOut") is True:
        completion_findings.append("process-exit journey exceeded its bounded timeout")
    if process.get("exitCode") != 0:
        completion_findings.append(
            f"process-exit journey expected exit code 0, found {process.get('exitCode')!r}"
        )
    for marker in missing_markers:
        completion_findings.append(f"required output marker was not observed: {marker}")
    for marker in observed_forbidden:
        completion_findings.append(f"forbidden output marker was observed: {marker}")

    existing_findings = review.get("findings", result.get("findings", []))
    if not isinstance(existing_findings, list):
        existing_findings = [str(existing_findings)]
    findings = _without_missing_report(existing_findings)
    findings.extend(completion_findings)
    findings = sorted(set(findings))

    completion = {
        "schemaVersion": "1.0",
        "mode": "process-exit",
        "status": "passed" if not completion_findings else "failed",
        "expectedExitCode": 0,
        "observedExitCode": process.get("exitCode"),
        "timedOut": bool(process.get("timedOut", False)),
        "requiredOutputMarkers": required_markers,
        "observedRequiredOutputMarkers": [
            marker for marker in required_markers if marker in output_lines
        ],
        "missingRequiredOutputMarkers": missing_markers,
        "forbiddenOutputMarkers": forbidden_markers,
        "observedForbiddenOutputMarkers": observed_forbidden,
    }
    completion_path = root / "process-exit-completion.json"
    completion_path.write_text(
        json.dumps(completion, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    relative_completion = completion_path.relative_to(artifacts).as_posix()

    evidence_value = result.get("evidence", review.get("evidence", []))
    if not isinstance(evidence_value, list):
        evidence_value = []
    evidence = sorted({str(item) for item in evidence_value} | {relative_completion})
    status = "passed" if not findings else "failed"

    review.update(
        {
            "status": status,
            "completion": completion,
            "findings": findings,
            "evidence": evidence,
        }
    )
    review_path.write_text(
        json.dumps(review, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    updated = dict(result)
    updated.update(
        {
            "status": status,
            "completion": completion,
            "findings": findings,
            "evidence": evidence,
        }
    )
    return updated


def _run_journey(
    args: Any,
    profile: dict[str, Any],
    journey: dict[str, Any],
    project_root: Path,
    artifacts: Path,
) -> dict[str, Any]:
    delegated, contract = split_process_exit_contract(journey)
    result = ORIGINAL_RUN_JOURNEY(
        args,
        profile,
        delegated,
        project_root,
        artifacts,
    )
    if contract is None:
        return result
    journey_id = str(journey.get("id", ""))
    return _apply_process_exit_contract(result, contract, artifacts, journey_id)


def main() -> int:
    BASE._run_journey = _run_journey
    return int(BASE.main())


if __name__ == "__main__":
    raise SystemExit(main())
