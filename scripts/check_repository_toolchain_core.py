#!/usr/bin/env python3
"""Fail-closed source and runtime validation for Godot Game Test Lab."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tomllib
from importlib import metadata
from pathlib import Path, PurePosixPath
from typing import Any

TOOL_VERSION = "0.8.0"
HOSTED_PYTHON = "3.11.15"
NATIVE_PYTHON_FAMILY = (3, 11)
CHECKOUT_V4_SHA = "08eba0b27e820071cde6df949e0beb9ba4906955"
CHECKOUT_V6_SHA = "de0fac2e4500dabe0009e67214ff5f5447ce83dd"
SETUP_PYTHON_SHA = "a309ff8b426b58ec0e2a45f0f869d46889d02405"
UPLOAD_ARTIFACT_SHA = "ea165f8d65b6e75b540449e92b4886f43607fa02"
LINUX_SANDBOX_BASE = (
    "ubuntu:noble-20260610@sha256:"
    "4fbb8e6a8395de5a7550b33509421a2bafbc0aab6c06ba2cef9ebffbc7092d90"
)
ROOT = Path.cwd().resolve(strict=True)
ERRORS: list[str] = []
SAFE_RELATIVE_PATH = re.compile(
    r"^(?!/)(?!.*(?:^|/)\.\.(?:/|$))[A-Za-z0-9._/-]{1,240}$"
)

WORKFLOWS = (
    ".github/workflows/capability-manifest.yml",
    ".github/workflows/ci.yml",
    ".github/workflows/evavo-mainline-confirmation.yml",
    ".github/workflows/evavo-native-godot-validation.yml",
    ".github/workflows/reusable-godot-linux-sandbox.yml",
    ".github/workflows/evavo-linux-godot-sandbox.yml",
    ".github/workflows/linux-sandbox-smoke.yml",
    ".github/workflows/verified-toolchain-transport.yml",
)

EXPECTED_SCRIPTS = {
    "godot-lab": "godot_game_test_lab.cli:main",
    "godot-lab-native-qa": "godot_game_test_lab.native_qa:main",
    "godot-lab-multiplayer-qa": "godot_game_test_lab.multiplayer_qa:main",
    "godot-lab-bot-qa": "godot_game_test_lab.bot_qa:main",
    "godot-lab-init-qa": "godot_game_test_lab.profile_bootstrap:main",
    "godot-lab-media-qa": "godot_game_test_lab.media_cli:main",
    "godot-lab-mcp": "godot_game_test_lab.mcp_server:main",
    "godot-lab-engine": "godot_game_test_lab.engine_cli:main",
    "godot-lab-sandbox": "godot_game_test_lab.local_sandbox:main",
    "godot-lab-rally-falcon-preview": (
        "godot_game_test_lab.rally_falcon_preview:main"
    ),
    "godot-lab-localization-plural": (
        "godot_game_test_lab.localization_plural_runtime_cli:main"
    ),
}


def fail(message: str) -> None:
    ERRORS.append(message)


def source_path(relative: str) -> Path:
    if not SAFE_RELATIVE_PATH.fullmatch(relative):
        raise RuntimeError(f"GODOT_LAB_TOOLCHAIN_PATH_INVALID:{relative}")
    if PurePosixPath(relative).is_absolute():
        raise RuntimeError(f"GODOT_LAB_TOOLCHAIN_PATH_ABSOLUTE:{relative}")
    candidate = ROOT / relative
    absolute = candidate.absolute()
    try:
        absolute.relative_to(ROOT)
    except ValueError as error:
        raise RuntimeError(
            f"GODOT_LAB_TOOLCHAIN_PATH_ESCAPE:{relative}"
        ) from error
    return absolute


def read_text(relative: str, maximum_bytes: int = 4_000_000) -> str:
    candidate = source_path(relative)
    if not candidate.exists():
        raise RuntimeError(f"Missing Godot lab toolchain file: {relative}")
    stat_result = candidate.lstat()
    if not candidate.is_file() or candidate.is_symlink():
        raise RuntimeError(
            f"Godot lab toolchain path must be a regular file: {relative}"
        )
    if candidate.resolve(strict=True) != candidate:
        raise RuntimeError(
            f"Godot lab toolchain path must be canonical: {relative}"
        )
    if stat_result.st_size > maximum_bytes:
        raise RuntimeError(f"Godot lab toolchain file is too large: {relative}")
    try:
        source = candidate.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise RuntimeError(
            f"Godot lab toolchain file is not valid UTF-8: {relative}"
        ) from error
    if source.startswith("\ufeff"):
        raise RuntimeError(f"Godot lab toolchain file contains a BOM: {relative}")
    return source


def canonical_json(relative: str) -> dict[str, Any]:
    source = read_text(relative, 16_000_000)
    try:
        value = json.loads(source)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"Godot lab JSON is invalid: {relative}") from error
    if not isinstance(value, dict):
        raise RuntimeError(f"Godot lab JSON must be an object: {relative}")
    expected = json.dumps(value, indent=2, ensure_ascii=False) + "\n"
    if source != expected:
        raise RuntimeError(f"Godot lab JSON is not canonical: {relative}")
    return value


def require_tokens(relative: str, tokens: tuple[str, ...]) -> str:
    source = read_text(relative)
    for token in tokens:
        if token not in source:
            fail(f"{relative} is missing required token: {token}")
    return source


def forbid_tokens(relative: str, tokens: tuple[str, ...]) -> None:
    source = read_text(relative)
    for token in tokens:
        if token in source:
            fail(f"{relative} contains prohibited token: {token}")


def action_references_are_immutable(relative: str) -> None:
    source = read_text(relative)
    pattern = re.compile(
        r"^\s*uses:\s*([^\s#]+)(?:\s+#.*)?$",
        re.MULTILINE,
    )
    for match in pattern.finditer(source):
        action = match.group(1)
        if action.startswith("./"):
            continue
        reference = action.rsplit("@", 1)[-1] if "@" in action else ""
        if re.fullmatch(r"[a-f0-9]{40}", reference, re.IGNORECASE) is None:
            fail(f"{relative} action must use a full commit SHA: {action}")


def validate_runtime(*, native_family: bool, skip_runtime: bool) -> None:
    if skip_runtime:
        return
    observed = (
        f"{sys.version_info.major}."
        f"{sys.version_info.minor}."
        f"{sys.version_info.micro}"
    )
    if native_family:
        if sys.version_info[:2] != NATIVE_PYTHON_FAMILY:
            fail(f"native Python must be 3.11.x; observed {observed}")
    elif observed != HOSTED_PYTHON:
        fail(f"hosted Python must be {HOSTED_PYTHON}; observed {observed}")


def validate_installed_state() -> None:
    expected_versions = (("pytest", "8.3.0"), ("ruff", "0.9.0"))
    for distribution, expected in expected_versions:
        try:
            observed = metadata.version(distribution)
        except metadata.PackageNotFoundError:
            fail(
                "installed-state validation requires "
                f"{distribution}=={expected}"
            )
            continue
        if observed != expected:
            fail(
                f"installed {distribution} must be {expected}; "
                f"observed {observed}"
            )

    expected_clis = (("pytest", "pytest 8.3.0"), ("ruff", "ruff 0.9.0"))
    for module, expected_prefix in expected_clis:
        result = subprocess.run(
            [sys.executable, "-m", module, "--version"],
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )
        output = (result.stdout or result.stderr).strip()
        if result.returncode != 0 or not output.startswith(expected_prefix):
            fail(f"{module} CLI identity changed: {output or 'unavailable'}")


def validate_agent_installed_state() -> None:
    try:
        observed = metadata.version("mcp")
    except metadata.PackageNotFoundError:
        fail("agent-installed validation requires mcp==1.28.1")
        return
    if observed != "1.28.1":
        fail(f"installed mcp must be 1.28.1; observed {observed}")


def validate_package_identity() -> None:
    if read_text(".python-version", 64) != f"{HOSTED_PYTHON}\n":
        fail(f".python-version must contain exactly {HOSTED_PYTHON}")

    pyproject = tomllib.loads(read_text("pyproject.toml", 128_000))
    if pyproject.get("build-system", {}).get("requires") != [
        "hatchling==1.25.0"
    ]:
        fail("pyproject.toml must pin hatchling==1.25.0")

    project = pyproject.get("project", {})
    if project.get("name") != "godot-game-test-lab":
        fail("pyproject.toml project name changed")
    if project.get("version") != TOOL_VERSION:
        fail(f"pyproject.toml version must be {TOOL_VERSION}")
    if project.get("requires-python") != ">=3.11":
        fail("pyproject.toml Python compatibility declaration changed")
    if project.get("dependencies") != []:
        fail("runtime dependencies must remain empty")
    optional = project.get("optional-dependencies", {})
    if optional.get("dev") != ["pytest==8.3.0", "ruff==0.9.0"]:
        fail("development dependency pins changed")
    if optional.get("agent") != ["mcp==1.28.1"]:
        fail("agent bridge dependency pin changed")
    if project.get("scripts") != EXPECTED_SCRIPTS:
        fail("Godot Lab command entrypoints changed")

    package_source = read_text(
        "src/godot_game_test_lab/__init__.py",
        64_000,
    )
    if f'__version__ = "{TOOL_VERSION}"' not in package_source:
        fail("package runtime version changed")

    force_include = (
        pyproject.get("tool", {})
        .get("hatch", {})
        .get("build", {})
        .get("targets", {})
        .get("wheel", {})
        .get("force-include", {})
    )
    expected_lock = "godot_game_test_lab/godot-engine-lock.json"
    if (
        force_include.get(
            "src/godot_game_test_lab/godot-engine-lock.json"
        )
        != expected_lock
    ):
        fail("managed engine lock is not forced into the wheel")
    if source_path("requirements.lock").exists():
        fail(
            "requirements.lock appeared before the review-first "
            "transition was approved"
        )


def validate_engine_and_reliability() -> None:
    engine_lock = canonical_json(
        "src/godot_game_test_lab/godot-engine-lock.json"
    )
    if (
        engine_lock.get("schemaVersion") != "1.0"
        or engine_lock.get("minimumVersion") != "4.6.2"
        or engine_lock.get("defaultVersion") != "4.6.3"
        or engine_lock.get("channels")
        != {"4.6": "4.6.3", "4.7": "4.7.1"}
        or engine_lock.get("defaultFlavors") != ["standard", "mono"]
        or engine_lock.get("installExportTemplates") is not True
        or engine_lock.get("selfContained") is not True
        or engine_lock.get("releaseRepository")
        != "godotengine/godot-builds"
    ):
        fail("managed Godot engine lock changed")

    profile = canonical_json("evavo.reliability.json")
    if (
        profile.get("schemaVersion") != "1.2"
        or profile.get("toolVersion") != TOOL_VERSION
        or profile.get("repository")
        != "EVAVO-STUDIO/godot-game-test-lab"
        or profile.get("defaultBranch") != "main"
        or profile.get("authority")
        != "canonical-native-and-sandboxed-godot-worker"
        or profile.get("requiredVisibility") != "public"
    ):
        fail("evavo.reliability.json identity changed")

    package_manager = profile.get("packageManager", {})
    if (
        package_manager.get("name") != "pip"
        or package_manager.get("lockfilePath") != "requirements.lock"
        or package_manager.get("lockfilePolicy") != "review-first"
        or package_manager.get("lockfilePresent") is not False
        or package_manager.get("buildBackend") != "hatchling==1.25.0"
        or package_manager.get("directDevelopmentDependencies")
        != ["pytest==8.3.0", "ruff==0.9.0"]
        or package_manager.get("agentDependencies") != ["mcp==1.28.1"]
    ):
        fail("repository-owned Python dependency authority changed")

    runtime = profile.get("runtime", {})
    if (
        runtime.get("hostedPython") != HOSTED_PYTHON
        or runtime.get("nativePythonFamily") != "3.11.x"
        or runtime.get("minimumGodot") != "4.6.2"
        or runtime.get("managedGodotDefault") != "4.6.3"
        or runtime.get("managedGodotChannels")
        != {"4.6": "4.6.3", "4.7": "4.7.1"}
        or runtime.get("linuxSandboxDotnet") != "8.0"
        or runtime.get("linuxSandboxBase") != LINUX_SANDBOX_BASE
    ):
        fail("repository-owned runtime authority changed")

    sandbox = runtime.get("localDockerSandbox", {})
    if (
        sandbox.get("runNetwork") != "none"
        or sandbox.get("targetSourceMount") != "read-only"
        or sandbox.get("rootFilesystem") != "read-only"
        or sandbox.get("sandboxUser") != "10001:10001"
    ):
        fail("local Docker sandbox runtime authority changed")

    branch_policy = profile.get("branchPolicy", {})
    if (
        branch_policy.get("mode") != "direct-main"
        or branch_policy.get("exclusiveLeaseRequired") is not True
        or branch_policy.get("forcePushAllowed") is not False
    ):
        fail("branch and force-push authority changed")

    selection = profile.get("toolSelection", {})
    if (
        selection.get("managedEngineProvisioning")
        != "official-godot-builds-sha512-self-contained"
        or selection.get("localLinuxSandbox")
        != "godot-lab-sandbox-checksum-verified-no-network-runtime"
        or selection.get("pluralLocalizationValidation")
        != (
            "godot-lab-localization-plural-exact-head-"
            "guarded-runtime-probes"
        )
    ):
        fail("managed engine, sandbox, or plural validation selection changed")

    native_stages = profile.get("nativeAcceptance", {}).get(
        "requiredStages",
        [],
    )
    for required_stage in (
        "repository toolchain source check",
        "exact-head plural-localization CSV import and "
        "reviewed runtime lookup probes",
        "final target Git and localization CSV identity recheck",
    ):
        if required_stage not in native_stages:
            fail(f"native acceptance is missing stage: {required_stage}")

    truth = profile.get("truthBoundaries", [])
    if not any(
        "Plural-localization validation proves only the exact requested"
        in item
        for item in truth
    ):
        fail("plural-localization truth boundary is missing")

    blocked = profile.get("autoRepair", {}).get("blockedEffects", [])
    for effect in (
        "target-repository-write-without-grant",
        "release-publication",
        "credential-change",
        "physical-controller-pass-claim-from-synthetic-input",
        "human-ux-approval-claim-from-geometry-telemetry",
        "plural-localization-release-claim-without-"
        "exact-head-runtime-evidence",
    ):
        if effect not in blocked:
            fail(f"auto-repair boundary is missing: {effect}")

    schema = canonical_json(
        "schemas/repository-owned-reliability-profile.schema.json"
    )
    properties = schema.get("properties", {})
    if (
        schema.get("$schema")
        != "https://json-schema.org/draft/2020-12/schema"
        or properties.get("schemaVersion", {}).get("const") != "1.2"
        or properties.get("toolVersion", {}).get("const") != TOOL_VERSION
        or properties.get("repository", {}).get("const")
        != "EVAVO-STUDIO/godot-game-test-lab"
    ):
        fail("repository-owned reliability schema identity changed")


def validate_plural_localization_surface() -> None:
    require_tokens(
        "src/godot_game_test_lab/localization_plural.py",
        (
            "localization-godot-plural-testlab-request-v1",
            "validate_plural_testlab_request",
            "exactHead",
            "targetRepositoryMutationAuthority",
            "publicationAuthority",
        ),
    )
    require_tokens(
        "src/godot_game_test_lab/localization_plural_safe.py",
        (
            "run_plural_localization_validation_safe",
            "capture_git_state",
            "Plural localization CSV bytes changed during validation.",
            "transientProbeRemovedBeforeAcceptance",
            '"targetRepositoryMutationAuthority": False',
            '"publicationAuthority": False',
        ),
    )
    require_tokens(
        "src/godot_game_test_lab/localization_plural_runtime.py",
        (
            "run_plural_localization_runtime_validation",
            "run_plural_localization_validation_safe",
            ".godot may not be a symbolic link",
        ),
    )
    require_tokens(
        "src/godot_game_test_lab/localization_plural_runtime_cli.py",
        (
            "Canonical guarded validator",
            "run_plural_localization_runtime_validation",
            '"targetRepositoryMutationAuthority": False',
            '"publicationAuthority": False',
        ),
    )
    require_tokens(
        "scripts/Invoke-GodotPluralLocalizationValidation.ps1",
        (
            "godot_game_test_lab.localization_plural_runtime_cli",
            '"--request", $Request',
            '"--artifacts", $Artifacts',
        ),
    )
    require_tokens(
        "docs/LOCALIZATION_PLURAL_RUNTIME_VALIDATION.md",
        (
            "python -m godot_game_test_lab.localization_plural_runtime_cli",
            "global subprocess guard",
            "publicationAuthority",
            "not be treated as the final guarded entrypoint",
        ),
    )

    request_schema = canonical_json(
        "schemas/localization-godot-plural-testlab-request.v1.schema.json"
    )
    request_properties = request_schema.get("properties", {})
    if (
        request_properties.get("version", {}).get("const")
        != "localization-godot-plural-testlab-request-v1"
    ):
        fail("plural localization request schema version changed")
    authority = request_properties.get("authority", {}).get(
        "properties",
        {},
    )
    for field in (
        "requestExecutesGodot",
        "requestWritesTarget",
        "requestPublishesTarget",
    ):
        if authority.get(field, {}).get("const") is not False:
            fail(f"plural localization request authority changed: {field}")

    report_schema = canonical_json(
        "schemas/evavo-godot-plural-localization-test-lab-report.v1.schema.json"
    )
    report_properties = report_schema.get("properties", {})
    if (
        report_properties.get("version", {}).get("const")
        != "evavo_godot_plural_localization_test_lab_report_v1"
    ):
        fail("plural localization report schema version changed")
    report_authority = report_properties.get("authority", {}).get(
        "properties",
        {},
    )
    for field in (
        "targetRepositoryMutationAuthority",
        "repairAuthority",
        "publicationAuthority",
    ):
        if report_authority.get(field, {}).get("const") is not False:
            fail(f"plural localization report authority changed: {field}")


def validate_engine_and_sandbox_source() -> None:
    require_tokens(
        "src/godot_game_test_lab/engine_manager.py",
        (
            "SHA512-SUMS.txt",
            "godot-engine-lock.json",
            "engine-installation.json",
            "prepare_estate",
            "mirror_release_assets",
            "payload_sha256",
        ),
    )
    require_tokens(
        "src/godot_game_test_lab/local_sandbox.py",
        (
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "no-new-privileges",
            "targetUnchanged",
        ),
    )
    dockerfile = require_tokens(
        "containers/linux-sandbox/Dockerfile",
        (
            f"FROM {LINUX_SANDBOX_BASE}",
            "ARG GODOT_VERSION=4.6.3",
            "dotnet-sdk-8.0",
            "SHA512-SUMS.txt",
            "USER 10001:10001",
        ),
    )
    first_line = dockerfile.splitlines()[0] if dockerfile else ""
    if "latest" in first_line:
        fail("Linux sandbox base image must not use latest")


def validate_workflows() -> None:
    expected_tokens = {
        ".github/workflows/ci.yml": (
            f"actions/checkout@{CHECKOUT_V6_SHA}",
            f"actions/setup-python@{SETUP_PYTHON_SHA}",
            f'python-version: "{HOSTED_PYTHON}"',
            "python scripts/check_repository_toolchain.py",
            "python scripts/test_repository_toolchain.py",
            "python -m compileall -q src scripts tests",
            "python -m ruff check src scripts tests",
            "python -m pytest",
            "python -m pip wheel --no-deps --wheel-dir dist .",
        ),
        ".github/workflows/evavo-mainline-confirmation.yml": (
            f"actions/checkout@{CHECKOUT_V4_SHA}",
            f"actions/setup-python@{SETUP_PYTHON_SHA}",
            f'python-version: "{HOSTED_PYTHON}"',
            "python scripts/check_repository_toolchain.py",
            "python scripts/test_repository_toolchain.py",
        ),
        ".github/workflows/evavo-native-godot-validation.yml": (
            f"actions/checkout@{CHECKOUT_V4_SHA}",
            "py -3.11 scripts/check_repository_toolchain.py --native-family",
            f"actions/upload-artifact@{UPLOAD_ARTIFACT_SHA}",
        ),
        ".github/workflows/reusable-godot-linux-sandbox.yml": (
            f"actions/checkout@{CHECKOUT_V4_SHA}",
            "--network none",
            "--read-only",
            "--cap-drop ALL",
            "--security-opt no-new-privileges",
        ),
        ".github/workflows/evavo-linux-godot-sandbox.yml": (
            f"actions/checkout@{CHECKOUT_V4_SHA}",
            "--network none",
            "--read-only",
            "--cap-drop ALL",
            "--security-opt no-new-privileges",
        ),
    }
    for relative, tokens in expected_tokens.items():
        require_tokens(relative, tokens)

    for workflow in WORKFLOWS:
        action_references_are_immutable(workflow)
        forbid_tokens(
            workflow,
            (
                "persist-credentials: true",
                "permissions: write-all",
                "contents: write",
                "pull-requests: write",
                "packages: write",
                "git push",
                "gh pr create",
            ),
        )


def main() -> int:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--skip-runtime", action="store_true")
    parser.add_argument("--native-family", action="store_true")
    parser.add_argument("--installed", action="store_true")
    parser.add_argument("--agent-installed", action="store_true")
    args = parser.parse_args()

    if args.skip_runtime and args.native_family:
        parser.error("--skip-runtime and --native-family cannot be combined")

    try:
        validate_package_identity()
        validate_engine_and_reliability()
        validate_plural_localization_surface()
        validate_engine_and_sandbox_source()
        validate_workflows()
        if args.installed:
            validate_installed_state()
        if args.agent_installed:
            validate_agent_installed_state()
        validate_runtime(
            native_family=args.native_family,
            skip_runtime=args.skip_runtime,
        )
    except (OSError, RuntimeError, tomllib.TOMLDecodeError) as error:
        fail(str(error))

    if ERRORS:
        print("Godot lab repository toolchain check failed:", file=sys.stderr)
        for error in ERRORS:
            print(f"- {error}", file=sys.stderr)
        return 1

    print("Godot lab repository toolchain check passed.")
    print(f"- package, runtime and reliability identity agree at {TOOL_VERSION}")
    print("- guarded exact-head plural localization validation is contract-bound")
    print("- Godot, container, workflow and effect boundaries agree")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
