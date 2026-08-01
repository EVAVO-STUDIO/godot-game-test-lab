from __future__ import annotations

import os
from pathlib import Path


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    source = path.read_text(encoding="utf-8")
    if source.count(old) != 1:
        raise SystemExit(f"{label} anchor count changed: {source.count(old)}")
    path.write_text(source.replace(old, new), encoding="utf-8", newline="\n")


def main() -> int:
    stage = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True) / "final-source-tree"
    if stage.is_symlink() or not stage.is_dir():
        raise SystemExit(f"final source staging directory is missing or unsafe: {stage}")

    checker = stage / "scripts/check_repository_toolchain.py"
    replace_once(
        checker,
        '    require_tokens(\n'
        '        "scripts/Install-GodotLab.ps1",\n'
        '        (\n'
        '            "engine bootstrap",\n',
        '    require_tokens(\n'
        '        "scripts/Install-GodotLab.ps1",\n'
        '        (\n'
        '            \'"engine", "bootstrap"\',\n',
        "Windows installer bootstrap token",
    )
    core = stage / "scripts/check_repository_toolchain_core.py"
    core.write_text(checker.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")

    wrapper = '''#!/usr/bin/env python3
"""Preflight the immutable workflow boundary, then run the toolchain core."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

ROOT = Path.cwd().resolve(strict=True)
CORE_PATH = ROOT / "scripts" / "check_repository_toolchain_core.py"
EXPECTED_WORKFLOWS = {
    "ci.yml",
    "evavo-linux-godot-sandbox.yml",
    "evavo-mainline-confirmation.yml",
    "evavo-native-godot-validation.yml",
    "linux-sandbox-smoke.yml",
    "reusable-godot-linux-sandbox.yml",
}
FORBIDDEN_STAGING_PATHS = (
    ".evavo/bootstrap",
    ".evavo/agent-audio-upgrade-diagnostic.txt",
    ".evavo/managed-sandbox-0.7-diagnostic.txt",
    ".github/workflows/apply-agent-audio-upgrade.yml",
    ".github/workflows/apply-managed-sandbox-0.7.yml",
    ".github/workflows/dispatch-agent-audio-upgrade.yml",
    "scripts/apply_agent_audio_upgrade.py",
)


def _preflight_errors() -> list[str]:
    errors: list[str] = []
    workflow_root = ROOT / ".github" / "workflows"
    try:
        observed = {
            path.name
            for path in workflow_root.iterdir()
            if path.is_file() and not path.is_symlink() and path.suffix in {".yml", ".yaml"}
        }
    except OSError as error:
        return [f"workflow inventory could not be read: {error}"]
    if observed != EXPECTED_WORKFLOWS:
        errors.append(
            "workflow inventory changed; "
            f"missing={sorted(EXPECTED_WORKFLOWS - observed)} "
            f"extra={sorted(observed - EXPECTED_WORKFLOWS)}"
        )

    for relative in FORBIDDEN_STAGING_PATHS:
        path = ROOT.joinpath(*Path(relative).parts)
        if path.exists() or path.is_symlink():
            errors.append(f"one-time publication residue remains: {relative}")

    if CORE_PATH.is_symlink() or not CORE_PATH.is_file():
        errors.append("toolchain core must be a regular file")
    else:
        try:
            if CORE_PATH.resolve(strict=True) != CORE_PATH.absolute():
                errors.append("toolchain core path must be canonical")
            elif CORE_PATH.stat().st_size > 4_000_000:
                errors.append("toolchain core exceeds the bounded source limit")
            else:
                source = CORE_PATH.read_text(encoding="utf-8")
                if source.startswith("\ufeff"):
                    errors.append("toolchain core contains a UTF-8 BOM")
                if "def main() -> int:" not in source:
                    errors.append("toolchain core does not expose its expected entrypoint")
        except (OSError, UnicodeError) as error:
            errors.append(f"toolchain core could not be validated: {error}")
    return errors


def main() -> int:
    errors = _preflight_errors()
    if errors:
        print("Godot lab toolchain preflight failed:\n", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    namespace = runpy.run_path(str(CORE_PATH), run_name="godot_toolchain_core")
    core_main = namespace.get("main")
    if not callable(core_main):
        raise RuntimeError("toolchain core does not expose callable main")
    result = core_main()
    if not isinstance(result, int):
        raise RuntimeError("toolchain core main must return an integer exit code")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
'''
    checker.write_text(wrapper, encoding="utf-8", newline="\n")

    replace_once(
        stage / "scripts/test_repository_toolchain.py",
        '    "schemas/repository-owned-reliability-profile.schema.json",\n'
        '    "scripts/check_repository_toolchain.py",\n'
        '    "src/godot_game_test_lab/__init__.py",\n',
        '    "schemas/repository-owned-reliability-profile.schema.json",\n'
        '    "scripts/check_repository_toolchain.py",\n'
        '    "scripts/check_repository_toolchain_core.py",\n'
        '    "src/godot_game_test_lab/__init__.py",\n',
        "adversarial fixture core inventory",
    )

    stale_core_test = stage / "scripts/test_repository_toolchain_core.py"
    if stale_core_test.exists() or stale_core_test.is_symlink():
        stale_core_test.unlink()

    linux_test = stage / "tests/test_linux_sandbox_contract.py"
    source = linux_test.read_text(encoding="utf-8")
    source = source.replace("from pathlib import Path\n", "import json\nfrom pathlib import Path\n", 1)
    source = source.replace(
        '    assert "GODOT_VERSION=4.6.2" in dockerfile\n',
        '    assert "ARG GODOT_VERSION=4.6.3" in dockerfile\n'
        '    engine_lock = json.loads(_read("src/godot_game_test_lab/godot-engine-lock.json"))\n'
        '    assert engine_lock["minimumVersion"] == "4.6.2"\n'
        '    assert engine_lock["defaultVersion"] == "4.6.3"\n',
        1,
    )
    source = source.replace(
        '    assert "sha512sum --check" in dockerfile\n',
        '    assert "digest = hashlib.sha512()" in dockerfile\n'
        '    assert "SHA-512 mismatch" in dockerfile\n',
        1,
    )
    linux_test.write_text(source, encoding="utf-8", newline="\n")

    replace_once(
        stage / "tests/test_native_workflow_policy.py",
        "pip install --disable-pip-version-check -e '.[dev]'",
        "pip install --disable-pip-version-check -e '.[dev,agent]'",
        "native workflow dependency assertion",
    )

    temporary = stage / ".evavo/apply_final_release_fixes.py"
    if temporary.exists() or temporary.is_symlink():
        temporary.unlink()
    print("applied final 0.7 release integration fixes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
