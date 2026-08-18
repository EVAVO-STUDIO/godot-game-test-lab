#!/usr/bin/env python3
"""Validate the EVAVO Godot Game Test Lab capability manifest against live source."""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import re
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "evavo.capabilities.json"
SCHEMA_PATH = ROOT / "schemas/evavo.repository-capabilities.schema.json"

TOP_LEVEL = {"$schema", "contractVersion", "repository", "authority", "summary", "capabilities", "brain", "reviewedAt"}
CAPABILITY_FIELDS = {"id", "title", "description", "interfaces", "effects", "entrypoints", "tags", "requires"}
BRAIN_FIELDS = {"consult", "sanityCheck", "topics"}
INTERFACES = {"api", "automation", "cli", "desktop", "game", "library", "mcp", "mobile", "openapi", "testing", "ui", "web-app"}
EFFECTS = {"read", "compute", "network", "write", "execute", "publish", "financial"}
ID = re.compile(r"^[a-z0-9][a-z0-9._:-]{1,127}$")
REQUIRED_CAPABILITIES = (
    "testlab.engine.provision",
    "testlab.project.inspect-audit",
    "testlab.project.validate-runtime",
    "testlab.qa.native-authored",
    "testlab.qa.bot",
    "testlab.sandbox.linux",
    "testlab.media.analyze",
    "testlab.asset-delivery.admit",
    "testlab.visual-animation.admit",
    "testlab.rig-motion.accept-v4.1",
)
FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        FAILURES.append(message)


def read(relative: str) -> str:
    path = ROOT / relative
    check(path.is_file() and not path.is_symlink(), f"missing regular source file: {relative}")
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def includes_all(source: str, markers: tuple[str, ...], label: str) -> None:
    for marker in markers:
        check(marker in source, f"{label} is missing source marker: {marker}")


def bounded(value: object, maximum: int) -> bool:
    return isinstance(value, str) and 0 < len(value) <= maximum


def valid_string_array(value: object, maximum_items: int, maximum_length: int) -> bool:
    return (
        isinstance(value, list)
        and len(value) <= maximum_items
        and len(set(value)) == len(value)
        and all(bounded(item, maximum_length) for item in value)
    )


def main() -> int:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    pyproject = tomllib.loads(read("pyproject.toml"))

    check(schema.get("$id") == "https://schemas.evavo.local/evavo.repository-capabilities.schema.json", "schema identity drifted")
    check(schema.get("properties", {}).get("contractVersion", {}).get("const") == "evavo_repository_capabilities_v1", "schema contract version drifted")

    check(set(manifest).issubset(TOP_LEVEL), "manifest has unknown top-level fields")
    check({"contractVersion", "capabilities", "brain"}.issubset(manifest), "manifest is missing required top-level fields")
    check(manifest.get("$schema") == "./schemas/evavo.repository-capabilities.schema.json", "manifest schema path is invalid")
    check(manifest.get("contractVersion") == "evavo_repository_capabilities_v1", "manifest contract version is invalid")
    check(manifest.get("repository") == "EVAVO-STUDIO/godot-game-test-lab", "repository identity is invalid")
    check(manifest.get("authority") == "independent-godot-validation-and-admission", "repository authority drifted")
    check(bounded(manifest.get("summary"), 1200), "manifest summary is invalid")
    try:
        datetime.fromisoformat(str(manifest.get("reviewedAt")).replace("Z", "+00:00"))
        reviewed_valid = True
    except ValueError:
        reviewed_valid = False
    check(reviewed_valid, "reviewedAt is not an ISO date-time")

    brain = manifest.get("brain")
    check(isinstance(brain, dict), "Brain contract is not an object")
    if isinstance(brain, dict):
        check(set(brain).issubset(BRAIN_FIELDS), "Brain contract has unknown fields")
        check(BRAIN_FIELDS.issubset(brain), "Brain contract is incomplete")
        check(brain.get("consult") is True and brain.get("sanityCheck") is True, "Brain consultation/sanity contract is not enabled")
        check(valid_string_array(brain.get("topics"), 100, 160), "Brain topics are invalid")

    capabilities = manifest.get("capabilities")
    check(isinstance(capabilities, list) and len(capabilities) == len(REQUIRED_CAPABILITIES), "manifest must contain exactly ten live Test Lab capabilities")
    capabilities = capabilities if isinstance(capabilities, list) else []
    ids = [entry.get("id") for entry in capabilities if isinstance(entry, dict)]
    check(len(ids) == len(capabilities), "all capabilities must be objects")
    check(len(set(ids)) == len(ids), "capability IDs are not unique")
    check(sorted(str(value) for value in ids) == sorted(REQUIRED_CAPABILITIES), "required Test Lab capability set drifted")

    scripts = pyproject.get("project", {}).get("scripts", {})
    source_files = {
        "src/godot_game_test_lab/engine_manager.py",
        "src/godot_game_test_lab/integrity.py",
        "src/godot_game_test_lab/pipeline.py",
        "src/godot_game_test_lab/native_qa.py",
        "src/godot_game_test_lab/bot_qa.py",
        "src/godot_game_test_lab/linux_sandbox.py",
        "src/godot_game_test_lab/media_cli.py",
        "src/godot_game_test_lab/game_asset_delivery_admission.py",
        "src/godot_game_test_lab/visual_animation_admission.py",
        "tools/rig_motion_acceptance_v4_1.py",
        "tools/rig_motion_probe_v4_1.gd",
        "docs/RIG_MOTION_ACCEPTANCE_V4_1.md",
        "config/visual-animation-admission.v1.json",
        "scripts/check_game_asset_delivery_admission.py",
        "scripts/Invoke-GodotLabNativeAgentQA.ps1",
        "scripts/Invoke-GodotLabBotQA.ps1",
        "scripts/Invoke-GodotLabLinuxSandbox.ps1",
    }
    for relative in source_files:
        path = ROOT / relative
        check(path.is_file() and not path.is_symlink(), f"declared Test Lab source surface is missing: {relative}")

    for capability in capabilities:
        if not isinstance(capability, dict):
            continue
        capability_id = str(capability.get("id", "unknown"))
        check(set(capability).issubset(CAPABILITY_FIELDS), f"{capability_id} has unknown fields")
        check(CAPABILITY_FIELDS.issubset(capability), f"{capability_id} is incomplete")
        check(bool(ID.fullmatch(str(capability.get("id", "")))), f"{capability_id} has an invalid ID")
        check(bounded(capability.get("title"), 160), f"{capability_id} title is invalid")
        check(bounded(capability.get("description"), 1200), f"{capability_id} description is invalid")
        check(valid_string_array(capability.get("interfaces"), 50, 40), f"{capability_id} interfaces are invalid")
        check(valid_string_array(capability.get("effects"), 50, 40), f"{capability_id} effects are invalid")
        check(valid_string_array(capability.get("entrypoints"), 100, 500), f"{capability_id} entrypoints are invalid")
        check(valid_string_array(capability.get("tags"), 100, 80), f"{capability_id} tags are invalid")
        check(valid_string_array(capability.get("requires"), 100, 160), f"{capability_id} prerequisites are invalid")
        check(all(item in INTERFACES for item in capability.get("interfaces", [])), f"{capability_id} has unknown interfaces")
        check(all(item in EFFECTS for item in capability.get("effects", [])), f"{capability_id} has unknown effects")
        check("publish" not in capability.get("effects", []), f"{capability_id} must not claim publication authority")
        check("financial" not in capability.get("effects", []), f"{capability_id} must not claim financial authority")

        for entrypoint in capability.get("entrypoints", []):
            if entrypoint in scripts:
                continue
            if entrypoint.startswith(("src/", "scripts/", "tools/", "docs/", "config/")):
                path = ROOT / entrypoint
                check(path.is_file() and not path.is_symlink(), f"{capability_id} references missing path {entrypoint}")

    by_id = {entry.get("id"): entry for entry in capabilities if isinstance(entry, dict)}
    inspect_effects = by_id.get("testlab.project.inspect-audit", {}).get("effects", [])
    check(inspect_effects == ["read", "compute"], "project inspection/audit must remain strictly read/compute")
    for capability_id in (
        "testlab.asset-delivery.admit",
        "testlab.visual-animation.admit",
    ):
        effects = by_id.get(capability_id, {}).get("effects", [])
        check(effects == ["read", "compute", "write"], f"{capability_id} must remain create-only admission evidence without execution/network authority")

    for command in (
        "godot-lab",
        "godot-lab-mcp",
        "godot-lab-engine",
        "godot-lab-native-qa",
        "godot-lab-bot-qa",
        "godot-lab-media-qa",
        "godot-lab-sandbox",
    ):
        check(command in scripts, f"pyproject no longer exposes script: {command}")

    mcp = read("src/godot_game_test_lab/mcp_server.py")
    includes_all(
        mcp,
        (
            "The server never edits or publishes a target game.",
            '@mcp.tool(name="godot_ensure_engine"',
            '@mcp.tool(name="godot_inspect"',
            '@mcp.tool(name="godot_audit"',
            '@mcp.tool(name="godot_validate"',
            '@mcp.tool(name="godot_run_bot_qa"',
            '@mcp.tool(name="godot_run_native_qa"',
            '@mcp.tool(name="godot_run_linux_sandbox"',
            "exact-SHA no-network Linux software-rendered Godot QA",
            'args.host not in {"127.0.0.1", "::1"}',
        ),
        "MCP server",
    )

    engine = read("src/godot_game_test_lab/engine_manager.py")
    includes_all(
        engine,
        (
            "godotengine/godot-builds/releases/download",
            "sha256",
            "offline",
        ),
        "engine manager",
    )

    native = read("src/godot_game_test_lab/native_qa.py")
    includes_all(
        native,
        (
            "godot_lab.native_qa_report.v3",
            "expected_lab_sha",
            "expected_target_sha",
            "non_interactive_contract_only",
        ),
        "native QA",
    )

    sandbox = read("src/godot_game_test_lab/local_sandbox.py")
    includes_all(
        sandbox,
        (
            '"--network",',
            '"none",',
            '"--read-only",',
            'f"{source_project}:/workspace/source:ro"',
            '"--unshare-net",',
            "Sandbox run root must be outside the source project",
            "Artifact root must be outside the source project",
        ),
        "local/Linux sandbox",
    )

    visual = read("src/godot_game_test_lab/visual_animation_admission.py")
    includes_all(
        visual,
        (
            "evavo.brass-visual-animation-test-lab-report.v1",
            '"creativeApproval": False',
            '"historicalApproval": False',
            '"publicationAuthority": False',
            '"publicationAuthority": false',
        ),
        "visual-animation admission",
    )

    game_asset = read("src/godot_game_test_lab/game_asset_delivery_admission.py")
    includes_all(
        game_asset,
        (
            "evavo.game-asset-delivery-test-lab-report.v1",
            "evavo.game-asset-delivery.v1",
            "evavo.game-asset-storage-admission.v1",
            "nativeCompositionApproval",
            "publicationAuthority",
            "write_report_create_only",
        ),
        "game-asset delivery admission",
    )

    rig = read("tools/rig_motion_acceptance_v4_1.py")
    includes_all(
        rig,
        (
            'SCHEMA_VERSION = "4.1"',
            "evavo-rig-motion-acceptance-manifest-v4.1",
            "evavo-rig-motion-acceptance-receipt-v4.1",
            '"runtimeAdmissionAuthorityGranted": False',
            '"targetRepositoryMutationAuthorityGranted": False',
            '"gitMutationAuthorityGranted": False',
            '"deploymentAuthorityGranted": False',
            '"publicationAuthorityGranted": False',
            "human review",
            "FileExistsError",
        ),
        "rig-motion acceptance v4.1",
    )

    media = read("src/godot_game_test_lab/media_cli.py")
    includes_all(media, ("ffprobe", "analyze_audio", "compare_images"), "media QA")

    tests = {
        "tests/test_visual_animation_admission.py": (
            "test_changed_candidate_bytes_fail_closed",
            "test_missing_spriteframes_reference_fails_closed",
        ),
        "tests/test_game_asset_delivery_admission.py": (
            "test_native_evidence_produces_technical_pass_without_approval",
            "test_installed_byte_tamper_is_rejected",
            "test_create_only_report",
        ),
        "tests/test_rig_motion_acceptance_v4_1.py": (
            "test_authority_escalation_rejected",
            "test_zero_motion_rejected",
        ),
    }
    for relative, markers in tests.items():
        includes_all(read(relative), markers, relative)

    serialized = json.dumps(manifest, sort_keys=True).lower()
    for boundary in ("does not repair", "does not", "publication", "target-repository", "human", "exact"):
        check(boundary in serialized, f"manifest is missing boundary language: {boundary}")

    if FAILURES:
        for failure in FAILURES:
            print(f"FAIL {failure}", file=sys.stderr)
        print(f"{len(FAILURES)} Godot Test Lab capability checks failed.", file=sys.stderr)
        return 1

    print("PASS 10 Godot Test Lab capabilities are schema-bounded, source-backed, target-mutation-safe and publication-free.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
