#!/usr/bin/env python3
"""Adversarial fixtures for the Godot lab repository toolchain contract."""

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
FILES = [
    ".github/workflows/ci.yml",
    ".github/workflows/evavo-mainline-confirmation.yml",
    ".github/workflows/evavo-native-godot-validation.yml",
    ".github/workflows/reusable-godot-linux-sandbox.yml",
    ".github/workflows/evavo-linux-godot-sandbox.yml",
    ".github/workflows/linux-sandbox-smoke.yml",
    ".python-version",
    "containers/linux-sandbox/Dockerfile",
    "docs/ART_STUDIO_ASSET_AUDIT.md",
    "docs/MEDIA_PRODUCTION_PLAN_GATE.md",
    "docs/FOUNDATION_KIT_MEDIA_PLAN_GATE.md",
    "docs/FOUNDATION_KIT_MEDIA_RELEASE_REPORT.md",
    "docs/BRASS_BRINE_AUDIO_ANALYSIS.md",
    "docs/CLASSIC_ADVENTURE_VGA_QA.md",
    "evavo.reliability.json",
    "pyproject.toml",
    "schemas/repository-owned-reliability-profile.schema.json",
    "scripts/check_asset_audit_toolchain.py",
    "scripts/check_foundation_media_toolchain.py",
    "scripts/check_audio_analysis_toolchain.py",
    "scripts/check_classic_adventure_vga_toolchain.py",
    "scripts/check_repository_toolchain.py",
    "scripts/check_repository_toolchain_core.py",
    "scripts/classic_adventure_vga_qa.py",
    "src/godot_game_test_lab/__init__.py",
    "src/godot_game_test_lab/asset_audit.py",
    "src/godot_game_test_lab/asset_audit_checks.py",
    "src/godot_game_test_lab/asset_audit_contract.py",
    "src/godot_game_test_lab/asset_audit_contract_groups.py",
    "src/godot_game_test_lab/asset_audit_contract_scalar.py",
    "src/godot_game_test_lab/asset_audit_io.py",
    "src/godot_game_test_lab/asset_audit_mcp.py",
    "src/godot_game_test_lab/asset_audit_mcp_policy.py",
    "src/godot_game_test_lab/asset_audit_model.py",
    "src/godot_game_test_lab/asset_audit_png.py",
    "src/godot_game_test_lab/asset_audit_validation.py",
    "src/godot_game_test_lab/audio_analysis.py",
    "src/godot_game_test_lab/audio_analysis_contract.py",
    "src/godot_game_test_lab/audio_analysis_io.py",
    "src/godot_game_test_lab/audio_analysis_mcp.py",
    "src/godot_game_test_lab/audio_analysis_media.py",
    "src/godot_game_test_lab/audio_analysis_types.py",
    "src/godot_game_test_lab/classic_adventure_vga.py",
    "src/godot_game_test_lab/classic_adventure_vga_contract.py",
    "src/godot_game_test_lab/classic_adventure_vga_png.py",
    "src/godot_game_test_lab/foundation_media_mcp.py",
    "src/godot_game_test_lab/foundation_media_plan.py",
    "src/godot_game_test_lab/foundation_media_release_report.py",
    "src/godot_game_test_lab/foundation_media_source_authority.py",
    "src/godot_game_test_lab/media_production_plan.py",
    "src/godot_game_test_lab/strict_json.py",
    "src/godot_game_test_lab/godot-engine-lock.json",
    "src/godot_game_test_lab/engine_manager.py",
    "scripts/Install-GodotLab.ps1",
    "scripts/Invoke-GodotLabLinuxSandbox.ps1",
    "scripts/install-godot-lab.sh",
    "scripts/run-godot-lab-linux-sandbox.sh",
    "src/godot_game_test_lab/local_sandbox.py",
    "tests/asset_audit_fixtures.py",
    "tests/test_asset_audit.py",
    "tests/test_asset_audit_authority.py",
    "tests/test_asset_audit_mcp.py",
    "tests/test_asset_audit_png.py",
    "tests/test_asset_audit_release_contract.py",
    "tests/test_audio_analysis.py",
    "tests/test_classic_adventure_vga.py",
    "tests/test_audio_analysis_mcp.py",
    "tests/test_foundation_media_mcp.py",
    "tests/test_foundation_media_plan.py",
    "tests/test_foundation_media_release_report.py",
    "tests/test_media_production_plan.py",
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
            "-S",
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


def mutate_json(
    root: Path,
    relative: str,
    operation: Callable[[dict[str, Any]], None],
) -> None:
    path = root / relative
    value = json.loads(path.read_text(encoding="utf-8"))
    operation(value)
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


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
        lambda root: mutate_text(
            root,
            "src/godot_game_test_lab/__init__.py",
            lambda value: value.replace(
                '__version__ = "0.7.0"',
                '__version__ = "0.7.1"',
            ),
        ),
        "package version drift",
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
        lambda root: (root / "requirements.lock").write_text(
            "pytest==8.3.0\n",
            encoding="utf-8",
        ),
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
            lambda value: value.replace(
                'python-version: "3.11.15"',
                'python-version: "3.11"',
            ),
        ),
        "floating hosted Python",
    )
    exercise(
        lambda root: mutate_text(
            root,
            ".github/workflows/evavo-mainline-confirmation.yml",
            lambda value: value.replace(
                "actions/setup-python@a309ff8b426b58ec0e2a45f0f869d46889d02405",
                "actions/setup-python@v6",
            ),
        ),
        "mutable setup-python action",
    )
    exercise(
        lambda root: mutate_text(
            root,
            ".github/workflows/evavo-native-godot-validation.yml",
            lambda value: value.replace(
                "py -3.11 scripts/check_repository_toolchain.py --native-family\n",
                "",
            ),
        ),
        "native source-check removal",
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
            ".github/workflows/evavo-linux-godot-sandbox.yml",
            lambda value: value.replace(
                "permissions:\n  contents: read",
                "permissions:\n  contents: write",
            ),
        ),
        "administrative write authority",
    )
    exercise(
        lambda root: mutate_text(
            root,
            "containers/linux-sandbox/Dockerfile",
            lambda value: value.replace(
                "ubuntu:noble-20260610@sha256:"
                "4fbb8e6a8395de5a7550b33509421a2bafbc0aab6c06ba2cef9ebffbc7092d90",
                "ubuntu:latest",
            ),
        ),
        "mutable sandbox base image",
    )
    exercise(
        lambda root: mutate_text(
            root,
            "containers/linux-sandbox/Dockerfile",
            lambda value: value.replace("def safe_extract", "def unsafe_extract"),
        ),
        "sandbox safe extraction removal",
    )
    exercise(
        lambda root: mutate_text(
            root,
            "src/godot_game_test_lab/local_sandbox.py",
            lambda value: value.replace('        "none",\n', '        "bridge",\n', 1),
        ),
        "local sandbox network enablement",
    )
    exercise(
        lambda root: mutate_text(
            root,
            "pyproject.toml",
            lambda value: value.replace(
                'godot-lab-sandbox = "godot_game_test_lab.local_sandbox:main"\n',
                "",
            ),
        ),
        "local sandbox entrypoint removal",
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
    exercise(
        lambda root: (root / "evavo.reliability.json").write_text(
            "\ufeff" + (root / "evavo.reliability.json").read_text(encoding="utf-8"),
            encoding="utf-8",
        ),
        "BOM-prefixed profile",
    )
    exercise(
        lambda root: mutate_text(
            root,
            "src/godot_game_test_lab/asset_audit_contract.py",
            lambda value: value.replace(
                "load_strict_json_object",
                "load_permissive_json_object",
            ),
        ),
        "asset-audit strict JSON removal",
    )
    exercise(
        lambda root: mutate_text(
            root,
            "src/godot_game_test_lab/asset_audit_validation.py",
            lambda value: value.replace(
                "asset-changed-after-admission",
                "asset-recheck-removed",
            ),
        ),
        "asset-audit final byte recheck removal",
    )
    exercise(
        lambda root: mutate_text(
            root,
            "src/godot_game_test_lab/asset_audit_png.py",
            lambda value: value.replace(
                "PNG chunk CRC mismatch",
                "PNG CRC unchecked",
            ),
        ),
        "asset-audit PNG CRC removal",
    )
    exercise(
        lambda root: mutate_text(
            root,
            "src/godot_game_test_lab/asset_audit_io.py",
            lambda value: value.replace(
                "Asset-audit output must remain strictly beneath EvidenceRoot",
                "Asset-audit output may escape EvidenceRoot",
            ),
        ),
        "asset-audit output confinement removal",
    )
    exercise(
        lambda root: (root / "src/godot_game_test_lab/asset_audit_mcp.py").write_text(
            (root / "src/godot_game_test_lab/asset_audit_mcp.py").read_text(
                encoding="utf-8"
            )
            + "\nfrom .agent_bridge import BridgeConfig\n",
            encoding="utf-8",
        ),
        "asset-audit private bridge import",
    )
    exercise(
        lambda root: mutate_text(
            root,
            "src/godot_game_test_lab/media_production_plan.py",
            lambda value: value.replace(
                "plan-audit-identity-mismatch",
                "plan-audit-recheck-removed",
            ),
        ),
        "media-plan audit identity removal",
    )
    exercise(
        lambda root: mutate_text(
            root,
            "src/godot_game_test_lab/foundation_media_source_authority.py",
            lambda value: value.replace(
                "current-source-identity-mismatch",
                "current-source-identity-unchecked",
            ),
        ),
        "Foundation current-source identity removal",
    )
    exercise(
        lambda root: mutate_text(
            root,
            "src/godot_game_test_lab/foundation_media_mcp.py",
            lambda value: value.replace(
                "foundation_build_media_release_report",
                "foundation_release_tool_removed",
            ),
        ),
        "Foundation release MCP removal",
    )
    exercise(
        lambda root: mutate_text(
            root,
            "src/godot_game_test_lab/foundation_media_release_report.py",
            lambda value: value.replace("return not dirty", "return dirty"),
        ),
        "Foundation exact-head cleanliness inversion",
    )
    exercise(
        lambda root: (
            root / "scripts/check_foundation_media_toolchain.py"
        ).unlink(),
        "Foundation media checker removal",
    )
    exercise(
        lambda root: (root / "scripts/check_audio_analysis_toolchain.py").unlink(),
        "Brass audio-analysis checker removal",
    )
    exercise(
        lambda root: (root / "scripts/check_classic_adventure_vga_toolchain.py").unlink(),
        "classic-adventure VGA checker removal",
    )
    exercise(
        lambda root: mutate_text(
            root,
            "docs/CLASSIC_ADVENTURE_VGA_QA.md",
            lambda value: value.replace("alpha: binary", "alpha: soft"),
        ),
        "classic-adventure VGA alpha-authority drift",
    )

    print("Godot lab repository toolchain adversarial tests passed.")
    print(
        "- Python, lockfile, workflow, sandbox, asset-audit, media-plan, "
        "current-source, exact-head CLI/MCP release, Brass audio-analysis, classic VGA and "
        "truth-boundary drift fail closed"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
