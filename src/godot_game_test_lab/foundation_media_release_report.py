from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .asset_audit_io import (
    AssetAuditError,
    default_evidence_root,
    default_lab_root,
    read_git_state,
    resolve_directory,
    write_evidence_json,
)
from .foundation_media_plan import validate_foundation_media_plan
from .strict_json import StrictJsonError

REPORT_SCHEMA_VERSION = "1.0"


class FoundationMediaReleaseReportError(AssetAuditError):
    """Raised when a plan report cannot become exact-head release evidence."""


def _head_from_state(value: dict[str, Any]) -> str | None:
    for key in (
        "targetSha",
        "target_sha",
        "headSha",
        "head_sha",
        "head",
        "commitSha",
        "commit_sha",
    ):
        candidate = value.get(key)
        if (
            isinstance(candidate, str)
            and len(candidate) == 40
            and all(
                character in "0123456789abcdefABCDEF"
                for character in candidate
            )
        ):
            return candidate.lower()
    return None


def _clean_from_state(value: dict[str, Any]) -> bool | None:
    dirty = value.get("dirty")
    if isinstance(dirty, bool):
        return not dirty
    for key in ("clean", "worktreeClean", "worktree_clean"):
        candidate = value.get(key)
        if isinstance(candidate, bool):
            return candidate
    status = value.get("status")
    if isinstance(status, str):
        return status.strip() == ""
    return None


def build_foundation_media_release_report(
    project: Path,
    contract: Path,
    audit: Path,
    plan: Path,
    *,
    strict: bool = True,
) -> dict[str, Any]:
    project_root = resolve_directory(project, "Godot project")
    state_before = read_git_state(project_root)
    before = state_before.to_dict()
    target_sha = _head_from_state(before)
    clean = _clean_from_state(before)
    if not state_before.available or target_sha is None:
        raise FoundationMediaReleaseReportError(
            "Exact Git HEAD is required for Foundation Kit release evidence"
        )
    if clean is not True:
        raise FoundationMediaReleaseReportError(
            "A clean target worktree is required for release evidence"
        )

    report = validate_foundation_media_plan(
        project_root,
        contract,
        audit,
        plan,
        strict=strict,
    )

    state_after = read_git_state(project_root)
    after = state_after.to_dict()
    after_sha = _head_from_state(after)
    after_clean = _clean_from_state(after)
    if after_sha != target_sha or after_clean is not True:
        raise FoundationMediaReleaseReportError(
            "Target Git state changed while release evidence was built"
        )

    report["targetSha"] = target_sha
    report["targetClean"] = True
    report["exactHeadBound"] = True
    report["targetMutationPerformed"] = False
    report["publicationAuthority"] = False
    report["releaseEvidenceEligible"] = bool(
        strict and report.get("status") == "passed"
    )
    if report.get("status") != "passed":
        return report

    report["schemaVersion"] = REPORT_SCHEMA_VERSION
    report["truthBoundaries"] = [
        *list(report.get("truthBoundaries", [])),
        "A head-bound report is not native Godot or human creative approval.",
        "Release eligibility remains contingent on all downstream evidence.",
    ]
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m godot_game_test_lab.foundation_media_release_report",
        description=(
            "Build an explicit clean-current-HEAD Foundation Kit media-plan "
            "report for Development Studio evidence admission."
        ),
    )
    parser.add_argument("project", type=Path)
    parser.add_argument("contract", type=Path)
    parser.add_argument("audit", type=Path)
    parser.add_argument("plan", type=Path)
    parser.add_argument("--strict", action="store_true", default=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--evidence-root",
        type=Path,
        default=default_evidence_root(),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        report = build_foundation_media_release_report(
            args.project,
            args.contract,
            args.audit,
            args.plan,
            strict=args.strict,
        )
        project_root = resolve_directory(args.project, "Godot project")
        state = read_git_state(project_root)
        protected = [project_root, default_lab_root()]
        if state.available and state.git_root is not None:
            protected.append(Path(state.git_root))
        written = write_evidence_json(
            report,
            output=args.output,
            evidence_root=args.evidence_root,
            protected_roots=tuple(dict.fromkeys(protected)),
            replace=False,
        )
        report["outputPath"] = str(written)
    except (
        AssetAuditError,
        FoundationMediaReleaseReportError,
        OSError,
        StrictJsonError,
        ValueError,
    ) as error:
        report = {
            "schemaVersion": REPORT_SCHEMA_VERSION,
            "tool": "godot-game-test-lab",
            "check": "foundation-media-release-report",
            "status": "failed",
            "releaseEvidenceEligible": False,
            "exactHeadBound": False,
            "targetMutationPerformed": False,
            "publicationAuthority": False,
            "findings": [
                {
                    "code": "foundation-media-release-report-error",
                    "severity": "error",
                    "message": str(error),
                }
            ],
        }
    sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return 0 if report.get("status") == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
