from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run_agent_godot_qa.py"


def _load_runner() -> Any:
    spec = importlib.util.spec_from_file_location("agent_qa_failure_runner", RUNNER)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_process_output_excerpt_is_bounded_and_tail_preserving() -> None:
    runner = _load_runner()
    stdout = "prefix-" + ("x" * 5000) + "PARSE ERROR TAIL"
    excerpt = runner._process_output_excerpt(
        {"stdout": stdout, "stderr": "SCRIPT ERROR: fixture"}
    )

    assert excerpt["stdout"].startswith("[truncated ")
    assert excerpt["stdout"].endswith("PARSE ERROR TAIL")
    assert len(excerpt["stdout"].split("\n", 1)[1]) == (
        runner.PROCESS_OUTPUT_EXCERPT_LIMIT
    )
    assert excerpt["stderr"] == "SCRIPT ERROR: fixture"


def test_process_output_excerpt_omits_empty_streams() -> None:
    runner = _load_runner()
    assert runner._process_output_excerpt({"stdout": "  ", "stderr": ""}) == {}
