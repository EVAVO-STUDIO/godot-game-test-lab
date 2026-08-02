#!/usr/bin/env python3
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
                if source.startswith(chr(0xFEFF)):
                    errors.append("toolchain core contains a UTF-8 BOM")
                if "def main() -> int:" not in source:
                    errors.append("toolchain core does not expose its expected entrypoint")
        except (OSError, UnicodeError) as error:
            errors.append(f"toolchain core could not be validated: {error}")
    return errors


def main() -> int:
    errors = _preflight_errors()
    if errors:
        print("Godot lab toolchain preflight failed:", file=sys.stderr)
        print(file=sys.stderr)
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
