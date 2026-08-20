from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .attended_multiplayer_attestation import (
    build_operator_attestation,
    confirmation_phrase,
    verify_operator_attestation,
)
from .attended_multiplayer_common import (
    ATTESTATION_CONTRACT,
    DESKTOP_LEASE_NAME,
    RECEIPT_CONTRACT,
    AttendedMultiplayerError,
    ensure_output_outside_artifacts,
    load_json_bytes,
    pretty_json,
    write_json_create_only,
)
from .attended_multiplayer_receipt import (
    compile_attended_multiplayer_receipt,
    verify_attended_multiplayer_receipt,
)
from .attended_multiplayer_run import verify_multiplayer_summary_sources

__all__ = [
    "ATTESTATION_CONTRACT",
    "DESKTOP_LEASE_NAME",
    "RECEIPT_CONTRACT",
    "AttendedMultiplayerError",
    "build_operator_attestation",
    "compile_attended_multiplayer_receipt",
    "confirmation_phrase",
    "main",
    "verify_attended_multiplayer_receipt",
    "verify_multiplayer_summary_sources",
    "verify_operator_attestation",
]


def _load_attestation(path: Path) -> dict[str, Any]:
    value, _payload, _resolved = load_json_bytes(path, "ATTESTATION")
    return value


def _load_receipt(path: Path) -> dict[str, Any]:
    value, _payload, _resolved = load_json_bytes(path, "RECEIPT")
    return value


def _probe_windows_session() -> dict[str, Any]:
    if os.name != "nt":
        raise AttendedMultiplayerError("ATTENDED_MULTIPLAYER_WINDOWS_REQUIRED")
    from .native_qa_evidence import _interactive_session

    session = _interactive_session(Path.cwd())
    if (
        session.get("interactive") is not True
        or session.get("explorerInSameSession") is not True
    ):
        detail = session.get("probeError") or (
            "Explorer is not in this nonzero Windows session"
        )
        raise AttendedMultiplayerError(
            "ATTENDED_MULTIPLAYER_INTERACTIVE_SESSION_REQUIRED: " + str(detail)
        )
    return session


def _attest_command(args: argparse.Namespace) -> dict[str, Any]:
    evidence = verify_multiplayer_summary_sources(
        summary_path=args.summary,
        artifact_root=args.artifacts,
    )
    ensure_output_outside_artifacts(args.output, args.artifacts)
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise AttendedMultiplayerError("ATTENDED_MULTIPLAYER_TTY_REQUIRED")
    session = _probe_windows_session()
    phrase = confirmation_phrase(str(evidence["runId"]))
    confirmation = input(
        f"Type {phrase} to attest that you observed the complete run: "
    )
    attestation = build_operator_attestation(
        evidence=evidence,
        campaign_id=args.campaign_id,
        operator_id=getpass.getuser(),
        windows_session_id=int(session["sessionId"]),
        confirmation=confirmation,
    )
    write_json_create_only(args.output, attestation)
    return attestation


def _compile_command(args: argparse.Namespace) -> dict[str, Any]:
    evidence = verify_multiplayer_summary_sources(
        summary_path=args.summary,
        artifact_root=args.artifacts,
    )
    ensure_output_outside_artifacts(args.output, args.artifacts)
    attestation = _load_attestation(args.attestation)
    receipt = compile_attended_multiplayer_receipt(
        evidence=evidence,
        attestation=attestation,
    )
    write_json_create_only(args.output, receipt)
    return receipt


def _verify_command(args: argparse.Namespace) -> dict[str, Any]:
    evidence = verify_multiplayer_summary_sources(
        summary_path=args.summary,
        artifact_root=args.artifacts,
    )
    attestation = _load_attestation(args.attestation)
    receipt = _load_receipt(args.receipt)
    return verify_attended_multiplayer_receipt(
        receipt,
        evidence=evidence,
        attestation=attestation,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m godot_game_test_lab.attended_multiplayer",
        description=(
            "Compile and verify attended exact-SHA Godot multiplayer evidence without "
            "claiming human approval or release authority."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    attest = subparsers.add_parser(
        "attest", help="Create an operator attendance attestation"
    )
    attest.add_argument("--summary", type=Path, required=True)
    attest.add_argument("--artifacts", type=Path, required=True)
    attest.add_argument("--campaign-id", required=True)
    attest.add_argument("--output", type=Path, required=True)
    attest.set_defaults(handler=_attest_command)

    compile_parser = subparsers.add_parser(
        "compile", help="Compile a source-bound attended multiplayer receipt"
    )
    compile_parser.add_argument("--summary", type=Path, required=True)
    compile_parser.add_argument("--artifacts", type=Path, required=True)
    compile_parser.add_argument("--attestation", type=Path, required=True)
    compile_parser.add_argument("--output", type=Path, required=True)
    compile_parser.set_defaults(handler=_compile_command)

    verify = subparsers.add_parser(
        "verify", help="Reverify a receipt against exact sources"
    )
    verify.add_argument("--summary", type=Path, required=True)
    verify.add_argument("--artifacts", type=Path, required=True)
    verify.add_argument("--attestation", type=Path, required=True)
    verify.add_argument("--receipt", type=Path, required=True)
    verify.set_defaults(handler=_verify_command)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        result = args.handler(args)
    except KeyboardInterrupt:
        print(json.dumps({"status": "cancelled", "error": "interrupted"}, sort_keys=True))
        return 130
    except (
        AttendedMultiplayerError,
        FileNotFoundError,
        OSError,
        TypeError,
        ValueError,
    ) as error:
        print(
            json.dumps(
                {"status": "blocked", "error": str(error)},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2
    print(pretty_json(result), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
