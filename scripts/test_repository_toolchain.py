#!/usr/bin/env python3
"""Adversarial fixtures for the Godot Lab release and policy contract."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

SOURCE_ROOT = Path.cwd().resolve(strict=True)
CORE_FILES = (
    ".github/workflows/capability-manifest.yml",
    ".github/workflows/ci.yml",
    ".github/workflows/evavo-mainline-confirmation.yml",
    ".github/workflows/evavo-native-godot-validation.yml",
    ".github/workflows/reusable-godot-linux-sandbox.yml",
    ".github/workflows/evavo-linux-godot-sandbox.yml",
    ".github/workflows/linux-sandbox-smoke.yml",
    ".github/workflows/verified-toolchain-transport.yml",
    ".python-version",
    "containers/linux-sandbox/Dockerfile",
    "docs/LOCALIZATION_PLURAL_RUNTIME_VALIDATION.md",
    "evavo.reliability.json",
    "pyproject.toml",
    "schemas/evavo-godot-plural-localization-test-lab-report.v1.schema.json",
    "schemas/localization-godot-plural-testlab-request.v1.schema.json",
    "schemas/repository-owned-reliability-profile.schema.json",
    "scripts/Invoke-GodotPluralLocalizationValidation.ps1",
    "scripts/check_repository_toolchain_core.py",
    "src/godot_game_test_lab/__init__.py",
    "src/godot_game_test_lab/engine_manager.py",
    "src/godot_game_test_lab/godot-engine-lock.json",
    "src/godot_game_test_lab/local_sandbox.py",
    "src/godot_game_test_lab/localization_plural.py",
    "src/godot_game_test_lab/localization_plural_runtime.py",
    "src/godot_game_test_lab/localization_plural_runtime_cli.py",
    "src/godot_game_test_lab/localization_plural_safe.py",
)


def copy_fixture(root: Path) -> None:
    for relative in CORE_FILES:
        source = SOURCE_ROOT / relative
        if not source.is_file() or source.is_symlink():
            raise AssertionError(f"fixture source is missing or unsafe: {relative}")
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def run(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-S",
            "scripts/check_repository_toolchain_core.py",
            "--skip-runtime",
        ],
        cwd=root,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )


def mutate_json(
    root: Path,
    relative: str,
    operation: Callable[[dict[str, Any]], None],
) -> None:
    path = root / relative
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"fixture JSON is not an object: {relative}")
    operation(value)
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def mutate_text(
    root: Path,
    relative: str,
    operation: Callable[[str], str],
) -> None:
    path = root / relative
    source = path.read_text(encoding="utf-8")
    changed = operation(source)
    if changed == source:
        raise AssertionError(f"fixture mutation did not change {relative}")
    path.write_text(changed, encoding="utf-8")


def exercise(operation: Callable[[Path], None], label: str) -> None:
    with tempfile.TemporaryDirectory(
        prefix="evavo-godot-toolchain-",
    ) as temporary:
        root = Path(temporary) / "fixture"
        root.mkdir(parents=True)
        copy_fixture(root)
        operation(root)
        result = run(root)
        if result.returncode == 0:
            raise AssertionError(f"{label} must fail closed")


def remove_list_item(value: dict[str, Any], path: tuple[str, ...], item: str) -> None:
    selected: Any = value
    for key in path:
        selected = selected[key]
    selected.remove(item)


def main() -> int:
    with tempfile.TemporaryDirectory(
        prefix="evavo-godot-toolchain-",
    ) as temporary:
        root = Path(temporary) / "fixture"
        root.mkdir(parents=True)
        copy_fixture(root)
        exact = run(root)
        if exact.returncode != 0:
            raise AssertionError(exact.stderr or exact.stdout)

    exercise(
        lambda root: mutate_text(
            root,
            "src/godot_game_test_lab/__init__.py",
            lambda value: value.replace(
                '__version__ = "0.8.0"',
                '__version__ = "0.8.1"',
            ),
        ),
        "package runtime version drift",
    )
    exercise(
        lambda root: mutate_text(
            root,
            "pyproject.toml",
            lambda value: value.replace(
                'version = "0.8.0"',
                'version = "0.8.1"',
            ),
        ),
        "package metadata version drift",
    )
    exercise(
        lambda root: mutate_text(
            root,
            "pyproject.toml",
            lambda value: value.replace(
                "godot_game_test_lab.localization_plural_runtime_cli:main",
                "godot_game_test_lab.localization_plural_cli:main",
            ),
        ),
        "unguarded plural localization console route",
    )
    exercise(
        lambda root: mutate_text(
            root,
            "pyproject.toml",
            lambda value: value.replace("mcp==1.28.1", "mcp>=1.28"),
        ),
        "floating MCP dependency",
    )
    exercise(
        lambda root: mutate_json(
            root,
            "evavo.reliability.json",
            lambda value: value.update({"toolVersion": "0.7.1"}),
        ),
        "reliability version drift",
    )
    exercise(
        lambda root: mutate_json(
            root,
            "evavo.reliability.json",
            lambda value: value["toolSelection"].pop(
                "pluralLocalizationValidation",
            ),
        ),
        "plural localization tool selection removal",
    )
    exercise(
        lambda root: mutate_json(
            root,
            "evavo.reliability.json",
            lambda value: remove_list_item(
                value,
                ("nativeAcceptance", "requiredStages"),
                (
                    "exact-head plural-localization CSV import and "
                    "reviewed runtime lookup probes"
                ),
            ),
        ),
        "plural localization native stage removal",
    )
    exercise(
        lambda root: mutate_json(
            root,
            "evavo.reliability.json",
            lambda value: remove_list_item(
                value,
                ("autoRepair", "blockedEffects"),
                (
                    "plural-localization-release-claim-without-"
                    "exact-head-runtime-evidence"
                ),
            ),
        ),
        "plural localization publication boundary removal",
    )
    exercise(
        lambda root: mutate_json(
            root,
            "schemas/repository-owned-reliability-profile.schema.json",
            lambda value: value["properties"]["toolVersion"].update(
                {"const": "0.7.1"}
            ),
        ),
        "reliability schema version drift",
    )
    exercise(
        lambda root: mutate_text(
            root,
            "src/godot_game_test_lab/localization_plural_runtime.py",
            lambda value: value.replace(
                "run_plural_localization_validation_safe",
                "run_plural_localization_validation_unguarded",
            ),
        ),
        "guarded runtime facade removal",
    )
    exercise(
        lambda root: mutate_text(
            root,
            "src/godot_game_test_lab/localization_plural_safe.py",
            lambda value: value.replace(
                '"publicationAuthority": False',
                '"publicationAuthority": True',
            ),
        ),
        "plural localization publication escalation",
    )
    exercise(
        lambda root: mutate_text(
            root,
            "src/godot_game_test_lab/localization_plural_safe.py",
            lambda value: value.replace(
                "Plural localization CSV bytes changed during validation.",
                "Plural localization CSV was not rechecked.",
            ),
        ),
        "final CSV identity recheck removal",
    )
    exercise(
        lambda root: mutate_text(
            root,
            "docs/LOCALIZATION_PLURAL_RUNTIME_VALIDATION.md",
            lambda value: value.replace(
                "python -m godot_game_test_lab.localization_plural_runtime_cli",
                "python -m godot_game_test_lab.localization_plural_cli",
            ),
        ),
        "canonical guarded invocation drift",
    )
    exercise(
        lambda root: mutate_json(
            root,
            "schemas/localization-godot-plural-testlab-request.v1.schema.json",
            lambda value: value["properties"]["authority"]["properties"][
                "requestWritesTarget"
            ].update({"const": True}),
        ),
        "request target-write authority escalation",
    )
    exercise(
        lambda root: mutate_json(
            root,
            (
                "schemas/"
                "evavo-godot-plural-localization-test-lab-report.v1.schema.json"
            ),
            lambda value: value["properties"]["authority"]["properties"][
                "publicationAuthority"
            ].update({"const": True}),
        ),
        "report publication authority escalation",
    )
    exercise(
        lambda root: mutate_json(
            root,
            "src/godot_game_test_lab/godot-engine-lock.json",
            lambda value: value.update({"defaultVersion": "4.8.0"}),
        ),
        "managed Godot default drift",
    )
    exercise(
        lambda root: (root / ".python-version").write_text(
            "3.11.14\n",
            encoding="utf-8",
        ),
        "hosted Python drift",
    )
    exercise(
        lambda root: mutate_text(
            root,
            ".github/workflows/ci.yml",
            lambda value: value.replace(
                (
                    "actions/checkout@"
                    "de0fac2e4500dabe0009e67214ff5f5447ce83dd"
                ),
                "actions/checkout@v6",
            ),
        ),
        "mutable checkout action",
    )
    exercise(
        lambda root: mutate_text(
            root,
            ".github/workflows/evavo-linux-godot-sandbox.yml",
            lambda value: value.replace(
                "permissions:\n  contents: read",
                "permissions:\n  contents: write",
            ),
        ),
        "workflow write authority",
    )
    exercise(
        lambda root: mutate_text(
            root,
            "src/godot_game_test_lab/local_sandbox.py",
            lambda value: value.replace(
                '        "none",\n',
                '        "bridge",\n',
                1,
            ),
        ),
        "local sandbox network enablement",
    )
    exercise(
        lambda root: (root / "requirements.lock").write_text(
            "pytest==8.3.0\n",
            encoding="utf-8",
        ),
        "unreviewed lockfile appearance",
    )

    print("Godot lab repository toolchain adversarial tests passed.")
    print(
        "- version, guarded plural runtime, request/report authority, "
        "workflow, engine, sandbox and publication drift fail closed"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
