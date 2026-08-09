#!/usr/bin/env python3
"""Fail closed when the Art Studio asset-audit and media-plan authority drifts."""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path, PurePosixPath

ROOT = Path.cwd().resolve(strict=True)
ERRORS: list[str] = []
MAXIMUM_SOURCE_BYTES = 1_000_000
FILES = {
    "cli": "src/godot_game_test_lab/asset_audit.py",
    "checks": "src/godot_game_test_lab/asset_audit_checks.py",
    "contract": "src/godot_game_test_lab/asset_audit_contract.py",
    "contractGroups": "src/godot_game_test_lab/asset_audit_contract_groups.py",
    "contractScalar": "src/godot_game_test_lab/asset_audit_contract_scalar.py",
    "io": "src/godot_game_test_lab/asset_audit_io.py",
    "mcp": "src/godot_game_test_lab/asset_audit_mcp.py",
    "mcpPolicy": "src/godot_game_test_lab/asset_audit_mcp_policy.py",
    "model": "src/godot_game_test_lab/asset_audit_model.py",
    "png": "src/godot_game_test_lab/asset_audit_png.py",
    "validation": "src/godot_game_test_lab/asset_audit_validation.py",
    "strictJson": "src/godot_game_test_lab/strict_json.py",
    "mediaPlan": "src/godot_game_test_lab/media_production_plan.py",
    "fixtures": "tests/asset_audit_fixtures.py",
    "tests": "tests/test_asset_audit.py",
    "authorityTests": "tests/test_asset_audit_authority.py",
    "mcpTests": "tests/test_asset_audit_mcp.py",
    "pngTests": "tests/test_asset_audit_png.py",
    "releaseTests": "tests/test_asset_audit_release_contract.py",
    "mediaPlanTests": "tests/test_media_production_plan.py",
    "docs": "docs/ART_STUDIO_ASSET_AUDIT.md",
    "mediaPlanDocs": "docs/MEDIA_PRODUCTION_PLAN_GATE.md",
    "pyproject": "pyproject.toml",
}


def fail(message: str) -> None:
    ERRORS.append(message)


def read_text(relative: str) -> str:
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts:
        raise RuntimeError(f"ASSET_AUDIT_SOURCE_PATH_INVALID:{relative}")
    candidate = ROOT.joinpath(*pure.parts)
    if not candidate.is_file() or candidate.is_symlink():
        raise RuntimeError(f"ASSET_AUDIT_SOURCE_FILE_INVALID:{relative}")
    if candidate.resolve(strict=True) != candidate.absolute():
        raise RuntimeError(f"ASSET_AUDIT_SOURCE_FILE_NONCANONICAL:{relative}")
    if candidate.stat().st_size > MAXIMUM_SOURCE_BYTES:
        raise RuntimeError(f"ASSET_AUDIT_SOURCE_FILE_TOO_LARGE:{relative}")
    source = candidate.read_text(encoding="utf-8")
    if source.startswith("\ufeff"):
        raise RuntimeError(f"ASSET_AUDIT_SOURCE_FILE_BOM:{relative}")
    return source


def require_tokens(label: str, source: str, tokens: tuple[str, ...]) -> None:
    for token in tokens:
        if token not in source:
            fail(f"{label} is missing required token: {token}")


def forbid_tokens(label: str, source: str, tokens: tuple[str, ...]) -> None:
    for token in tokens:
        if token in source:
            fail(f"{label} contains prohibited material: {token}")


def main() -> int:
    try:
        sources = {name: read_text(path) for name, path in FILES.items()}
    except (OSError, UnicodeError, RuntimeError) as error:
        print(f"Asset-audit toolchain check failed: {error}", file=sys.stderr)
        return 1

    try:
        pyproject = tomllib.loads(sources["pyproject"])
    except tomllib.TOMLDecodeError:
        fail("pyproject.toml must remain valid TOML")
        pyproject = {}
    scripts = pyproject.get("project", {}).get("scripts", {})
    if set(scripts) != {
        "godot-lab",
        "godot-lab-native-qa",
        "godot-lab-bot-qa",
        "godot-lab-init-qa",
        "godot-lab-media-qa",
        "godot-lab-mcp",
        "godot-lab-engine",
        "godot-lab-sandbox",
        "godot-lab-pixel-font",
    }:
        fail("asset-audit hardening must not silently change the nine governed package entrypoints")
    per_file = (
        pyproject.get("tool", {})
        .get("ruff", {})
        .get("lint", {})
        .get("per-file-ignores", {})
    )
    if any(
        "asset_audit" in source_path or "media_production_plan" in source_path
        for source_path in per_file
    ):
        fail("asset-audit and media-plan source may not use a Ruff per-file exemption")

    require_tokens(
        "asset-audit CLI",
        sources["cli"],
        (
            "from collections.abc import Sequence",
            "default_evidence_root",
            "write_evidence_json",
            "--replace-output",
            "--expected-target-sha",
        ),
    )
    require_tokens(
        "asset-audit validation",
        sources["validation"],
        (
            "load_art_studio_audit",
            'REPORT_SCHEMA_VERSION = "1.1"',
            '"finalIdentityRecheck": True',
            "read_stable_regular_file",
            "maximum_total_asset_bytes",
            "require_clean_target",
            "asset-changed-after-admission",
            "inventory_art_files",
        ),
    )
    forbid_tokens(
        "asset-audit validation",
        sources["validation"],
        (".read_bytes()", "json.loads("),
    )
    require_tokens(
        "asset-audit contract",
        sources["contract"],
        (
            "load_strict_json_object",
            "Unsupported Art Studio audit schemaVersion",
            "audit.duplicateGroups does not exactly match",
            "auditSummary",
            "missingAssetReferences",
        ),
    )
    forbid_tokens(
        "asset-audit contract",
        sources["contract"],
        ("json.loads(", "json.load("),
    )
    require_tokens(
        "asset-audit stable IO",
        sources["io"],
        (
            "os.open(source, flags)",
            "os.path.samestat",
            "portable_path_key",
            "write_evidence_json",
            "os.O_EXCL",
            "os.replace",
            "Existing output is not a prior Godot Lab asset-audit report",
            "Asset-audit output must remain strictly beneath EvidenceRoot",
        ),
    )
    require_tokens(
        "asset-audit PNG probe",
        sources["png"],
        (
            "PNG chunk CRC mismatch",
            "PNG IDAT chunks must remain consecutive",
            "PNG scanline data does not match the declared canvas",
            "bit_depth == 16",
            "filter_type == 4",
            "MAX_DECODED_ALPHA_BYTES",
        ),
    )
    require_tokens(
        "asset-audit MCP",
        sources["mcp"],
        (
            "godot_asset_audit_capabilities",
            "godot_validate_art_audit",
            "godot_validate_media_production_plan",
            "validate_media_production_plan",
            '"writesTargetRepository": False',
            '"performsGitMutation": False',
            "allow_evidence_root=False",
            "Streamable HTTP is restricted to an explicit loopback host",
        ),
    )
    require_tokens(
        "asset-audit MCP policy",
        sources["mcpPolicy"],
        (
            "Target Git root must remain disjoint from the Lab",
            "Target contains multiple Godot projects; project_subpath is required",
            "Art Studio audit must remain inside the target Git root or evidence root",
            "expected_target_sha",
        ),
    )
    for label in ("mcp", "mcpPolicy"):
        forbid_tokens(
            f"asset-audit {label}",
            sources[label],
            (
                "from .agent_bridge import",
                "BridgeConfig",
                "engine_root",
                "git push",
            ),
        )
    require_tokens(
        "media production-plan gate",
        sources["mediaPlan"],
        (
            "load_art_studio_audit",
            "load_strict_json_object",
            "read_stable_regular_file",
            "portable_path_key",
            "brass_brine_media_production_plan_v1",
            "plan-game-contract-identity-mismatch",
            "plan-audit-identity-mismatch",
            "plan-work-item-source-drift",
            "plan-work-item-role-drift",
            "plan-summary-invalid",
            "strict-plan-blocked-items",
            "strict-plan-review-required",
            '"publicationAuthority": False',
            '"deletionAuthority": False',
        ),
    )
    forbid_tokens(
        "media production-plan gate",
        sources["mediaPlan"],
        (
            "git push",
            "subprocess.run(",
            "unlink(",
            "rmtree(",
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
        ),
    )
    require_tokens(
        "asset-audit release tests",
        sources["releaseTests"],
        (
            "test_asset_audit_source_and_policy_are_permanently_governed",
            "test_asset_audit_has_no_ruff_exemption",
            "test_asset_audit_mcp_self_test_uses_root_restricted_configuration",
            "media_production_plan.py",
            "godot_validate_media_production_plan",
        ),
    )
    require_tokens(
        "asset-audit PNG tests",
        sources["pngTests"],
        (
            "test_png_probe_rejects_crc_mismatch",
            "test_png_probe_rejects_non_consecutive_idat",
            "test_png_probe_rejects_invalid_filter_type",
            "test_png_probe_rejects_decompression_bomb",
        ),
    )
    require_tokens(
        "asset-audit docs",
        sources["docs"],
        (
            "technical evidence only",
            "does not delete files",
            "does not publish or deploy",
        ),
    )
    require_tokens(
        "media production-plan docs",
        sources["mediaPlanDocs"],
        (
            "read-only admission gate",
            "publication authority",
            "deletion authority",
        ),
    )

    if ERRORS:
        print("Godot asset-audit toolchain check failed:", file=sys.stderr)
        print(file=sys.stderr)
        for error in ERRORS:
            print(f"- {error}", file=sys.stderr)
        return 1

    print("Godot asset-audit toolchain check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
