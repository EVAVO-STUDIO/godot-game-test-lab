#!/usr/bin/env python3
"""Fail-closed source and runtime validation for the Godot Game Test Lab."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tomllib
from typing import Any

HOSTED_PYTHON = "3.11.15"
NATIVE_PYTHON_FAMILY = (3, 11)
CHECKOUT_V4_SHA = "08eba0b27e820071cde6df949e0beb9ba4906955"
CHECKOUT_V6_SHA = "de0fac2e4500dabe0009e67214ff5f5447ce83dd"
SETUP_PYTHON_SHA = "a309ff8b426b58ec0e2a45f0f869d46889d02405"
UPLOAD_ARTIFACT_SHA = "ea165f8d65b6e75b540449e92b4886f43607fa02"
ROOT = Path.cwd().resolve(strict=True)
ERRORS: list[str] = []


def fail(message: str) -> None:
    ERRORS.append(message)


def source_path(relative: str) -> Path:
    candidate = (ROOT / relative).resolve(strict=False)
    try:
        candidate.relative_to(ROOT)
    except ValueError as error:
        raise RuntimeError(f"GODOT_LAB_TOOLCHAIN_PATH_ESCAPE:{relative}") from error
    return candidate


def read_text(relative: str, maximum_bytes: int = 4_000_000) -> str:
    candidate = source_path(relative)
    if not candidate.exists():
        raise RuntimeError(f"Missing Godot lab toolchain file: {relative}")
    stat = candidate.lstat()
    if not candidate.is_file() or candidate.is_symlink():
        raise RuntimeError(f"Godot lab toolchain path must be a regular file: {relative}")
    if stat.st_size > maximum_bytes:
        raise RuntimeError(f"Godot lab toolchain file is too large: {relative}")
    try:
        return candidate.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise RuntimeError(f"Godot lab toolchain file is not valid UTF-8: {relative}") from error


def canonical_json(relative: str) -> dict[str, Any]:
    source = read_text(relative, 16_000_000)
    if source.startswith("\ufeff"):
        raise RuntimeError(f"Godot lab JSON contains a BOM: {relative}")
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


def require_tokens(relative: str, tokens: list[str]) -> str:
    source = read_text(relative)
    for token in tokens:
        if token not in source:
            fail(f"{relative} is missing required token: {token}")
    return source


def forbid_tokens(relative: str, tokens: list[str]) -> None:
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


def main() -> int:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--skip-runtime", action="store_true")
    parser.add_argument("--native-family", action="store_true")
    parser.add_argument("--installed", action="store_true")
    args = parser.parse_args()

    if read_text(".python-version", 64) != f"{HOSTED_PYTHON}\n":
        fail(f".python-version must contain exactly {HOSTED_PYTHON}")

    pyproject_source = read_text("pyproject.toml", 128_000)
    pyproject = tomllib.loads(pyproject_source)
    if pyproject.get("build-system", {}).get("requires") != ["hatchling==1.25.0"]:
        fail("pyproject.toml must pin hatchling==1.25.0")
    project = pyproject.get("project", {})
    if project.get("name") != "godot-game-test-lab" or project.get("version") != "0.4.0":
        fail("pyproject.toml project identity changed")
    if project.get("requires-python") != ">=3.11":
        fail("pyproject.toml Python compatibility declaration changed")
    if project.get("dependencies") != []:
        fail("runtime dependencies must remain empty")
    if project.get("optional-dependencies", {}).get("dev") != [
        "pytest==8.3.0",
        "ruff==0.9.0",
    ]:
        fail("development dependency pins changed")

    lock_path = source_path("requirements.lock")
    if lock_path.exists():
        fail("requirements.lock appeared before the review-first transition was approved")

    profile = canonical_json("evavo.reliability.json")
    if (
        profile.get("schemaVersion") != "1.2"
        or profile.get("repository") != "EVAVO-STUDIO/godot-game-test-lab"
        or profile.get("defaultBranch") != "main"
        or profile.get("authority") != "canonical-native-and-sandboxed-godot-worker"
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
    ):
        fail("repository-owned Python dependency authority changed")
    runtime = profile.get("runtime", {})
    if (
        runtime.get("hostedPython") != HOSTED_PYTHON
        or runtime.get("nativePythonFamily") != "3.11.x"
        or runtime.get("minimumGodot") != "4.6.2"
        or runtime.get("linuxSandboxDotnet") != "8.0"
        or runtime.get("linuxSandboxBase")
        != "ubuntu:noble-20260610@sha256:4fbb8e6a8395de5a7550b33509421a2bafbc0aab6c06ba2cef9ebffbc7092d90"
    ):
        fail("repository-owned runtime authority changed")
    if profile.get("branchPolicy", {}).get("forcePushAllowed") is not False:
        fail("force-push prohibition changed")
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

    dockerfile = require_tokens(
        "containers/linux-sandbox/Dockerfile",
        [
            "FROM ubuntu:noble-20260610@sha256:4fbb8e6a8395de5a7550b33509421a2bafbc0aab6c06ba2cef9ebffbc7092d90",
            "ARG GODOT_VERSION=4.6.2",
            "dotnet-sdk-8.0",
            "SHA512-SUMS.txt",
            "sha512sum --check selected-SHA512-SUMS.txt",
            "USER 10001:10001",
        ],
    )
    if "latest" in dockerfile.splitlines()[0]:
        fail("Linux sandbox base image must not use latest")

    ci = require_tokens(
        ".github/workflows/ci.yml",
        [
            "permissions:\n  contents: read",
            f"actions/checkout@{CHECKOUT_V6_SHA} # v6.0.2",
            "persist-credentials: false",
            f"actions/setup-python@{SETUP_PYTHON_SHA} # v6.2.0",
            f'python-version: "{HOSTED_PYTHON}"',
            "python scripts/check_repository_toolchain.py",
            "python scripts/test_repository_toolchain.py",
            'python -m pip install --disable-pip-version-check ".[dev]"',
            "python scripts/check_repository_toolchain.py --installed",
            "python -m compileall -q src scripts tests",
            "python -m ruff check src scripts tests",
            "python -m pytest",
            "python -m pip wheel --no-deps --wheel-dir dist .",
            "rm -rf dist",
            "git diff --exit-code",
            'test -z "$(git status --porcelain)"',
        ],
    )
    if "requirements.lock" in ci and "cache-dependency-path" in ci:
        fail("CI must not cache against an absent review-first lockfile")

    mainline = require_tokens(
        ".github/workflows/evavo-mainline-confirmation.yml",
        [
            "workflow_dispatch:",
            "permissions:\n  contents: read",
            f"actions/checkout@{CHECKOUT_V4_SHA} # v4.3.0",
            "persist-credentials: false",
            f"actions/setup-python@{SETUP_PYTHON_SHA} # v6.2.0",
            f'python-version: "{HOSTED_PYTHON}"',
            "python scripts/check_repository_toolchain.py",
            "python scripts/test_repository_toolchain.py",
            'python -m pip install --disable-pip-version-check ".[dev]"',
        ],
    )
    if re.search(r'^\s*python-version:\s*"3\.11"\s*$', mainline, re.MULTILINE):
        fail("mainline confirmation still uses a floating Python minor")

    require_tokens(
        ".github/workflows/evavo-native-godot-validation.yml",
        [
            "workflow_dispatch:",
            "permissions:\n  contents: read",
            f"actions/checkout@{CHECKOUT_V4_SHA} # v4.3.0",
            "persist-credentials: false",
            "py -3.11 -m venv",
            "scripts/check_repository_toolchain.py --native-family",
            "4.6.2",
            f"actions/upload-artifact@{UPLOAD_ARTIFACT_SHA} # v4.6.2",
        ],
    )
    reusable = require_tokens(
        ".github/workflows/reusable-godot-linux-sandbox.yml",
        [
            "workflow_call:",
            "permissions:\n  contents: read",
            f"actions/checkout@{CHECKOUT_V4_SHA} # v4.3.0",
            "persist-credentials: false",
            "python3 lab-source/scripts/check_repository_toolchain.py --skip-runtime",
            "--network none",
            "--read-only",
            "--cap-drop ALL",
            "--security-opt no-new-privileges",
            f"actions/upload-artifact@{UPLOAD_ARTIFACT_SHA} # v4.6.2",
        ],
    )
    if "docker.sock" in reusable:
        fail("reusable target-execution workflow must not mount the Docker socket")

    for workflow in [
        ".github/workflows/ci.yml",
        ".github/workflows/evavo-mainline-confirmation.yml",
        ".github/workflows/evavo-native-godot-validation.yml",
        ".github/workflows/reusable-godot-linux-sandbox.yml",
        ".github/workflows/linux-sandbox-smoke.yml",
    ]:
        action_references_are_immutable(workflow, allow_local=True)
        forbid_tokens(
            workflow,
            [
                "persist-credentials: true",
                "permissions: write-all",
                "contents: write",
                "pull-requests: write",
                "packages: write",
                "git push",
                "gh pr create",
            ],
        )

    if args.installed:
        try:
            import pytest  # noqa: F401
            import ruff  # type: ignore[import-not-found]  # noqa: F401
        except ImportError:
            fail("installed-state validation requires pinned pytest and Ruff packages")

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
