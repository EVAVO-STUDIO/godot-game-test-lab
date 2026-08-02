from __future__ import annotations

import argparse
import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .bot_profile import normalize_bot_profile
from .native_qa_common import NativeQaError, _canonical_json

__all__ = [
    "NativeQaError",
    "build_parser",
    "enforce_exploration_evidence",
    "main",
    "normalize_bot_profile",
    "run_bot_qa",
]


def run_bot_qa(args: argparse.Namespace) -> dict[str, object]:
    from .bot_runner import run_bot_qa as run

    return enforce_exploration_evidence(dict(run(args)))


def _list_value(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _int_value(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def enforce_exploration_evidence(summary: dict[str, object]) -> dict[str, object]:
    """Fail required campaigns that never prove a changed state or replay it."""
    campaigns = summary.get("campaigns")
    if not isinstance(campaigns, list):
        return summary

    required_failure = False
    for raw_campaign in campaigns:
        if not isinstance(raw_campaign, dict) or raw_campaign.get("required") is not True:
            continue

        campaign: dict[str, Any] = raw_campaign
        transitions = [
            item
            for item in _list_value(campaign.get("transitions"))
            if isinstance(item, dict)
        ]
        replays = [
            item
            for item in _list_value(campaign.get("representativeReplays"))
            if isinstance(item, dict)
        ]
        changed_transitions = [
            item
            for item in transitions
            if item.get("result") == "new-state"
            and str(item.get("to", ""))
            and str(item.get("to", "")) != str(item.get("from", ""))
            and len(_list_value(item.get("trace"))) > 0
        ]
        nonbaseline_replays = [
            item
            for item in replays
            if item.get("status") == "passed"
            and _int_value(item.get("depth")) >= 1
            and len(_list_value(item.get("trace"))) > 0
            and len(_list_value(item.get("evidence"))) > 0
        ]

        gate_findings: list[str] = []
        if _int_value(campaign.get("stateCount")) < 2 or not changed_transitions:
            gate_findings.append(
                "required bot campaign did not prove a changed runtime state"
            )
        if not nonbaseline_replays:
            gate_findings.append(
                "required bot campaign did not retain a passing non-baseline replay"
            )
        if not gate_findings:
            continue

        required_failure = True
        campaign["status"] = "failed"
        campaign_findings = [
            str(item) for item in _list_value(campaign.get("findings"))
        ]
        campaign["findings"] = sorted(set([*campaign_findings, *gate_findings]))
        campaign_failures = [
            item
            for item in _list_value(campaign.get("failures"))
            if isinstance(item, dict)
        ]
        campaign_failures.append(
            {
                "source": "bot-summary-exploration-gate",
                "trace": [],
                "findings": gate_findings,
                "evidence": [],
            }
        )
        campaign["failures"] = campaign_failures

    if required_failure:
        summary["status"] = "failed"
        findings = [str(item) for item in _list_value(summary.get("findings"))]
        findings.append(
            "one or more required bot campaigns lacked changed-state or "
            "non-baseline replay evidence"
        )
        summary["findings"] = sorted(set(findings))
    return summary


def _write_enforced_summary(args: argparse.Namespace, summary: dict[str, object]) -> None:
    summary_path = (
        Path(args.artifacts).expanduser().resolve(strict=False)
        / "bot-agent-summary.json"
    )
    if summary_path.exists() and summary_path.is_symlink():
        raise NativeQaError("bot-agent-summary.json may not be a symbolic link")
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(_canonical_json(summary), encoding="utf-8", newline="\n")


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
        _write_enforced_summary(args, summary)
    except (NativeQaError, FileNotFoundError, OSError, ValueError) as error:
        print(json.dumps({"status": "blocked", "error": str(error)}, sort_keys=True))
        return 2
    print(json.dumps(summary, sort_keys=True))
    return 0 if summary.get("status") == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
