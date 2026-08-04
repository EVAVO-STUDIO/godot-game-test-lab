#!/usr/bin/env python3
"""Fail closed when Foundation Kit media-plan authority drifts."""
from __future__ import annotations

import sys
from pathlib import Path, PurePosixPath

ROOT = Path.cwd().resolve(strict=True)
ERRORS: list[str] = []
FILES = {
    "gate": "src/godot_game_test_lab/foundation_media_plan.py",
    "release": "src/godot_game_test_lab/foundation_media_release_report.py",
    "mcp": "src/godot_game_test_lab/foundation_media_mcp.py",
    "tests": "tests/test_foundation_media_plan.py",
    "release_tests": "tests/test_foundation_media_release_report.py",
    "docs": "docs/FOUNDATION_KIT_MEDIA_PLAN_GATE.md",
    "release_docs": "docs/FOUNDATION_KIT_MEDIA_RELEASE_REPORT.md",
}
MAXIMUM_SOURCE_BYTES = 1_000_000


def fail(message: str) -> None:
    ERRORS.append(message)


def read_text(relative: str) -> str:
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts:
        raise RuntimeError(f"FOUNDATION_MEDIA_SOURCE_PATH_INVALID:{relative}")
    path = ROOT.joinpath(*pure.parts)
    if not path.is_file() or path.is_symlink():
        raise RuntimeError(f"FOUNDATION_MEDIA_SOURCE_FILE_INVALID:{relative}")
    if path.resolve(strict=True) != path.absolute():
        raise RuntimeError(
            f"FOUNDATION_MEDIA_SOURCE_FILE_NONCANONICAL:{relative}"
        )
    if path.stat().st_size > MAXIMUM_SOURCE_BYTES:
        raise RuntimeError(f"FOUNDATION_MEDIA_SOURCE_FILE_TOO_LARGE:{relative}")
    source = path.read_text(encoding="utf-8")
    if source.startswith("\ufeff"):
        raise RuntimeError(f"FOUNDATION_MEDIA_SOURCE_FILE_BOM:{relative}")
    return source


def require(label: str, source: str, tokens: tuple[str, ...]) -> None:
    for token in tokens:
        if token not in source:
            fail(f"{label} is missing required token: {token}")


def forbid(label: str, source: str, tokens: tuple[str, ...]) -> None:
    for token in tokens:
        if token in source:
            fail(f"{label} contains prohibited material: {token}")


def main() -> int:
    try:
        sources = {name: read_text(path) for name, path in FILES.items()}
    except (OSError, UnicodeError, RuntimeError) as error:
        print(f"Foundation media toolchain check failed: {error}", file=sys.stderr)
        return 1

    require(
        "Foundation media gate",
        sources["gate"],
        (
            "evavo_godot_media_production_plan_v1",
            "evavo_godot_media_production_contract_v1",
            "load_art_studio_audit",
            "load_strict_json_object",
            "read_stable_regular_file",
            "portable_path_key",
            "Foundation Kit contract must retain five authored surfaces",
            "plan-game-contract-identity-mismatch",
            "plan-audit-identity-mismatch",
            "plan-work-item-source-drift",
            "plan-work-item-role-drift",
            "plan-summary-invalid",
            "strict-plan-blocked-items",
            "strict-plan-review-required",
            '"requiresAudioAnalysis": audio',
            '"publicationAuthority": False',
            '"deletionAuthority": False',
        ),
    )
    forbid(
        "Foundation media gate",
        sources["gate"],
        (
            "git push",
            "subprocess.run(",
            "unlink(",
            "rmtree(",
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
        ),
    )

    require(
        "Foundation media exact-head release report",
        sources["release"],
        (
            "build_foundation_media_release_report",
            "read_git_state",
            'dirty = value.get("dirty")',
            "return not dirty",
            'report["targetSha"] = target_sha',
            'report["targetClean"] = True',
            'report["exactHeadBound"] = True',
            'report["releaseEvidenceEligible"] = bool(',
            'report["targetMutationPerformed"] = False',
            'report["publicationAuthority"] = False',
            "Target Git state changed while release evidence was built",
            "A clean target worktree is required for release evidence",
            "replace=False",
        ),
    )
    forbid(
        "Foundation media exact-head release report",
        sources["release"],
        (
            "git push",
            "git commit",
            "shell=True",
            "force push",
            "unlink(",
            "rmtree(",
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
        ),
    )

    require(
        "Foundation media MCP",
        sources["mcp"],
        (
            "foundation_media_plan_capabilities",
            "foundation_validate_media_plan",
            "validate_foundation_media_plan",
            '"writesTargetRepository": False',
            '"performsGitMutation": False',
            '"longRunningUpstreamOperationsUseTasks": True',
            '"taskCancellationRequired": True',
            "ctx.report_progress",
            "target_only=True",
            "Streamable HTTP is restricted to an explicit loopback host",
        ),
    )
    forbid(
        "Foundation media MCP",
        sources["mcp"],
        (
            "git push",
            "subprocess.run(",
            "shell=True",
            "force push",
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
        ),
    )

    require(
        "Foundation media tests",
        sources["tests"],
        (
            "test_foundation_contract_passes_strict_validation",
            "test_foundation_plan_retains_review_boundary",
            "test_foundation_plan_repository_mismatch_fails",
            '"nativeViewports"',
            '"requiresAudioAnalysis"',
        ),
    )
    require(
        "Foundation media exact-head release tests",
        sources["release_tests"],
        (
            "test_release_report_binds_clean_exact_head",
            "test_release_report_rejects_dirty_worktree",
            "test_release_report_preserves_plan_failure_and_head_identity",
            'assert report["targetSha"] == head',
            'assert report["targetClean"] is True',
            'assert report["releaseEvidenceEligible"] is True',
            "strict-plan-blocked-items",
        ),
    )

    require(
        "Foundation media documentation",
        sources["docs"],
        (
            "EVAVO-STUDIO/GodotGameFoundationKit",
            "EVAVO Art Studio",
            "EVAVO Audio Studio",
            "Godot Game Test Lab",
            "Godot Web Runtime",
            "EVAVO Development Studio",
            "HUB       640×480",
            "GODZ      640×400",
            "MCP Tasks",
            "signed publication transaction",
        ),
    )
    require(
        "Foundation media exact-head release documentation",
        sources["release_docs"],
        (
            "Foundation Kit exact-head media release report",
            "foundation_media_release_report",
            '"targetSha"',
            '"targetClean": true',
            '"exactHeadBound": true',
            '"releaseEvidenceEligible": true',
            "testLabArtPlanReport",
            "does not approve creative work or import Godot",
        ),
    )

    if ERRORS:
        print("Foundation media toolchain check failed:", file=sys.stderr)
        for error in ERRORS:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("Foundation media toolchain check passed.")
    print("- exact Foundation Kit contract and Art Studio audit remain bound")
    print("- five authored surfaces and audio listening routes remain explicit")
    print("- clean current HEAD is required for Development Studio evidence")
    print("- MCP remains root-restricted, progress-aware and mutation-free")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
