from __future__ import annotations

import argparse
import json
import re
from collections.abc import Sequence
from pathlib import Path

from .bot_profile import normalize_bot_profile
from .native_qa_common import NativeQaError

__all__ = ["NativeQaError", "build_parser", "main", "normalize_bot_profile", "run_bot_qa"]


def run_bot_qa(args: argparse.Namespace) -> dict[str, object]:
    from .bot_runner import run_bot_qa as run

    return run(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="godot-lab-bot-qa",
        description=(
            "Run exact-SHA deterministic Godot UI graph exploration and mapped input fuzzing."
        ),
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
    parser.add_argument("--max-total-seconds", type=int, default=3600)
    parser.add_argument("--max-artifact-bytes", type=int, default=20 * 1024**3)
    parser.add_argument("--window-position", default="32,32")
    parser.add_argument(
        "--allow-noninteractive",
        action="store_false",
        dest="require_interactive_desktop",
        help="Allow contract testing without claiming native desktop evidence.",
    )
    parser.set_defaults(require_interactive_desktop=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    if not 30 <= args.timeout <= 7200:
        raise SystemExit("--timeout must be between 30 and 7200 seconds")
    if not 0 <= args.boot_frames <= 3600:
        raise SystemExit("--boot-frames must be between 0 and 3600")
    if not 60 <= args.max_total_seconds <= 14400:
        raise SystemExit("--max-total-seconds must be between 60 and 14400")
    if not 1024**2 <= args.max_artifact_bytes <= 200 * 1024**3:
        raise SystemExit("--max-artifact-bytes must be between 1 MiB and 200 GiB")
    if re.fullmatch(r"-?[0-9]{1,5},-?[0-9]{1,5}", args.window_position) is None:
        raise SystemExit("--window-position must use X,Y integer coordinates")
    try:
        summary = run_bot_qa(args)
    except (NativeQaError, FileNotFoundError, OSError, ValueError) as error:
        print(json.dumps({"status": "blocked", "error": str(error)}, sort_keys=True))
        return 2
    print(json.dumps(summary, sort_keys=True))
    return 0 if summary.get("status") == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
