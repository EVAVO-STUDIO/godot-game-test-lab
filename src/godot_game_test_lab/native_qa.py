from __future__ import annotations

import argparse
import json
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from .native_qa_common import (
    NativeQaError,
    _archive_checkout,
    _canonical_json,
    _git_text,
    _is_within,
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
    from .native_qa_visual_review import augment_native_qa_summary

    return augment_native_qa_summary(args, run(args))


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
    parser.add_argument("--max-total-seconds", type=int, default=3600)
    parser.add_argument(
        "--max-artifact-bytes",
        type=int,
        default=20 * 1024 * 1024 * 1024,
    )
    parser.add_argument(
        "--allow-noninteractive",
        action="store_false",
        dest="require_interactive_desktop",
        help="Allow non-interactive execution for contract tests only; never native evidence.",
    )
    parser.set_defaults(require_interactive_desktop=True)
    return parser


def _write_blocked_summary(args: argparse.Namespace, error: Exception) -> None:
    try:
        allowed = args.allowed_artifact_root.expanduser().resolve(strict=True)
        artifacts = args.artifacts.expanduser().resolve(strict=False)
        lab = args.lab_root.expanduser().resolve(strict=False)
        target = args.target_repository.expanduser().resolve(strict=False)
        if (
            artifacts == allowed
            or not _is_within(artifacts, allowed)
            or _is_within(artifacts, lab)
            or _is_within(artifacts, target)
        ):
            return
        if artifacts.exists() and any(artifacts.iterdir()):
            owned_partial = any(
                (artifacts / name).exists()
                for name in ("profile.normalized.json", "run-context.json", "hardware.json")
            )
            if not owned_partial:
                return
        artifacts.mkdir(parents=True, exist_ok=True)
        target_status = None
        try:
            git_root = Path(_git_text(target, ["rev-parse", "--show-toplevel"])).resolve()
            target_status = _git_text(
                git_root, ["status", "--porcelain=v1", "--untracked-files=all"]
            )
        except NativeQaError:
            pass
        payload = {
            "schemaVersion": "2.0",
            "status": "blocked",
            "generatedAt": datetime.now(UTC).isoformat(),
            "errorType": type(error).__name__,
            "error": str(error),
            "labSha": args.expected_lab_sha,
            "targetSha": args.expected_target_sha,
            "projectSubpath": args.project_subpath,
            "targetStatus": target_status,
            "nativeDesktopEvidence": False,
            "truthBoundary": (
                "The native worker was blocked before completing authoritative validation "
                "and journey evidence; no pass claim is made."
            ),
        }
        (artifacts / "native-agent-summary.json").write_text(
            _canonical_json(payload), encoding="utf-8"
        )
    except (OSError, ValueError):
        return


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    if not isinstance(args.timeout, int) or not 30 <= args.timeout <= 7200:
        raise SystemExit("--timeout must be between 30 and 7200 seconds")
    if not isinstance(args.boot_frames, int) or not 0 <= args.boot_frames <= 3600:
        raise SystemExit("--boot-frames must be between 0 and 3600")
    if not isinstance(args.max_total_seconds, int) or not 60 <= args.max_total_seconds <= 14400:
        raise SystemExit("--max-total-seconds must be between 60 and 14400")
    if (
        not isinstance(args.max_artifact_bytes, int)
        or not 1024**3 <= args.max_artifact_bytes <= 200 * 1024**3
    ):
        raise SystemExit("--max-artifact-bytes must be between 1 GiB and 200 GiB")
    if re.fullmatch(r"-?[0-9]{1,5},-?[0-9]{1,5}", args.window_position) is None:
        raise SystemExit("--window-position must use X,Y integer coordinates")

    try:
        summary = run_native_qa(args)
    except KeyboardInterrupt as error:
        _write_blocked_summary(args, error)
        print(json.dumps({"status": "cancelled", "error": "interrupted"}, sort_keys=True))
        return 130
    except (NativeQaError, FileNotFoundError, OSError, TypeError, ValueError) as error:
        _write_blocked_summary(args, error)
        print(json.dumps({"status": "blocked", "error": str(error)}, sort_keys=True))
        return 2
    print(json.dumps(summary, sort_keys=True))
    return 0 if summary.get("status") == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
