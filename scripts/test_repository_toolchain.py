#!/usr/bin/env python3
"""Adversarial fixtures for the Godot lab repository toolchain contract."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Callable

SOURCE_ROOT = Path.cwd().resolve(strict=True)
FILES = [
    ".github/workflows/ci.yml",
    ".github/workflows/evavo-mainline-confirmation.yml",
    ".github/workflows/evavo-native-godot-validation.yml",
    ".github/workflows/reusable-godot-linux-sandbox.yml",
    ".github/workflows/linux-sandbox-smoke.yml",
    ".python-version",
    "containers/linux-sandbox/Dockerfile",
    "evavo.reliability.json",
    "pyproject.toml",
    "schemas/repository-owned-reliability-profile.schema.json",
    "scripts/check_repository_toolchain.py",
]


def copy_fixture(root: Path) -> None:
    for relative in FILES:
        source = SOURCE_ROOT / relative
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def run(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "scripts/check_repository_toolchain.py",
            "--skip-runtime",
            *arguments,
        ],
        cwd=root,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )


def mutate_json(root: Path, relative: str, operation: Callable[[dict[str, Any]], None]) -> None:
    path = root / relative
    value = json.loads(path.read_text(encoding="utf-8"))
    operation(value)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def mutate_text(root: Path, relative: str, operation: Callable[[str], str]) -> None:
    path = root / relative
    path.write_text(operation(path.read_text(encoding="utf-8")), encoding="utf-8")


def exercise(operation: Callable[[Path], None], label: str) -> None:
    with tempfile.TemporaryDirectory(prefix="evavo-godot-toolchain-") as temporary:
        root = Path(temporary) / "fixture"
        root.mkdir(parents=True)
        copy_fixture(root)
        operation(root)
        result = run(root)
        if result.returncode == 0:
            raise AssertionError(f"{label} must fail closed")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="evavo-godot-toolchain-") as temporary:
        root = Path(temporary) / "fixture"
        root.mkdir(parents=True)
        copy_fixture(root)
        exact = run(root)
        if exact.returncode != 0:
            raise AssertionError(exact.stderr or exact.stdout)

    exercise(
        lambda root: (root / ".python-version").write_text("3.11.14\n", encoding="utf-8"),
        "hosted Python drift",
    )
    exercise(
        lambda root: mutate_json(
            root,
            "evavo.reliability.json",
            lambda value: value["packageManager"].update(
                {"lockfilePolicy": "committed-frozen", "lockfilePresent": True}
            ),
        ),
        "unreviewed lockfile transition",
    )
    exercise(
        lambda root: (root / "requirements.lock").write_text("pytest==8.3.0\n", encoding="utf-8"),
        "unreviewed lockfile appearance",
    )
    exercise(
        lambda root: mutate_text(
            root,
            ".github/workflows/ci.yml",
            lambda value: value.replace(
                "actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd",
                "actions/checkout@v6",
            ),
        ),
        "mutable checkout action",
    )
    exercise(
        lambda root: mutate_text(
            root,
            ".github/workflows/ci.yml",
            lambda value: value.replace('python-version: "3.11.15"', 'python-version: "3.11"'),
        ),
        "floating hosted Python",
    )
    exercise(
        lambda root: mutate_text(
            root,
            ".github/workflows/reusable-godot-linux-sandbox.yml",
            lambda value: value.replace("--network none", "--network bridge"),
        ),
        "sandbox network enablement",
    )
    exercise(
        lambda root: mutate_text(
            root,
            "containers/linux-sandbox/Dockerfile",
            lambda value: value.replace(
                "ubuntu:noble-20260610@sha256:4fbb8e6a8395de5a7550b33509421a2bafbc0aab6c06ba2cef9ebffbc7092d90",
                "ubuntu:latest",
            ),
        ),
        "mutable sandbox base image",
    )
    exercise(
        lambda root: mutate_json(
            root,
            "evavo.reliability.json",
            lambda value: value["autoRepair"]["blockedEffects"].remove(
                "physical-controller-pass-claim-from-synthetic-input"
            ),
        ),
        "physical-controller truth-boundary removal",
    )

    print("Godot lab repository toolchain adversarial tests passed.")
    print("- Python, lockfile, workflow, sandbox and truth-boundary drift fail closed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
