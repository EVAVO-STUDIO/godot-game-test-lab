from __future__ import annotations

import os
from pathlib import Path


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    source = path.read_text(encoding="utf-8")
    if source.count(old) != 1:
        raise SystemExit(f"{label} anchor count changed: {source.count(old)}")
    path.write_text(source.replace(old, new), encoding="utf-8", newline="\n")


def main() -> int:
    stage = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True) / "final-source-tree"
    if stage.is_symlink() or not stage.is_dir():
        raise SystemExit(f"final source staging directory is missing or unsafe: {stage}")

    runner = stage / "scripts/run_agent_godot_qa.py"
    replace_once(
        runner,
        ')\nBLACK_DURATION_RE = re.compile(r"black_duration:(?P<duration>[0-9.]+)")\n',
        ')\nPROCESS_OUTPUT_EXCERPT_LIMIT = 4096\n'
        'BLACK_DURATION_RE = re.compile(r"black_duration:(?P<duration>[0-9.]+)")\n',
        "journey process-output limit",
    )
    replace_once(
        runner,
        '    return findings\n\n\ndef _extract_visual_evidence(\n',
        '    return findings\n\n\n'
        'def _process_output_excerpt(result: dict[str, Any]) -> dict[str, str]:\n'
        '    excerpt: dict[str, str] = {}\n'
        '    for stream in ("stdout", "stderr"):\n'
        '        value = str(result.get(stream, "")).strip()\n'
        '        if not value:\n'
        '            continue\n'
        '        if len(value) > PROCESS_OUTPUT_EXCERPT_LIMIT:\n'
        '            removed = len(value) - PROCESS_OUTPUT_EXCERPT_LIMIT\n'
        '            value = (\n'
        '                f"[truncated {removed} characters]\\n"\n'
        '                f"{value[-PROCESS_OUTPUT_EXCERPT_LIMIT:]}"\n'
        '            )\n'
        '        excerpt[stream] = value\n'
        '    return excerpt\n\n\n'
        'def _extract_visual_evidence(\n',
        "journey bounded process-output helper",
    )
    replace_once(
        runner,
        '    findings = _process_findings(process)\n'
        '    report_value: dict[str, Any] = {}\n',
        '    process_findings = _process_findings(process)\n'
        '    findings = list(process_findings)\n'
        '    process_output_excerpt = (\n'
        '        _process_output_excerpt(process) if process_findings else {}\n'
        '    )\n'
        '    report_value: dict[str, Any] = {}\n',
        "journey process-output capture",
    )
    replace_once(
        runner,
        '            "timedOut": process.get("timedOut"),\n'
        '        },\n'
        '        "harness": report_value,\n',
        '            "timedOut": process.get("timedOut"),\n'
        '            "failureOutputExcerpt": process_output_excerpt,\n'
        '        },\n'
        '        "harness": report_value,\n',
        "journey retained process-output excerpt",
    )
    replace_once(
        runner,
        '        "findings": review["findings"],\n'
        '        "evidence": sorted(set(review["evidence"])),\n'
        '    }\n\n\ndef run(args: argparse.Namespace) -> dict[str, Any]:\n',
        '        "findings": review["findings"],\n'
        '        "evidence": sorted(set(review["evidence"])),\n'
        '        "processFailureOutputExcerpt": process_output_excerpt,\n'
        '    }\n\n\ndef run(args: argparse.Namespace) -> dict[str, Any]:\n',
        "journey summary process-output excerpt",
    )

    journey_driver = stage / "scripts/godot_input_journey.gd"
    replace_once(
        journey_driver,
        "        var node := stack.pop_back()\n",
        "        var node: Node = stack.pop_back()\n",
        "journey driver typed node stack pop",
    )

    test_path = stage / "tests/test_agent_qa_failure_diagnostics.py"
    if test_path.exists() or test_path.is_symlink():
        raise SystemExit("journey failure-diagnostics test path already exists")
    test_path.write_text(
        '''from __future__ import annotations

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
    assert len(excerpt["stdout"].split("\\n", 1)[1]) == (
        runner.PROCESS_OUTPUT_EXCERPT_LIMIT
    )
    assert excerpt["stderr"] == "SCRIPT ERROR: fixture"


def test_process_output_excerpt_omits_empty_streams() -> None:
    runner = _load_runner()
    assert runner._process_output_excerpt({"stdout": "  ", "stderr": ""}) == {}
''',
        encoding="utf-8",
        newline="\n",
    )

    driver_test = stage / "tests/test_godot_journey_driver_contract.py"
    if driver_test.exists() or driver_test.is_symlink():
        raise SystemExit("journey-driver contract test path already exists")
    driver_test.write_text(
        '''from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "scripts" / "godot_input_journey.gd"


def test_variant_stack_pop_has_an_explicit_node_type() -> None:
    source = DRIVER.read_text(encoding="utf-8")
    assert "var node: Node = stack.pop_back()" in source
    assert "var node := stack.pop_back()" not in source
''',
        encoding="utf-8",
        newline="\n",
    )

    temporary = stage / ".evavo/apply_journey_driver_fixes.py"
    if temporary.exists() or temporary.is_symlink():
        temporary.unlink()
    print("applied journey-driver diagnostics and parser fix")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
