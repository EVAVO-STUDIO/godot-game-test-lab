#!/usr/bin/env python3
"""Fail-closed source and runtime validation for the Godot Game Test Lab."""

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

HOSTED_PYTHON = "3.11.15"
NATIVE_PYTHON_FAMILY = (3, 11)
CHECKOUT_V4_SHA = "08eba0b27e820071cde6df949e0beb9ba4906955"
CHECKOUT_V6_SHA = "de0fac2e4500dabe0009e67214ff5f5447ce83dd"
SETUP_PYTHON_SHA = "a309ff8b426b58ec0e2a45f0f869d46889d02405"
UPLOAD_ARTIFACT_SHA = "ea165f8d65b6e75b540449e92b4886f43607fa02"
LINUX_SANDBOX_BASE = (
    "ubuntu:noble-20260610@sha256:4fbb8e6a8395de5a7550b33509421a2bafbc0aab6c06ba2cef9ebffbc7092d90"
)
ROOT = Path.cwd().resolve(strict=True)
ERRORS: list[str] = []
SAFE_RELATIVE_PATH = re.compile(r"^(?!/)(?!.*(?:^|/)\.\.(?:/|$))[A-Za-z0-9._/-]{1,240}$")

WORKFLOWS = (
    ".github/workflows/ci.yml",
    ".github/workflows/evavo-mainline-confirmation.yml",
    ".github/workflows/evavo-native-godot-validation.yml",
    ".github/workflows/reusable-godot-linux-sandbox.yml",
    ".github/workflows/evavo-linux-godot-sandbox.yml",
    ".github/workflows/linux-sandbox-smoke.yml",
)


def fail(message: str) -> None:
    ERRORS.append(message)


def source_path(relative: str) -> Path:
    if not SAFE_RELATIVE_PATH.fullmatch(relative) or PurePosixPath(relative).is_absolute():
        raise RuntimeError(f"GODOT_LAB_TOOLCHAIN_PATH_INVALID:{relative}")
    candidate = ROOT / relative
    absolute = candidate.absolute()
    try:
        absolute.relative_to(ROOT)
    except ValueError as error:
        raise RuntimeError(f"GODOT_LAB_TOOLCHAIN_PATH_ESCAPE:{relative}") from error
    return absolute


def read_text(relative: str, maximum_bytes: int = 4_000_000) -> str:
    candidate = source_path(relative)
    if not candidate.exists():
        raise RuntimeError(f"Missing Godot lab toolchain file: {relative}")
    stat = candidate.lstat()
    if not stat.st_mode or not candidate.is_file() or candidate.is_symlink():
        raise RuntimeError(f"Godot lab toolchain path must be a regular file: {relative}")
    real = candidate.resolve(strict=True)
    if real != candidate:
        raise RuntimeError(f"Godot lab toolchain path must be canonical: {relative}")
    if stat.st_size > maximum_bytes:
        raise RuntimeError(f"Godot lab toolchain file is too large: {relative}")
    try:
        source = candidate.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise RuntimeError(f"Godot lab toolchain file is not valid UTF-8: {relative}") from error
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


def require_tokens(relative: str, tokens: tuple[str, ...] | list[str]) -> str:
    source = read_text(relative)
    for token in tokens:
        if token not in source:
            fail(f"{relative} is missing required token: {token}")
    return source


def forbid_tokens(relative: str, tokens: tuple[str, ...] | list[str]) -> None:
    source = read_text(relative)
    for token in tokens:
        if token in source:
            fail(f"{relative} contains prohibited token: {token}")


def action_references_are_immutable(relative: str, allow_local: bool = False) -> None:
    source = read_text(relative)
    for match in re.finditer(r"^\s*uses:\s*([^\s#]+)(?:\s+#.*)?$", source, re.MULTILINE):
        action = match.group(1)
        if allow_local and action.startswith("./"):
            continue
        reference = action.rsplit("@", 1)[-1] if "@" in action else ""
        if re.fullmatch(r"[a-f0-9]{40}", reference, re.IGNORECASE) is None:
            fail(f"{relative} action must use a full commit SHA: {action}")


def validate_runtime(allow_native_family: bool, skip_runtime: bool) -> None:
    if skip_runtime:
        return
    observed = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if allow_native_family:
        if sys.version_info[:2] != NATIVE_PYTHON_FAMILY:
            fail(f"native Python must be 3.11.x; observed {observed}")
    elif observed != HOSTED_PYTHON:
        fail(f"hosted Python must be {HOSTED_PYTHON}; observed {observed}")


def validate_installed_state() -> None:
    for distribution, expected in (
        ("pytest", "8.3.0"),
        ("ruff", "0.9.0"),
    ):
        try:
            observed = metadata.version(distribution)
        except metadata.PackageNotFoundError:
            fail(f"installed-state validation requires {distribution}=={expected}")
            continue
        if observed != expected:
            fail(f"installed {distribution} must be {expected}; observed {observed}")

    for module, expected_prefix in (
        ("pytest", "pytest 8.3.0"),
        ("ruff", "ruff 0.9.0"),
    ):
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


def main() -> int:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--skip-runtime", action="store_true")
    parser.add_argument("--native-family", action="store_true")
    parser.add_argument("--installed", action="store_true")
    parser.add_argument("--agent-installed", action="store_true")
    args = parser.parse_args()

    if args.skip_runtime and args.native_family:
        parser.error("--skip-runtime and --native-family cannot be combined")

    if read_text(".python-version", 64) != f"{HOSTED_PYTHON}\n":
        fail(f".python-version must contain exactly {HOSTED_PYTHON}")

    pyproject_source = read_text("pyproject.toml", 128_000)
    pyproject = tomllib.loads(pyproject_source)
    if pyproject.get("build-system", {}).get("requires") != ["hatchling==1.25.0"]:
        fail("pyproject.toml must pin hatchling==1.25.0")
    project = pyproject.get("project", {})
    if project.get("name") != "godot-game-test-lab" or project.get("version") != "0.7.0":
        fail("pyproject.toml project identity changed")
    package_source = read_text("src/godot_game_test_lab/__init__.py", 64_000)
    if '__version__ = "0.7.0"' not in package_source:
        fail("package runtime version changed")

    engine_lock = canonical_json("src/godot_game_test_lab/godot-engine-lock.json")
    if (
        engine_lock.get("schemaVersion") != "1.0"
        or engine_lock.get("minimumVersion") != "4.6.2"
        or engine_lock.get("defaultVersion") != "4.6.3"
        or engine_lock.get("channels") != {"4.6": "4.6.3", "4.7": "4.7.1"}
        or engine_lock.get("defaultFlavors") != ["standard", "mono"]
        or engine_lock.get("installExportTemplates") is not True
        or engine_lock.get("selfContained") is not True
        or engine_lock.get("releaseRepository") != "godotengine/godot-builds"
    ):
        fail("managed Godot engine lock changed")

    if project.get("requires-python") != ">=3.11":
        fail("pyproject.toml Python compatibility declaration changed")
    if project.get("dependencies") != []:
        fail("runtime dependencies must remain empty")
    optional = project.get("optional-dependencies", {})
    if optional.get("dev") != ["pytest==8.3.0", "ruff==0.9.0"]:
        fail("development dependency pins changed")
    if optional.get("agent") != ["mcp==1.28.1"]:
        fail("agent bridge dependency pin changed")

    scripts = project.get("scripts", {})
    expected_scripts = {
        "godot-lab": "godot_game_test_lab.cli:main",
        "godot-lab-native-qa": "godot_game_test_lab.native_qa:main",
        "godot-lab-bot-qa": "godot_game_test_lab.bot_qa:main",
        "godot-lab-init-qa": "godot_game_test_lab.profile_bootstrap:main",
        "godot-lab-media-qa": "godot_game_test_lab.media_cli:main",
        "godot-lab-mcp": "godot_game_test_lab.mcp_server:main",
        "godot-lab-engine": "godot_game_test_lab.engine_cli:main",
        "godot-lab-sandbox": "godot_game_test_lab.local_sandbox:main",
    }
    if scripts != expected_scripts:
        fail("Godot Lab command entrypoints changed")
    force_include = (
        pyproject.get("tool", {})
        .get("hatch", {})
        .get("build", {})
        .get("targets", {})
        .get("wheel", {})
        .get("force-include", {})
    )
    if force_include.get("src/godot_game_test_lab/godot-engine-lock.json") != (
        "godot_game_test_lab/godot-engine-lock.json"
    ):
        fail("managed engine lock is not forced into the wheel")

    if source_path("requirements.lock").exists():
        fail("requirements.lock appeared before the review-first transition was approved")

    profile = canonical_json("evavo.reliability.json")
    if (
        profile.get("schemaVersion") != "1.2"
        or profile.get("toolVersion") != "0.7.0"
        or profile.get("repository") != "EVAVO-STUDIO/godot-game-test-lab"
        or profile.get("defaultBranch") != "main"
        or profile.get("authority") != "canonical-native-and-sandboxed-godot-worker"
        or profile.get("requiredVisibility") != "public"
    ):
        fail("evavo.reliability.json identity changed")

    package_manager = profile.get("packageManager", {})
    if (
        package_manager.get("name") != "pip"
        or package_manager.get("lockfilePath") != "requirements.lock"
        or package_manager.get("lockfilePolicy") != "review-first"
        or package_manager.get("lockfilePresent") is not False
        or package_manager.get("install")
        != "python -m pip install --disable-pip-version-check .[dev]"
        or package_manager.get("buildBackend") != "hatchling==1.25.0"
        or package_manager.get("directDevelopmentDependencies")
        != ["pytest==8.3.0", "ruff==0.9.0"]
        or package_manager.get("agentInstall")
        != 'python -m pip install --disable-pip-version-check ".[agent]"'
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
        or runtime.get("managedGodotPlatforms")
        != [
            "windows-x86_64",
            "windows-arm64",
            "linux-x86_64",
            "linux-arm64",
        ]
        or runtime.get("linuxSandboxDotnet") != "8.0"
        or runtime.get("linuxSandboxBase") != LINUX_SANDBOX_BASE
    ):
        fail("repository-owned runtime authority changed")
    local_sandbox = runtime.get("localDockerSandbox", {})
    if (
        local_sandbox.get("containerEngine")
        != "Docker Desktop or Docker Engine with Linux containers"
        or local_sandbox.get("runNetwork") != "none"
        or local_sandbox.get("targetSourceMount") != "read-only"
        or local_sandbox.get("rootFilesystem") != "read-only"
        or local_sandbox.get("sandboxUser") != "10001:10001"
    ):
        fail("local Docker sandbox runtime authority changed")

    provider = profile.get("providerConfirmation", {})
    if (
        provider.get("workflow") != ".github/workflows/evavo-mainline-confirmation.yml"
        or provider.get("selfValidationWorkflow") != ".github/workflows/ci.yml"
        or provider.get("githubRunner") != "ubuntu-24.04"
        or provider.get("exactMainShaRequired") is not True
        or provider.get("exactHostedPythonRequired") is not True
        or provider.get("sourceConfirmationOnly") is not True
        or provider.get("nativeWindowsEvidenceSeparate") is not True
        or provider.get("linuxSandboxEvidenceSeparate") is not True
    ):
        fail("provider confirmation authority changed")

    branch_policy = profile.get("branchPolicy", {})
    if (
        branch_policy.get("mode") != "direct-main"
        or branch_policy.get("exclusiveLeaseRequired") is not True
        or branch_policy.get("forcePushAllowed") is not False
    ):
        fail("branch and force-push authority changed")

    if "repository toolchain source check" not in profile.get("nativeAcceptance", {}).get(
        "requiredStages", []
    ):
        fail("native acceptance is missing repository toolchain source validation")
    if "repository toolchain source check" not in profile.get("linuxSandboxAcceptance", {}).get(
        "requiredBaseStages", []
    ):
        fail("Linux sandbox acceptance is missing repository toolchain source validation")
    selection = profile.get("toolSelection", {})
    if (
        selection.get("managedEngineProvisioning")
        != "official-godot-builds-sha512-self-contained"
        or selection.get("localLinuxSandbox")
        != "godot-lab-sandbox-checksum-verified-no-network-runtime"
    ):
        fail("managed engine or local sandbox tool selection changed")

    blocked_effects = profile.get("autoRepair", {}).get("blockedEffects", [])
    for effect in [
        "target-repository-write-without-grant",
        "release-publication",
        "store-deployment",
        "credential-change",
        "physical-controller-pass-claim-from-synthetic-input",
        "human-ux-approval-claim-from-geometry-telemetry",
    ]:
        if effect not in blocked_effects:
            fail(f"auto-repair boundary is missing: {effect}")

    schema = canonical_json("schemas/repository-owned-reliability-profile.schema.json")
    if (
        schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema"
        or schema.get("properties", {}).get("schemaVersion", {}).get("const") != "1.2"
        or schema.get("properties", {}).get("repository", {}).get("const")
        != "EVAVO-STUDIO/godot-game-test-lab"
    ):
        fail("repository-owned reliability schema identity changed")
    if (
        schema.get("properties", {})
        .get("toolVersion", {})
        .get("const")
        != "0.7.0"
    ):
        fail("repository-owned reliability tool version changed")

    require_tokens(
        "src/godot_game_test_lab/engine_manager.py",
        (
            "SHA512-SUMS.txt",
            "godot-engine-lock.json",
            "._sc_",
            "engine-installation.json",
            "prepare_estate",
            "mirror_release_assets",
            "payload_sha256",
        ),
    )
    require_tokens(
        "scripts/Install-GodotLab.ps1",
        (
            '"engine", "bootstrap"',
            "standard,mono",
            "Write-GodotLabMcpConfig.ps1",
            "managed-engine-bootstrap.json",
            "PrepareLinuxSandboxImages",
            "sandbox image",
        ),
    )
    require_tokens(
        "scripts/install-godot-lab.sh",
        (
            "engine bootstrap",
            "standard,mono",
            "managed-engine-bootstrap.json",
            "godot-lab-mcp.json",
            "PREPARE_SANDBOX_IMAGES",
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
            "local-sandbox-summary.json",
            "targetUnchanged",
        ),
    )
    require_tokens(
        "scripts/run-godot-lab-linux-sandbox.sh",
        ("godot_game_test_lab.local_sandbox",),
    )
    require_tokens(
        "scripts/Invoke-GodotLabLinuxSandbox.ps1",
        ("godot_game_test_lab.local_sandbox", "AllowedArtifactRoot"),
    )

    dockerfile = require_tokens(
        "containers/linux-sandbox/Dockerfile",
        (
            f"FROM {LINUX_SANDBOX_BASE}",
            "ARG GODOT_VERSION=4.6.3",
            "dotnet-sdk-8.0",
            "SHA512-SUMS.txt",
            "curl --proto '=https'",
            "checksum manifest must contain exactly one",
            "def safe_extract",
            "SHA-512 mismatch",
            "USER 10001:10001",
        ),
    )
    if "latest" in dockerfile.splitlines()[0]:
        fail("Linux sandbox base image must not use latest")

    ci = require_tokens(
        ".github/workflows/ci.yml",
        (
            "permissions:\n  contents: read",
            f"actions/checkout@{CHECKOUT_V6_SHA} # v6.0.2",
            "persist-credentials: false",
            f"actions/setup-python@{SETUP_PYTHON_SHA} # v6.2.0",
            f'python-version: "{HOSTED_PYTHON}"',
            "python scripts/check_repository_toolchain.py",
            "python scripts/test_repository_toolchain.py",
            'python -m pip install --disable-pip-version-check ".[dev]"',
            "python scripts/check_repository_toolchain.py --installed",
            'python -m pip install --disable-pip-version-check ".[agent]"',
            "python scripts/check_repository_toolchain.py --agent-installed",
            "python -m godot_game_test_lab.mcp_server",
            "python -m compileall -q src scripts tests",
            "python -m ruff check src scripts tests",
            "python -m pytest",
            "python -m pip wheel --no-deps --wheel-dir dist .",
            "rm -rf dist",
            "git diff --exit-code",
            'test -z "$(git status --porcelain=v1 --untracked-files=all)"',
        ),
    )
    if "cache-dependency-path" in ci or "cache: pip" in ci:
        fail("CI must not cache against an absent review-first lockfile")

    mainline = require_tokens(
        ".github/workflows/evavo-mainline-confirmation.yml",
        (
            "workflow_dispatch:",
            "permissions:\n  contents: read",
            f"actions/checkout@{CHECKOUT_V4_SHA} # v4.3.0",
            "persist-credentials: false",
            f"actions/setup-python@{SETUP_PYTHON_SHA} # v6.2.0",
            f'python-version: "{HOSTED_PYTHON}"',
            "python scripts/check_repository_toolchain.py",
            "python scripts/test_repository_toolchain.py",
            'python -m pip install --disable-pip-version-check ".[dev]"',
            "python scripts/check_repository_toolchain.py --installed",
            'python -m pip install --disable-pip-version-check ".[agent]"',
            "python scripts/check_repository_toolchain.py --agent-installed",
            "python -m godot_game_test_lab.mcp_server",
            "python -m pytest",
            "python -m pip wheel --no-deps --wheel-dir dist .",
            'test -z "$(git status --porcelain=v1 --untracked-files=all)"',
        ),
    )
    if re.search(r'^\s*python-version:\s*"3\.11"\s*$', mainline, re.MULTILINE):
        fail("mainline confirmation still uses a floating Python minor")

    native = require_tokens(
        ".github/workflows/evavo-native-godot-validation.yml",
        (
            "workflow_dispatch:",
            "permissions:\n  contents: read",
            f"actions/checkout@{CHECKOUT_V4_SHA} # v4.3.0",
            "persist-credentials: false",
            "py -3.11 scripts/check_repository_toolchain.py --native-family",
            "py -3.11 -m venv",
            "scripts/check_repository_toolchain.py --native-family --installed",
            "4.6.2",
            f"actions/upload-artifact@{UPLOAD_ARTIFACT_SHA} # v4.6.2",
        ),
    )
    if "force:" in native or "git reset --hard" in native:
        fail("native workflow must not reset or replace target source")

    reusable = require_tokens(
        ".github/workflows/reusable-godot-linux-sandbox.yml",
        (
            "workflow_call:",
            "permissions:\n  contents: read",
            f"actions/checkout@{CHECKOUT_V4_SHA} # v4.3.0",
            "persist-credentials: false",
            "working-directory: lab-source",
            "python3 scripts/check_repository_toolchain.py --skip-runtime",
            "--network none",
            "--read-only",
            "--cap-drop ALL",
            "--security-opt no-new-privileges",
            f"actions/upload-artifact@{UPLOAD_ARTIFACT_SHA} # v4.6.2",
        ),
    )
    if "docker.sock" in reusable:
        fail("reusable target-execution workflow must not mount the Docker socket")

    administrative = require_tokens(
        ".github/workflows/evavo-linux-godot-sandbox.yml",
        (
            "permissions:\n  contents: read",
            f"actions/checkout@{CHECKOUT_V4_SHA} # v4.3.0",
            "persist-credentials: false",
            "--network none",
            "--read-only",
            "--cap-drop ALL",
            "--security-opt no-new-privileges",
            f"actions/upload-artifact@{UPLOAD_ARTIFACT_SHA} # v4.6.2",
        ),
    )
    if "docker.sock" in administrative:
        fail("administrative target-execution workflow must not mount the Docker socket")

    require_tokens(
        ".github/workflows/linux-sandbox-smoke.yml",
        (
            "permissions:\n  contents: read",
            "uses: ./.github/workflows/reusable-godot-linux-sandbox.yml",
            "fixtures/linux-smoke/.evavo/godot-lab-linux.json",
        ),
    )

    for workflow in WORKFLOWS:
        action_references_are_immutable(workflow, allow_local=True)
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

    if args.installed:
        validate_installed_state()
    if args.agent_installed:
        validate_agent_installed_state()

    validate_runtime(args.native_family, args.skip_runtime)

    if ERRORS:
        print("Godot lab repository toolchain check failed:\n", file=sys.stderr)
        for error in ERRORS:
            print(f"- {error}", file=sys.stderr)
        return 1

    print("Godot lab repository toolchain check passed.")
    if args.native_family:
        print("- native Python 3.11 family capability is present")
    elif args.skip_runtime:
        print("- source authority validated without a runtime claim")
    else:
        print(f"- hosted Python {HOSTED_PYTHON} is exact")
    print("- Godot, .NET, container, workflow and effect boundaries agree")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
