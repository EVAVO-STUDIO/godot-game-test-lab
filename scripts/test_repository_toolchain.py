#!/usr/bin/env python3
"""Run the canonical adversarial toolchain suite plus workflow-inventory fixtures."""

from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path
from types import ModuleType

SOURCE_ROOT = Path.cwd().resolve(strict=True)
CORE_PATH = SOURCE_ROOT / "scripts" / "test_repository_toolchain_core.py"
CHECKER_CORE = "scripts/check_repository_toolchain_core.py"


def _load_core() -> ModuleType:
    spec = importlib.util.spec_from_file_location("test_repository_toolchain_core", CORE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load canonical toolchain adversarial-test core")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if CHECKER_CORE not in module.FILES:
        module.FILES.append(CHECKER_CORE)
    return module


def _exercise_wrapper_guards(module: ModuleType) -> None:
    with tempfile.TemporaryDirectory(prefix="evavo-godot-workflow-inventory-") as temporary:
        root = Path(temporary) / "fixture"
        root.mkdir(parents=True)
        module.copy_fixture(root)
        unexpected = root / ".github" / "workflows" / "unexpected-writer.yml"
        unexpected.write_text(
            "name: Unexpected writer\non:\n  issues:\npermissions:\n  contents: write\n",
            encoding="utf-8",
        )
        result = module.run(root)
        if result.returncode == 0:
            raise AssertionError("unexpected workflow inventory must fail closed")

    with tempfile.TemporaryDirectory(prefix="evavo-godot-upgrade-residue-") as temporary:
        root = Path(temporary) / "fixture"
        root.mkdir(parents=True)
        module.copy_fixture(root)
        residue = root / ".evavo" / "bootstrap" / "agent-audio-upgrade-00.b64"
        residue.parent.mkdir(parents=True)
        residue.write_text("cGF5bG9hZA==\n", encoding="utf-8")
        result = module.run(root)
        if result.returncode == 0:
            raise AssertionError("one-time upgrade residue must fail closed")


def main() -> int:
    module = _load_core()
    _exercise_wrapper_guards(module)
    return int(module.main())


if __name__ == "__main__":
    raise SystemExit(main())
