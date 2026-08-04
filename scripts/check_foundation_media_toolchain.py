#!/usr/bin/env python3
"""Fail closed when Foundation Kit media and host handoff authority drift."""
from __future__ import annotations

import sys
from pathlib import Path, PurePosixPath

ROOT = Path.cwd().resolve(strict=True)
ERRORS: list[str] = []
FILES = {
    "gate": "src/godot_game_test_lab/foundation_media_plan.py",
    "source_authority": (
        "src/godot_game_test_lab/foundation_media_source_authority.py"
    ),
    "release": "src/godot_game_test_lab/foundation_media_release_report.py",
    "mcp": "src/godot_game_test_lab/foundation_media_mcp.py",
    "tests": "tests/test_foundation_media_plan.py",
    "release_tests": "tests/test_foundation_media_release_report.py",
    "mcp_tests": "tests/test_foundation_media_mcp.py",
    "docs": "docs/FOUNDATION_KIT_MEDIA_PLAN_GATE.md",
    "release_docs": "docs/FOUNDATION_KIT_MEDIA_RELEASE_REPORT.md",
    "linux_workflow": ".github/workflows/reusable-godot-linux-sandbox.yml",
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
        "Foundation current-source authority",
        sources["source_authority"],
        (
            "validate_current_foundation_media_sources",
            "resolve_project_file",
            "read_stable_regular_file",
            "probe_image_bytes",
            "current-audit-root-mismatch",
            "current-plan-audit-root-mismatch",
            "current-plan-audit-authority-split",
            "current-source-identity-mismatch",
            "current-source-extension-mismatch",
            "current-source-png-invalid",
            "current-source-image-evidence-mismatch",
            "current-source-required-blocker-missing",
            "current-source-target-collision-blocker-missing",
            "runtime-target-collision",
            "exact-canvas-mismatch",
            "meaningful-alpha-required",
            "opaque-art-cannot-be-fully-transparent",
            "MAXIMUM_IMAGE_PROBE_BYTES",
        ),
    )
    forbid(
        "Foundation current-source authority",
        sources["source_authority"],
        (
            "git push",
            "git commit",
            "subprocess.run(",
            "shell=True",
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
            "validate_current_foundation_media_sources",
            "_attach_current_source_authority",
            "read_git_state",
            'dirty = value.get("dirty")',
            "return not dirty",
            'report["targetSha"] = target_sha',
            'report["targetClean"] = True',
            'report["exactHeadBound"] = True',
            'report["currentSourceBound"] = current_source_bound',
            'report["releaseEvidenceEligible"] = bool(',
            'report["targetMutationPerformed"] = False',
            'report["publicationAuthority"] = False',
            'policy["currentTargetBytesRechecked"] = True',
            'policy["currentPngEvidenceRechecked"] = True',
            'policy["auditAndPlanRootBound"] = True',
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
            "foundation_build_media_release_report",
            "build_release_report_for_mcp",
            "build_foundation_media_release_report",
            "validate_foundation_media_plan",
            "expected_target_sha: str",
            "Foundation release report target SHA differs from MCP target authority",
            "Rechecking current target bytes, roots and PNG evidence",
            "Foundation Kit exact-head release report complete",
            '"writesTargetRepository": False',
            '"performsGitMutation": False',
            '"longRunningUpstreamOperationsUseTasks": True',
            '"taskCancellationRequired": True',
            "ctx.report_progress",
            "target_only=True",
            "replace=False",
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
            "_rgba(32, 32",
            '"auditRoot": str(audit_root.resolve())',
        ),
    )
    require(
        "Foundation media exact-head release tests",
        sources["release_tests"],
        (
            "test_release_report_binds_clean_exact_head",
            "test_release_report_rejects_dirty_worktree",
            "test_release_report_preserves_plan_failure_and_head_identity",
            "test_release_report_rejects_clean_head_with_stale_audit_bytes",
            "test_release_report_rejects_split_audit_root_authority",
            "test_release_report_rejects_omitted_current_canvas_blocker",
            'assert report["targetSha"] == head',
            'assert report["targetClean"] is True',
            'assert report["currentSourceBound"] is True',
            'assert report["releaseEvidenceEligible"] is True',
            "current-source-identity-mismatch",
            "current-audit-root-mismatch",
            "current-plan-audit-root-mismatch",
            "current-source-required-blocker-missing",
            "exact-canvas-mismatch",
            "strict-plan-blocked-items",
        ),
    )
    require(
        "Foundation media MCP tests",
        sources["mcp_tests"],
        (
            "test_mcp_release_helper_writes_exact_current_source_report",
            "test_mcp_release_helper_is_create_only",
            "test_mcp_release_helper_rejects_target_write",
            "build_release_report_for_mcp",
            'assert report["currentSourceBound"] is True',
            'assert report["releaseEvidenceEligible"] is True',
            "currentBytesRechecked",
            "forbidden-release-report.json",
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
            '"currentSourceBound": true',
            '"releaseEvidenceEligible": true',
            "current target bytes",
            "audit root",
            "testLabArtPlanReport",
            "does not approve creative work or import Godot",
        ),
    )

    require(
        "Linux sandbox hosted-runner ownership handoff",
        sources["linux_workflow"],
        (
            'host_uid="$(id -u)"',
            'host_gid="$(id -g)"',
            "Linux sandbox requires a non-root hosted runner identity",
            '--user "${host_uid}:${host_gid}"',
            'uid=${host_uid},gid=${host_gid}',
            "--env HOME=/home/godotlab",
            'work="${RUNNER_TEMP}/godot-linux-work-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"',
            '[[ ! -e "${work}" ]]',
            "Linux sandbox ephemeral worktree cleanup failed",
        ),
    )
    forbid(
        "Linux sandbox hosted-runner ownership handoff",
        sources["linux_workflow"],
        (
            "uid=10001,gid=10001",
            "--user root",
            "sudo chown",
            "sudo chmod",
            "chmod -R 0777",
        ),
    )

    if ERRORS:
        print("Foundation media toolchain check failed:", file=sys.stderr)
        for error in ERRORS:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("Foundation media toolchain check passed.")
    print("- exact Foundation Kit contract and Art Studio audit remain bound")
    print("- current target bytes, audit roots and PNG evidence are rechecked")
    print("- five authored surfaces and audio listening routes remain explicit")
    print("- clean current HEAD is required for Development Studio evidence")
    print("- exact-head release reports are available through CLI and MCP")
    print("- Linux evidence returns under the non-root hosted runner identity")
    print("- MCP remains root-restricted, progress-aware and mutation-free")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
