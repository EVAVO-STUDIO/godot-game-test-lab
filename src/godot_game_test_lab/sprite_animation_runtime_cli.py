from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .game_asset_delivery_common import _read_json
from .sprite_animation_runtime_admission import (
    admit_sprite_animation_runtime,
    compile_sprite_animation_runtime_evidence,
)


def _write_create_only(path: Path, value: dict[str, Any]) -> Path:
    destination = path.expanduser().resolve()
    if destination.exists():
        raise ValueError(f"output already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="godot-lab-sprite-animation",
        description=(
            "Compile target-owned raw AnimatedSprite2D telemetry into self-hashed evidence "
            "and admit it against an exact Art Studio runtime expectation."
        ),
    )
    parser.add_argument("--expectation", type=Path, required=True)
    parser.add_argument("--raw-telemetry", type=Path, required=True)
    parser.add_argument("--evidence-output", type=Path, required=True)
    parser.add_argument("--report-output", type=Path, required=True)
    return parser


def run(args: argparse.Namespace) -> dict[str, Any]:
    expectation_path, _, expectation = _read_json(
        args.expectation,
        "sprite animation runtime expectation",
    )
    raw_path, _, raw = _read_json(
        args.raw_telemetry,
        "sprite animation raw telemetry",
    )
    evidence_output = args.evidence_output.expanduser().resolve()
    report_output = args.report_output.expanduser().resolve()
    if evidence_output == report_output:
        raise ValueError("evidence-output and report-output must be distinct")
    inputs = {expectation_path.resolve(), raw_path.resolve()}
    if evidence_output in inputs or report_output in inputs:
        raise ValueError("outputs must not overwrite input evidence")

    expectation_sha = expectation.get("expectationSha256")
    evidence = compile_sprite_animation_runtime_evidence(raw, expectation_sha)
    report = admit_sprite_animation_runtime(expectation, evidence)
    _write_create_only(evidence_output, evidence)
    _write_create_only(report_output, report)
    return {
        "status": report["status"],
        "expectationSha256": report["expectationSha256"],
        "runtimeEvidenceSha256": report["runtimeEvidenceSha256"],
        "reportSha256": report["reportSha256"],
        "evidenceOutput": str(evidence_output),
        "reportOutput": str(report_output),
    }


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = run(args)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"sprite animation runtime admission failed: {error}", file=os.sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
