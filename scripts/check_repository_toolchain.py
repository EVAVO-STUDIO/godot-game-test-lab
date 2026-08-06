#!/usr/bin/env python3
"""Preflight immutable source boundaries, then run the toolchain core."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

ROOT = Path.cwd().resolve(strict=True)
ASSET_AUDIT_PATH = ROOT / "scripts" / "check_asset_audit_toolchain.py"
FOUNDATION_MEDIA_PATH = ROOT / "scripts" / "check_foundation_media_toolchain.py"
AUDIO_ANALYSIS_PATH = ROOT / "scripts" / "check_audio_analysis_toolchain.py"
CORE_PATH = ROOT / "scripts" / "check_repository_toolchain_core.py"
VISUAL_ADMISSION_PATH = ROOT / "src" / "godot_game_test_lab" / "visual_animation_admission.py"
EXPECTED_WORKFLOWS = {
    "ci.yml",
    "evavo-linux-godot-sandbox.yml",
    "evavo-mainline-confirmation.yml",
    "evavo-native-godot-validation.yml",
    "linux-sandbox-smoke.yml",
    "reusable-godot-linux-sandbox.yml",
    "visual-animation-admission.yml",
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


def _validate_checker(path: Path, label: str, entrypoint: str) -> list[str]:
    errors: list[str] = []
    if path.is_symlink() or not path.is_file():
        return [f"{label} must be a regular file"]
    try:
        if path.resolve(strict=True) != path.absolute():
            errors.append(f"{label} path must be canonical")
        elif path.stat().st_size > 4_000_000:
            errors.append(f"{label} exceeds the bounded source limit")
        else:
            source = path.read_text(encoding="utf-8")
            if source.startswith(chr(0xFEFF)):
                errors.append(f"{label} contains a UTF-8 BOM")
            if entrypoint not in source:
                errors.append(f"{label} does not expose its expected entrypoint")
    except (OSError, UnicodeError) as error:
        errors.append(f"{label} could not be validated: {error}")
    return errors


def _preflight_errors() -> list[str]:
    errors: list[str] = []
    workflow_root = ROOT / ".github" / "workflows"
    try:
        observed = {
            path.name
            for path in workflow_root.iterdir()
            if path.is_file()
            and not path.is_symlink()
            and path.suffix in {".yml", ".yaml"}
        }
    except OSError as error:
        return [f"workflow inventory could not be read: {error}"]
    expected = set(EXPECTED_WORKFLOWS)
    if not VISUAL_ADMISSION_PATH.exists() and not VISUAL_ADMISSION_PATH.is_symlink():
        expected.remove("visual-animation-admission.yml")
    if observed != expected:
        errors.append(
            "workflow inventory changed; "
            f"missing={sorted(expected - observed)} "
            f"extra={sorted(observed - expected)}"
        )

    for relative in FORBIDDEN_STAGING_PATHS:
        path = ROOT.joinpath(*Path(relative).parts)
        if path.exists() or path.is_symlink():
            errors.append(f"one-time publication residue remains: {relative}")

    errors.extend(
        _validate_checker(
            ASSET_AUDIT_PATH,
            "asset-audit checker",
            "def main() -> int:",
        )
    )
    errors.extend(
        _validate_checker(
            FOUNDATION_MEDIA_PATH,
            "Foundation media checker",
            "def main() -> int:",
        )
    )
    errors.extend(
        _validate_checker(
            AUDIO_ANALYSIS_PATH,
            "Brass audio-analysis checker",
            "def main() -> int:",
        )
    )
    errors.extend(
        _validate_checker(
            CORE_PATH,
            "toolchain core",
            "def main() -> int:",
        )
    )
    return errors


def _run_checker(path: Path, label: str) -> int:
    namespace = runpy.run_path(str(path), run_name=f"godot_{label.replace('-', '_')}")
    checker_main = namespace.get("main")
    if not callable(checker_main):
        raise RuntimeError(f"{label} does not expose callable main")
    result = checker_main()
    if not isinstance(result, int):
        raise RuntimeError(f"{label} main must return an integer exit code")
    return result


def main() -> int:
    errors = _preflight_errors()
    if errors:
        print("Godot lab toolchain preflight failed:", file=sys.stderr)
        print(file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    asset_result = _run_checker(ASSET_AUDIT_PATH, "asset-audit-checker")
    if asset_result != 0:
        return asset_result
    foundation_result = _run_checker(FOUNDATION_MEDIA_PATH, "foundation-media-checker")
    if foundation_result != 0:
        return foundation_result
    audio_result = _run_checker(AUDIO_ANALYSIS_PATH, "Brass-audio-analysis-checker")
    if audio_result != 0:
        return audio_result
    return _run_checker(CORE_PATH, "toolchain-core")


if __name__ == "__main__":
    raise SystemExit(main())
