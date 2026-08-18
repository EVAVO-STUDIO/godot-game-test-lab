#!/usr/bin/env python3
"""Validate the Godot Game Test Lab capability declaration against live source."""
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
PYPROJECT_PATH = ROOT / "pyproject.toml"

TOP_LEVEL = {"$schema", "contractVersion", "repository", "authority", "summary", "capabilities", "brain", "reviewedAt"}
CAPABILITY_FIELDS = {"id", "title", "description", "interfaces", "effects", "entrypoints", "tags", "requires"}
BRAIN_FIELDS = {"consult", "sanityCheck", "topics"}
INTERFACES = {"api", "automation", "cli", "desktop", "game", "library", "mcp", "mobile", "openapi", "testing", "ui", "web-app"}
EFFECTS = {"read", "compute", "network", "write", "execute", "publish", "financial"}
ID = re.compile(r"^[a-z0-9][a-z0-9._:-]{1,127}$")

EXPECTED_EFFECTS = {
    "testlab.engine.provision": ["read", "compute", "network", "write", "execute"],
    "testlab.project.inspect-audit": ["read", "compute"],
    "testlab.project.validate-runtime": ["read", "compute", "write", "execute"],
    "testlab.qa.native-authored": ["read", "compute", "write", "execute"],
    "testlab.qa.bot": ["read", "compute", "write", "execute"],
    "testlab.sandbox.linux": ["read", "compute", "write", "execute"],
    "testlab.media.analyze": ["read", "compute", "write", "execute"],
    "testlab.asset-delivery.admit": ["read", "compute", "write"],
    "testlab.visual-animation.admit": ["read", "compute", "write"],
    "testlab.rig-motion.accept-v4.1": ["read", "compute", "write", "execute"],
}
EXPECTED_IDS = tuple(EXPECTED_EFFECTS)
EXPECTED_SCRIPTS = {
    "godot-lab": "godot_game_test_lab.cli:main",
    "godot-lab-native-qa": "godot_game_test_lab.native_qa:main",
    "godot-lab-bot-qa": "godot_game_test_lab.bot_qa:main",
    "godot-lab-init-qa": "godot_game_test_lab.profile_bootstrap:main",
    "godot-lab-media-qa": "godot_game_test_lab.media_cli:main",
    "godot-lab-mcp": "godot_game_test_lab.mcp_server:main",
    "godot-lab-engine": "godot_game_test_lab.engine_cli:main",
    "godot-lab-sandbox": "godot_game_test_lab.local_sandbox:main",
}
FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        FAILURES.append(message)


def bounded(value: object, maximum: int) -> bool:
    return isinstance(value, str) and 0 < len(value) <= maximum


def string_array(value: object, maximum_items: int, maximum_length: int) -> list[str]:
    if not isinstance(value, list) or len(value) > maximum_items:
        return []
    if any(not bounded(item, maximum_length) for item in value):
        return []
    if len(set(value)) != len(value):
        return []
    return list(value)


def read(relative: str, maximum_bytes: int = 1_000_000) -> str:
    path = ROOT / relative
    check(path.is_file() and not path.is_symlink(), f"missing regular source file: {relative}")
    if not path.is_file() or path.is_symlink():
        return ""
    try:
        size = path.stat().st_size
        check(0 < size <= maximum_bytes, f"invalid source size: {relative}")
        if size <= 0 or size > maximum_bytes:
            return ""
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        FAILURES.append(f"cannot read {relative}: {error}")
        return ""
    check(not source.startswith("\ufeff"), f"source contains UTF-8 BOM: {relative}")
    check(
        not any(marker in source for marker in ("<<<<<<<", "=======", ">>>>>>>")),
        f"source contains conflict marker: {relative}",
    )
    return source


def includes_all(source: str, markers: tuple[str, ...], label: str) -> None:
    for marker in markers:
        check(marker in source, f"{label} is missing source marker: {marker}")


def validate_manifest_shape() -> tuple[dict, dict[str, dict]]:
    try:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        pyproject = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, tomllib.TOMLDecodeError) as error:
        FAILURES.append(f"manifest/schema/pyproject read failed: {error}")
        return {}, {}

    check(isinstance(schema, dict), "shared schema is not an object")
    check(
        schema.get("$id") == "https://schemas.evavo.local/evavo.repository-capabilities.schema.json",
        "shared schema identity drifted",
    )
    check(
        schema.get("properties", {}).get("contractVersion", {}).get("const")
        == "evavo_repository_capabilities_v1",
        "shared schema contract version drifted",
    )

    check(isinstance(manifest, dict), "manifest is not an object")
    if not isinstance(manifest, dict):
        return {}, {}
    check(set(manifest).issubset(TOP_LEVEL), "manifest has unknown top-level fields")
    check(
        {"contractVersion", "capabilities", "brain"}.issubset(manifest),
        "manifest is missing required top-level fields",
    )
    check(
        manifest.get("$schema") == "./schemas/evavo.repository-capabilities.schema.json",
        "manifest schema path is invalid",
    )
    check(
        manifest.get("contractVersion") == "evavo_repository_capabilities_v1",
        "manifest contract version is invalid",
    )
    check(
        manifest.get("repository") == "EVAVO-STUDIO/godot-game-test-lab",
        "repository identity is invalid",
    )
    check(
        manifest.get("authority") == "independent-godot-validation-and-admission",
        "repository authority drifted",
    )
    check(bounded(manifest.get("summary"), 1200), "manifest summary is invalid")

    reviewed_at = manifest.get("reviewedAt")
    try:
        datetime.fromisoformat(str(reviewed_at).replace("Z", "+00:00"))
        reviewed_valid = True
    except ValueError:
        reviewed_valid = False
    check(reviewed_valid, "reviewedAt is not an ISO date-time")

    brain = manifest.get("brain")
    check(isinstance(brain, dict), "Brain contract is not an object")
    if isinstance(brain, dict):
        check(set(brain).issubset(BRAIN_FIELDS), "Brain contract has unknown fields")
        check(BRAIN_FIELDS.issubset(brain), "Brain contract is incomplete")
        check(brain.get("consult") is True, "Brain consultation must be enabled")
        check(brain.get("sanityCheck") is True, "Brain sanity checking must be enabled")
        topics = string_array(brain.get("topics"), 100, 160)
        check(
            isinstance(brain.get("topics"), list) and len(topics) == len(brain.get("topics", [])),
            "Brain topics are invalid",
        )

    capabilities = manifest.get("capabilities")
    check(
        isinstance(capabilities, list) and 1 <= len(capabilities) <= 200,
        "capability list is invalid",
    )
    capabilities = capabilities if isinstance(capabilities, list) else []
    ids = [entry.get("id") for entry in capabilities if isinstance(entry, dict)]
    check(len(ids) == len(capabilities), "all capabilities must be objects")
    check(len(set(ids)) == len(ids), "capability IDs are not unique")

    for capability in capabilities:
        if not isinstance(capability, dict):
            continue
        capability_id = str(capability.get("id", "unknown"))
        check(set(capability).issubset(CAPABILITY_FIELDS), f"{capability_id} has unknown fields")
        check(CAPABILITY_FIELDS.issubset(capability), f"{capability_id} is incomplete")
        check(bool(ID.fullmatch(str(capability.get("id", "")))), f"{capability_id} has an invalid ID")
        check(bounded(capability.get("title"), 160), f"{capability_id} title is invalid")
        check(bounded(capability.get("description"), 1200), f"{capability_id} description is invalid")

        interfaces = string_array(capability.get("interfaces"), 50, 40)
        effects = string_array(capability.get("effects"), 50, 40)
        entrypoints = string_array(capability.get("entrypoints"), 100, 500)
        tags = string_array(capability.get("tags"), 100, 80)
        requires = string_array(capability.get("requires"), 100, 160)
        check(len(interfaces) == len(capability.get("interfaces", [])), f"{capability_id} interfaces are invalid")
        check(len(effects) == len(capability.get("effects", [])), f"{capability_id} effects are invalid")
        check(len(entrypoints) == len(capability.get("entrypoints", [])), f"{capability_id} entrypoints are invalid")
        check(len(tags) == len(capability.get("tags", [])), f"{capability_id} tags are invalid")
        check(len(requires) == len(capability.get("requires", [])), f"{capability_id} prerequisites are invalid")
        check(all(item in INTERFACES for item in interfaces), f"{capability_id} has unknown interfaces")
        check(all(item in EFFECTS for item in effects), f"{capability_id} has unknown effects")

        for entrypoint in entrypoints:
            looks_like_path = (
                "/" in entrypoint
                and not entrypoint.startswith(("http://", "https://"))
                and (
                    entrypoint.endswith((".py", ".gd", ".json", ".ps1", ".yml", ".md"))
                    or entrypoint.startswith(".")
                )
            )
            if looks_like_path:
                path = ROOT / entrypoint
                check(
                    path.is_file() and not path.is_symlink(),
                    f"{capability_id} references missing source entrypoint {entrypoint}",
                )

    by_id = {entry.get("id"): entry for entry in capabilities if isinstance(entry, dict)}
    check(
        sorted(str(value) for value in by_id) == sorted(EXPECTED_IDS),
        "manifest must contain exactly the ten live Test Lab capabilities",
    )
    for capability_id, expected in EXPECTED_EFFECTS.items():
        check(
            by_id.get(capability_id, {}).get("effects") == expected,
            f"{capability_id} effect authority drifted",
        )
    check(
        all("publish" not in entry.get("effects", []) for entry in capabilities if isinstance(entry, dict)),
        "Test Lab must not claim publish authority",
    )
    check(
        all("financial" not in entry.get("effects", []) for entry in capabilities if isinstance(entry, dict)),
        "Test Lab must not claim financial authority",
    )

    scripts = pyproject.get("project", {}).get("scripts", {})
    check(isinstance(scripts, dict), "pyproject project.scripts is missing")
    for name, target in EXPECTED_SCRIPTS.items():
        check(scripts.get(name) == target, f"pyproject script binding drifted: {name}")
    return manifest, by_id


def validate_live_sources(manifest: dict, by_id: dict[str, dict]) -> None:
    engine = read("src/godot_game_test_lab/engine_manager.py")
    includes_all(
        engine,
        (
            '_ALLOWED_RELEASE_REPOSITORY = "godotengine/godot-builds"',
            "Managed engines must use the official godotengine/godot-builds repository",
            "Engine lock exceeds the bounded size limit",
            "Managed Godot channels must stay within the governed major version",
            "urllib.request",
        ),
        "managed engine provisioner",
    )

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
        ),
        "MCP bridge",
    )

    native_wrapper = read("src/godot_game_test_lab/native_qa.py")
    native_runner = read("src/godot_game_test_lab/native_qa_runner.py")
    includes_all(
        native_wrapper,
        (
            "--expected-lab-sha",
            "--expected-target-sha",
            "--allow-noninteractive",
            '"nativeDesktopEvidence": False',
            "no pass claim is made",
        ),
        "native QA wrapper",
    )
    includes_all(
        native_runner,
        (
            '_validate_exact_checkout(lab_root, expected_lab_sha, "test lab")',
            '_validate_exact_checkout(target_git_root, expected_target_sha, "target repository")',
            '_require_clean_checkout(target_git_root, "target repository")',
            '"targetMutationDetected": mutation',
            "native QA changed the target repository checkout",
            '"physicalControllerCertified": False',
            "It does not certify physical controllers",
        ),
        "native QA runner",
    )

    bot_wrapper = read("src/godot_game_test_lab/bot_qa.py")
    bot_runner = read("src/godot_game_test_lab/bot_runner.py")
    includes_all(
        bot_wrapper,
        (
            "--expected-lab-sha",
            "--expected-target-sha",
            "required bot campaign did not prove a changed runtime state",
            "required bot campaign did not retain a passing non-baseline replay",
        ),
        "bot QA wrapper",
    )
    includes_all(
        bot_runner,
        (
            '_validate_exact_checkout(lab_root, expected_lab_sha, "test lab")',
            '_validate_exact_checkout(target_git_root, expected_target_sha, "target repository")',
            '"targetMutationDetected": mutation',
            "bot QA changed the target repository checkout",
            "bounded deterministic graph",
            "It does not prove complete gameplay",
        ),
        "bot QA runner",
    )

    sandbox = read("src/godot_game_test_lab/local_sandbox.py")
    includes_all(
        sandbox,
        (
            '"--network",\n        "none"',
            '"--read-only"',
            '"--cap-drop",\n        "ALL"',
            '"no-new-privileges"',
            "target=/workspace/source,readonly",
            "Lab and target repositories must be separate checkouts",
            "Target repository is outside the configured allowed roots",
            "Sandbox artifacts must remain outside Lab and target checkouts",
            "_require_clean_exact_checkout",
        ),
        "local Docker sandbox",
    )

    media_cli = read("src/godot_game_test_lab/media_cli.py")
    media = read("src/godot_game_test_lab/media_evidence.py")
    includes_all(
        media_cli,
        (
            "analyze_media_file",
            "normalize_media_policy",
            "scan_run_media",
            "--ffmpeg",
            "--ffprobe",
            "Extract and analyse synchronized audio from retained Godot gameplay movies.",
        ),
        "media QA CLI",
    )
    includes_all(
        media,
        (
            "_MAX_MEDIA_FILES = 128",
            "_MAX_MEDIA_BYTES = 64 * 1024 * 1024 * 1024",
            "media source may not be a symbolic link",
            "ffmpeg",
            "ffprobe",
            "maximumAvSyncDriftSeconds",
            "failOnClipping",
            "failOnSilence",
        ),
        "media evidence engine",
    )

    asset = read("src/godot_game_test_lab/game_asset_delivery_admission.py")
    includes_all(
        asset,
        (
            'REPORT_SCHEMA_ID = "evavo.godot-game-asset-delivery-admission.v1"',
            "game checkout head differs from expected gameHead",
            '"allInstalledBytesVerified": True',
            '"allStorageVersionsVerified": True',
            '"nativeCompositionApproval": False',
            '"publicationAuthority": False',
            "report output already exists",
            "os.link(temporary, destination)",
        ),
        "game-asset delivery admission",
    )

    visual = read("src/godot_game_test_lab/visual_animation_admission.py")
    includes_all(
        visual,
        (
            'REPORT_SCHEMA = "evavo.brass-visual-animation-test-lab-report.v1"',
            "static Art Studio evaluation did not pass",
            "animation Art Studio evaluation did not pass",
            "engine evidence game head differs",
            "engine evidence lacks SpriteFrames render proof",
            '"creativeApproval": False',
            '"historicalApproval": False',
            '"publicationAuthority": False',
        ),
        "visual-animation admission",
    )

    rig = read("tools/rig_motion_acceptance_v4_1.py")
    includes_all(
        rig,
        (
            '"evavo-godot-rig-motion-acceptance-v4.1"',
            '"--headless"',
            "shell=False",
            "no measurable motion",
            '"runtimeAdmission": False',
            '"targetRepositoryMutation": False',
            '"gitMutation": False',
            '"deployment": False',
            '"publication": False',
            '"namedHumanReviewRequired": True',
            'destination.open("x"',
        ),
        "rig-motion acceptance",
    )

    pipeline = read("src/godot_game_test_lab/pipeline.py")
    includes_all(
        pipeline,
        ("minimum_godot_version", "artifacts", "discover_godot_binary"),
        "runtime validation pipeline",
    )

    serialized = json.dumps(manifest, sort_keys=True).lower()
    for boundary in ("does not repair", "publication", "human", "target"):
        check(boundary in serialized, f"manifest must preserve authority/truth boundary: {boundary}")

    for capability_id in (
        "testlab.asset-delivery.admit",
        "testlab.visual-animation.admit",
        "testlab.rig-motion.accept-v4.1",
    ):
        effects = by_id.get(capability_id, {}).get("effects", [])
        check("network" not in effects, f"{capability_id} must not claim network authority")
        check("publish" not in effects, f"{capability_id} must not claim publish authority")


def main() -> int:
    manifest, by_id = validate_manifest_shape()
    if manifest and by_id:
        validate_live_sources(manifest, by_id)
    if FAILURES:
        for failure in FAILURES:
            print(f"FAIL {failure}", file=sys.stderr)
        print(f"{len(FAILURES)} Godot Test Lab capability checks failed.", file=sys.stderr)
        return 1
    print(
        "PASS 10 Godot Test Lab capabilities match the live engine, QA, sandbox, "
        "media and admission source while retaining no target publication or financial authority."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
