#!/usr/bin/env python3
"""Apply static integrity policy around the canonical Linux Godot QA runner."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path
from types import ModuleType

from godot_game_test_lab.linux_integrity import (
    merge_integrity_evidence,
    run_integrity_preflight,
    write_integrity_preflight_failure,
)

HERE = Path(__file__).resolve().parent
CANONICAL_RUNNER = HERE / "run_agent_godot_qa_with_process_exit.py"


def _load_canonical_runner() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "evavo_agent_qa_with_process_exit",
        CANONICAL_RUNNER,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not import canonical agent QA runner: {CANONICAL_RUNNER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _preflight_arguments(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("source", type=Path)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--project-subpath", default=".")
    values, _ = parser.parse_known_args(argv)
    return values


def _warnings_as_errors() -> bool:
    value = os.environ.get("EVAVO_INTEGRITY_WARNINGS_AS_ERRORS", "").strip().casefold()
    if value in {"", "0", "false", "no", "off"}:
        return False
    if value in {"1", "true", "yes", "on"}:
        return True
    raise ValueError("EVAVO_INTEGRITY_WARNINGS_AS_ERRORS must be a boolean value")


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    known = _preflight_arguments(arguments)
    try:
        warnings_as_errors = _warnings_as_errors()
    except ValueError as error:
        gate = write_integrity_preflight_failure(
            known.artifacts,
            project_subpath=known.project_subpath,
            error=error,
        )
        print(json.dumps(gate, sort_keys=True))
        return 2
    gate = run_integrity_preflight(
        known.source,
        project_subpath=known.project_subpath,
        artifacts_root=known.artifacts,
        warnings_as_errors=warnings_as_errors,
    )
    if gate.get("status") == "blocked":
        print(json.dumps(gate, sort_keys=True))
        return 2

    runner_exit_code = 2
    try:
        canonical = _load_canonical_runner()
        original_argv = sys.argv
        sys.argv = [str(CANONICAL_RUNNER), *arguments]
        try:
            runner_exit_code = int(canonical.main())
        finally:
            sys.argv = original_argv
    except SystemExit as error:
        runner_exit_code = int(error.code or 0)
    except (ImportError, OSError, RuntimeError, ValueError) as error:
        print(f"Canonical Godot QA runner failed before completion: {error}", file=sys.stderr)
        runner_exit_code = 2

    summary = merge_integrity_evidence(
        known.artifacts,
        runner_exit_code=runner_exit_code,
    )
    print(json.dumps(summary, sort_keys=True))
    return 0 if summary.get("status") == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
