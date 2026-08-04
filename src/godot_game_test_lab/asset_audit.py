from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from .asset_audit_io import (
    AssetAuditError,
    default_evidence_root,
    default_lab_root,
    read_git_state,
    resolve_directory,
    resolve_regular_file,
    write_evidence_json,
)
from .asset_audit_validation import (
    DEFAULT_MAXIMUM_ASSET_BYTES,
    DEFAULT_MAXIMUM_FINDINGS,
    DEFAULT_MAXIMUM_IMAGE_PROBE_BYTES,
    DEFAULT_MAXIMUM_TOTAL_ASSET_BYTES,
    REPORT_SCHEMA_VERSION as REPORT_SCHEMA_VERSION,
    validate_asset_audit as validate_asset_audit,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="godot-lab-asset-audit",
        description=(
            "Validate an EVAVO Art Studio asset audit against stable current Godot project bytes."
        ),
    )
    parser.add_argument("project", type=Path)
    parser.add_argument("audit", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--evidence-root", type=Path, default=default_evidence_root())
    parser.add_argument("--replace-output", action="store_true")
    parser.add_argument("--expected-target-sha")
    parser.add_argument("--require-clean-target", action="store_true")
    parser.add_argument("--require-audit-root-match", action="store_true")
    parser.add_argument("--allow-unrecorded-assets", action="store_true")
    parser.add_argument("--allow-missing-references", action="store_true")
    parser.add_argument("--allow-animation-gaps", action="store_true")
    parser.add_argument("--allow-unverified-alpha", action="store_true")
    parser.add_argument(
        "--maximum-asset-bytes",
        type=int,
        default=DEFAULT_MAXIMUM_ASSET_BYTES,
    )
    parser.add_argument(
        "--maximum-total-asset-bytes",
        type=int,
        default=DEFAULT_MAXIMUM_TOTAL_ASSET_BYTES,
    )
    parser.add_argument(
        "--maximum-image-probe-bytes",
        type=int,
        default=DEFAULT_MAXIMUM_IMAGE_PROBE_BYTES,
    )
    parser.add_argument(
        "--maximum-findings",
        type=int,
        default=DEFAULT_MAXIMUM_FINDINGS,
    )
    return parser


def _failed_report(error: Exception) -> dict[str, Any]:
    return {
        "schemaVersion": REPORT_SCHEMA_VERSION,
        "tool": "godot-game-test-lab",
        "check": "art-studio-asset-audit",
        "status": "failed",
        "summary": {
            "errors": 1,
            "warnings": 0,
            "retainedFindings": 1,
            "omittedFindings": 0,
        },
        "findingsTruncated": False,
        "findings": [
            {
                "code": "asset-audit-command-error",
                "severity": "error",
                "message": str(error),
            }
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        for label, value in (
            ("maximum_asset_bytes", args.maximum_asset_bytes),
            ("maximum_total_asset_bytes", args.maximum_total_asset_bytes),
            ("maximum_image_probe_bytes", args.maximum_image_probe_bytes),
            ("maximum_findings", args.maximum_findings),
        ):
            if value < 1:
                raise AssetAuditError(f"{label} must be positive")
        report = validate_asset_audit(
            args.project,
            args.audit,
            allow_unrecorded_assets=args.allow_unrecorded_assets,
            allow_missing_references=args.allow_missing_references,
            allow_animation_gaps=args.allow_animation_gaps,
            allow_unverified_alpha=args.allow_unverified_alpha,
            expected_target_sha=args.expected_target_sha,
            require_clean_target=args.require_clean_target,
            require_audit_root_match=args.require_audit_root_match,
            maximum_asset_bytes=args.maximum_asset_bytes,
            maximum_total_asset_bytes=args.maximum_total_asset_bytes,
            maximum_image_probe_bytes=args.maximum_image_probe_bytes,
            maximum_findings=args.maximum_findings,
        )
        if args.output is not None:
            project_root = resolve_directory(args.project, "Godot project")
            audit_source = resolve_regular_file(args.audit, "Art Studio audit")
            git_state = read_git_state(project_root)
            lab_root = default_lab_root()
            protected = [project_root, lab_root]
            if git_state.available and git_state.git_root is not None:
                protected.append(Path(git_state.git_root))
            written = write_evidence_json(
                report,
                output=args.output,
                evidence_root=args.evidence_root,
                protected_roots=tuple(dict.fromkeys(protected)),
                replace=args.replace_output,
            )
            _ = written
    except (AssetAuditError, OSError, ValueError) as error:
        report = _failed_report(error)
    sys.stdout.write(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    return 0 if report.get("status") == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
