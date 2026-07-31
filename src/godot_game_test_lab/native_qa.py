from __future__ import annotations

import argparse
import json
import re
from collections.abc import Sequence
from pathlib import Path

from .native_qa_common import (
    NativeQaError,
    _archive_checkout,
    _load_json_object,
    _safe_relative_path,
)
from .native_qa_evidence import _artifact_inventory
from .native_qa_profile import normalize_profile

__all__ = [
    "NativeQaError",
    "_archive_checkout",
    "_artifact_inventory",
    "_load_json_object",
    "_safe_relative_path",
    "build_parser",
    "main",
    "normalize_profile",
    "run_native_qa",
]


def run_native_qa(args: argparse.Namespace) -> dict[str, object]:
    from .native_qa_runner import run_native_qa as run

    return run(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="godot-lab-native-qa",
        description="Run exact-SHA native Windows Godot validation and synthetic journeys.",
    )
    parser.add_argument("--lab-root", type=Path, required=True)
    parser.add_argument("--target-repository", type=Path, required=True)
    parser.add_argument("--project-subpath", default=".")
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--expected-lab-sha", required=True)
    parser.add_argument("--expected-target-sha", required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--allowed-artifact-root", type=Path, required=True)
    parser.add_argument("--godot", type=Path)
    parser.add_argument("--dotnet", type=Path)
    parser.add_argument("--minimum-godot-version", default="4.6.2")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--boot-frames", type=int, default=30)
    parser.add_argument("--window-position", default="32,32")
    parser.add_argument(
        "--allow-noninteractive",
        action="store_false",
        dest="require_interactive_desktop",
        help="Allow non-interactive execution for contract tests only.",
    )
    parser.set_defaults(require_interactive_desktop=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    if not isinstance(args.timeout, int) or args.timeout < 30 or args.timeout > 7200:
        raise SystemExit("--timeout must be between 30 and 7200 seconds")
    if not isinstance(args.boot_frames, int) or not 0 <= args.boot_frames <= 3600:
        raise SystemExit("--boot-frames must be between 0 and 3600")
    if re.fullmatch(r"-?[0-9]{1,5},-?[0-9]{1,5}", args.window_position) is None:
        raise SystemExit("--window-position must use X,Y integer coordinates")

    try:
        summary = run_native_qa(args)
    except (NativeQaError, FileNotFoundError, OSError, ValueError) as error:
        print(json.dumps({"status": "blocked", "error": str(error)}, sort_keys=True))
        return 2
    print(json.dumps(summary, sort_keys=True))
    return 0 if summary.get("status") == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
