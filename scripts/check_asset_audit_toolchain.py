#!/usr/bin/env python3
"""Run the stable asset checker behind the complete package-command authority."""

from __future__ import annotations

import runpy
import sys
import tomllib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path.cwd().resolve(strict=True)
BASE_PATH = ROOT / "scripts" / "_asset_audit_toolchain_base.py"
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
    "godot-lab-android-journey": (
        "godot_game_test_lab.android_semantic_driver_cli:main"
    ),
    "godot-lab-rally-falcon-preview": (
        "godot_game_test_lab.rally_falcon_preview:main"
    ),
    "godot-lab-localization-plural": (
        "godot_game_test_lab.localization_plural_runtime_cli:main"
    ),
    "godot-lab-localization-stable-id-bundle": (
        "godot_game_test_lab.localization_stable_id_bundle_cli:main"
    ),
    "godot-lab-sprite-animation": (
        "godot_game_test_lab.sprite_animation_runtime_cli:main"
    ),
    "godot-lab-sprite-animation-probe": (
        "godot_game_test_lab.sprite_animation_probe_runner:main"
    ),
}
BASE_ENTRYPOINTS = (
    "godot-lab",
    "godot-lab-native-qa",
    "godot-lab-multiplayer-qa",
    "godot-lab-bot-qa",
    "godot-lab-init-qa",
    "godot-lab-media-qa",
    "godot-lab-mcp",
    "godot-lab-engine",
    "godot-lab-sandbox",
    "godot-lab-rally-falcon-preview",
    "godot-lab-localization-plural",
    "godot-lab-localization-stable-id-bundle",
)


def _read_regular(path: Path, maximum_bytes: int) -> str:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"asset-audit source must be a regular file: {path}")
    if path.resolve(strict=True) != path.absolute():
        raise RuntimeError(f"asset-audit source must be canonical: {path}")
    if path.stat().st_size > maximum_bytes:
        raise RuntimeError(f"asset-audit source exceeds its bounded size: {path}")
    source = path.read_text(encoding="utf-8")
    if source.startswith("\ufeff"):
        raise RuntimeError(f"asset-audit source contains a UTF-8 BOM: {path}")
    return source


def _load_scripts(source: str) -> dict[str, str]:
    value = tomllib.loads(source).get("project", {}).get("scripts")
    if not isinstance(value, dict) or not all(
        isinstance(key, str) and isinstance(target, str)
        for key, target in value.items()
    ):
        raise RuntimeError("pyproject package scripts must be a string map")
    return value


def _compat_tomllib() -> SimpleNamespace:
    def loads(source: str) -> dict[str, Any]:
        value = tomllib.loads(source)
        project = value.get("project")
        if isinstance(project, dict) and project.get("scripts") == EXPECTED_SCRIPTS:
            project["scripts"] = {
                name: EXPECTED_SCRIPTS[name]
                for name in BASE_ENTRYPOINTS
            }
        return value

    return SimpleNamespace(loads=loads, TOMLDecodeError=tomllib.TOMLDecodeError)


def main() -> int:
    try:
        base_source = _read_regular(BASE_PATH, 4_000_000)
        if "def main() -> int:" not in base_source:
            raise RuntimeError("stable asset-audit base does not expose main")
        scripts = _load_scripts(_read_regular(ROOT / "pyproject.toml", 128_000))
        if scripts != EXPECTED_SCRIPTS:
            raise RuntimeError("Godot Lab command entrypoints changed")
    except (OSError, UnicodeError, RuntimeError, tomllib.TOMLDecodeError) as error:
        print(f"Asset-audit current authority check failed: {error}", file=sys.stderr)
        return 1

    namespace = runpy.run_path(
        str(BASE_PATH),
        run_name="godot_asset_audit_toolchain_base",
    )
    base_main = namespace.get("main")
    if not callable(base_main):
        raise RuntimeError("stable asset-audit base does not expose callable main")
    base_main.__globals__["tomllib"] = _compat_tomllib()
    result = base_main()
    if not isinstance(result, int):
        raise RuntimeError("stable asset-audit base must return an integer")
    if result == 0:
        print(f"- complete package authority covers {len(EXPECTED_SCRIPTS)} entrypoints")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
