from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_agent_godot_qa_with_process_exit.py"


def load_wrapper():
    spec = importlib.util.spec_from_file_location("process_exit_wrapper", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def process_exit_journey(*extra_arguments: str) -> dict[str, Any]:
    return {
        "id": "compiled-regression",
        "required": True,
        "userArguments": [
            "--run-regression-harness",
            "--evavo-agent-completion=process-exit",
            "--evavo-agent-require-output=[ACTION_SCREEN_EXPERIENCE] PASS",
            "--evavo-agent-require-output=[PLAYTEST_REGRESSION] PASS",
            "--evavo-agent-forbid-output=[ACTION_SCREEN_EXPERIENCE] FAIL",
            *extra_arguments,
        ],
    }


def write_base_review(
    artifacts: Path,
    *,
    stdout: str,
    exit_code: int | None = 0,
    timed_out: bool = False,
    findings: list[str] | None = None,
) -> None:
    root = artifacts / "journeys" / "compiled-regression"
    logs = root / "logs"
    logs.mkdir(parents=True)
    (logs / "journey.stdout.log").write_text(stdout, encoding="utf-8")
    (logs / "journey.stderr.log").write_text("", encoding="utf-8")
    (root / "visual-ux-review.json").write_text(
        json.dumps(
            {
                "status": "failed",
                "process": {
                    "exitCode": exit_code,
                    "timedOut": timed_out,
                },
                "findings": findings or ["journey report was not produced"],
                "evidence": ["journeys/compiled-regression/logs/journey.stdout.log"],
            }
        )
        + "\n",
        encoding="utf-8",
    )


def install_base_result(module, findings: list[str] | None = None) -> None:
    module.ORIGINAL_RUN_JOURNEY = lambda *args, **kwargs: {
        "id": "compiled-regression",
        "required": True,
        "status": "failed",
        "findings": findings or ["journey report was not produced"],
        "evidence": ["journeys/compiled-regression/logs/journey.stdout.log"],
    }


def run_process_exit(module, tmp_path: Path, artifacts: Path) -> dict[str, Any]:
    return module._run_journey(
        SimpleNamespace(),
        {},
        process_exit_journey(),
        tmp_path,
        artifacts,
    )


def test_split_process_exit_contract_strips_only_reserved_arguments() -> None:
    module = load_wrapper()

    delegated, contract = module.split_process_exit_contract(process_exit_journey())

    assert delegated["userArguments"] == ["--run-regression-harness"]
    assert contract == {
        "mode": "process-exit",
        "requiredOutputMarkers": [
            "[ACTION_SCREEN_EXPERIENCE] PASS",
            "[PLAYTEST_REGRESSION] PASS",
        ],
        "forbiddenOutputMarkers": ["[ACTION_SCREEN_EXPERIENCE] FAIL"],
    }


def test_process_exit_contract_requires_completion_mode_and_marker() -> None:
    module = load_wrapper()

    with pytest.raises(ValueError, match="require --evavo-agent-completion"):
        module.split_process_exit_contract(
            {
                "id": "bad",
                "userArguments": [
                    "--evavo-agent-require-output=[PLAYTEST_REGRESSION] PASS"
                ],
            }
        )
    with pytest.raises(ValueError, match="at least one output marker"):
        module.split_process_exit_contract(
            {
                "id": "bad",
                "userArguments": ["--evavo-agent-completion=process-exit"],
            }
        )


def test_successful_process_exit_markers_replace_only_missing_report_failure(
    tmp_path: Path,
) -> None:
    module = load_wrapper()
    artifacts = tmp_path / "artifacts"
    write_base_review(
        artifacts,
        stdout=(
            "[ACTION_SCREEN_EXPERIENCE] PASS\n"
            "[PLAYTEST_REGRESSION] PASS\n"
        ),
    )
    install_base_result(module)

    result = run_process_exit(module, tmp_path, artifacts)

    assert result["status"] == "passed"
    assert result["findings"] == []
    assert result["completion"]["schemaVersion"] == "1.1"
    assert result["completion"]["status"] == "passed"
    assert result["completion"]["processExitStatus"] == "passed"
    assert "journeys/compiled-regression/process-exit-completion.json" in result[
        "evidence"
    ]


def test_decorated_markers_do_not_match_exact_output_lines(tmp_path: Path) -> None:
    module = load_wrapper()
    artifacts = tmp_path / "artifacts"
    write_base_review(
        artifacts,
        stdout=(
            "prefix [ACTION_SCREEN_EXPERIENCE] PASS suffix\n"
            "[PLAYTEST_REGRESSION] PASS\n"
            "prefix [ACTION_SCREEN_EXPERIENCE] FAIL suffix\n"
        ),
    )
    install_base_result(module)

    result = run_process_exit(module, tmp_path, artifacts)

    assert result["status"] == "failed"
    assert result["completion"]["status"] == "failed"
    assert result["completion"]["processExitStatus"] == "failed"
    assert result["completion"]["observedRequiredOutputMarkers"] == [
        "[PLAYTEST_REGRESSION] PASS"
    ]
    assert result["completion"]["observedForbiddenOutputMarkers"] == []
    assert any(
        "required output marker was not observed" in item
        for item in result["findings"]
    )
    assert not any(
        "forbidden output marker was observed" in item
        for item in result["findings"]
    )


def test_missing_or_forbidden_marker_keeps_process_exit_journey_failed(
    tmp_path: Path,
) -> None:
    module = load_wrapper()
    artifacts = tmp_path / "artifacts"
    write_base_review(
        artifacts,
        stdout=(
            "[ACTION_SCREEN_EXPERIENCE] PASS\n"
            "[ACTION_SCREEN_EXPERIENCE] FAIL\n"
        ),
    )
    install_base_result(module)

    result = run_process_exit(module, tmp_path, artifacts)

    assert result["status"] == "failed"
    assert result["completion"]["status"] == "failed"
    assert result["completion"]["processExitStatus"] == "failed"
    assert any(
        "required output marker was not observed" in item
        for item in result["findings"]
    )
    assert any(
        "forbidden output marker was observed" in item
        for item in result["findings"]
    )


def test_process_exit_completion_never_discards_other_base_findings(
    tmp_path: Path,
) -> None:
    module = load_wrapper()
    artifacts = tmp_path / "artifacts"
    other_findings = [
        "journey report was not produced",
        "rendered journey contains a sustained black segment",
    ]
    write_base_review(
        artifacts,
        stdout=(
            "[ACTION_SCREEN_EXPERIENCE] PASS\n"
            "[PLAYTEST_REGRESSION] PASS\n"
        ),
        findings=other_findings,
    )
    install_base_result(module, other_findings)

    result = run_process_exit(module, tmp_path, artifacts)

    assert result["status"] == "failed"
    assert result["completion"]["status"] == "failed"
    assert result["completion"]["processExitStatus"] == "passed"
    assert result["findings"] == [
        "rendered journey contains a sustained black segment"
    ]
