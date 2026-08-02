from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from .media_evidence import analyze_media_file, normalize_media_policy, scan_run_media
from .native_qa_common import NativeQaError, _canonical_json, _load_json_object


def _policy(path: Path | None) -> dict[str, object]:
    if path is None:
        return normalize_media_policy()
    return normalize_media_policy(_load_json_object(path, "media policy"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="godot-lab-media-qa",
        description=(
            "Extract and analyse synchronized audio from retained Godot gameplay movies."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    analyze = subparsers.add_parser("analyze", help="Analyse one recorded gameplay movie.")
    analyze.add_argument("media", type=Path)
    analyze.add_argument("--artifacts", type=Path, required=True)
    analyze.add_argument("--policy", type=Path)
    analyze.add_argument("--timeout", type=int, default=300)
    analyze.add_argument("--ffmpeg", type=Path)
    analyze.add_argument("--ffprobe", type=Path)

    scan = subparsers.add_parser(
        "scan",
        help="Find and analyse every supported gameplay movie beneath a retained run.",
    )
    scan.add_argument("run", type=Path)
    scan.add_argument("--artifacts", type=Path)
    scan.add_argument("--policy", type=Path)
    scan.add_argument("--timeout", type=int, default=300)
    scan.add_argument("--ffmpeg", type=Path)
    scan.add_argument("--ffprobe", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        governed = _policy(args.policy)
        if args.command == "analyze":
            result = analyze_media_file(
                args.media,
                args.artifacts,
                policy=governed,
                timeout_seconds=args.timeout,
                ffmpeg=args.ffmpeg,
                ffprobe=args.ffprobe,
            )
        else:
            result = scan_run_media(
                args.run,
                args.artifacts,
                policy=governed,
                timeout_seconds=args.timeout,
                ffmpeg=args.ffmpeg,
                ffprobe=args.ffprobe,
            )
    except (NativeQaError, FileNotFoundError, OSError, ValueError) as error:
        print(json.dumps({"status": "blocked", "error": str(error)}, sort_keys=True))
        return 2
    print(_canonical_json(result), end="")
    return 0 if result.get("status") == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
