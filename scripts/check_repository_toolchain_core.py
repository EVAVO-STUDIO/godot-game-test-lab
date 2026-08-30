#!/usr/bin/env python3
"""Run the stable repository checker with current CLI, runtime and dependency authority."""

from __future__ import annotations

import copy
import json
import runpy
import sys
import tomllib
from collections.abc import Callable
from importlib import metadata
from pathlib import Path
from typing import Any

ROOT = Path.cwd().resolve(strict=True)
BASE_PATH = ROOT / "scripts" / "_repository_toolchain_core_base.py"
ENGINE_LOCK_PATH = "src/godot_game_test_lab/godot-engine-lock.json"
RELIABILITY_PATH = "evavo.reliability.json"
PYPROJECT_PATH = "pyproject.toml"
CURRENT_GODOT_47 = "4.7.2"
BASE_GODOT_47 = "4.7.1"
CURRENT_MCP_VERSION = "1.29.1"
BASE_MCP_VERSION = "1.28.1"
CURRENT_MCP_REQUIREMENT = f"mcp=={CURRENT_MCP_VERSION}"
BASE_MCP_REQUIREMENT = f"mcp=={BASE_MCP_VERSION}"
CURRENT_MCP_NOTE = (
    f"The optional agent extra pins {CURRENT_MCP_REQUIREMENT}; the core Godot "
    "validation and media runtime remains dependency-free."
)
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
    "godot-lab-web-export-audit": (
        "godot_game_test_lab.web_export_audit:main"
    ),
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
    "godot-lab-movie-evidence": (
        "godot_game_test_lab.movie_evidence_cli:main"
    ),
    "godot-lab-movie-temporal": (
        "godot_game_test_lab.movie_temporal_cli:main"
    ),
    "godot-lab-movie-source-identities": (
        "godot_game_test_lab.movie_source_identity_cli:main"
    ),
}


def _read_regular(path: Path, maximum_bytes: int) -> str:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"toolchain source must be a regular file: {path}")
    if path.resolve(strict=True) != path.absolute():
        raise RuntimeError(f"toolchain source must be canonical: {path}")
    if path.stat().st_size > maximum_bytes:
        raise RuntimeError(f"toolchain source exceeds its bounded size: {path}")
    source = path.read_text(encoding="utf-8")
    if source.startswith("\ufeff"):
        raise RuntimeError(f"toolchain source contains a UTF-8 BOM: {path}")
    return source


def _canonical_json(relative: str) -> dict[str, Any]:
    source = _read_regular(ROOT / relative, 16_000_000)
    value = json.loads(source)
    if not isinstance(value, dict):
        raise RuntimeError(f"toolchain JSON must be an object: {relative}")
    if source != json.dumps(value, indent=2, ensure_ascii=False) + "\n":
        raise RuntimeError(f"toolchain JSON must remain canonical: {relative}")
    return value


def _authority_errors() -> list[str]:
    errors: list[str] = []
    try:
        base_source = _read_regular(BASE_PATH, 4_000_000)
        if "def main() -> int:" not in base_source:
            errors.append("stable repository toolchain base does not expose main")

        pyproject = tomllib.loads(_read_regular(ROOT / PYPROJECT_PATH, 128_000))
        project = pyproject.get("project", {})
        if project.get("scripts") != EXPECTED_SCRIPTS:
            errors.append("Godot Lab command entrypoints changed")
        optional = project.get("optional-dependencies", {})
        if not isinstance(optional, dict) or optional.get("agent") != [
            CURRENT_MCP_REQUIREMENT
        ]:
            errors.append(
                f"agent bridge dependency must be {CURRENT_MCP_REQUIREMENT}"
            )

        engine_lock = _canonical_json(ENGINE_LOCK_PATH)
        channels = engine_lock.get("channels")
        if not isinstance(channels, dict) or channels.get("4.7") != CURRENT_GODOT_47:
            errors.append(
                f"managed Godot 4.7 channel must be {CURRENT_GODOT_47}"
            )

        reliability = _canonical_json(RELIABILITY_PATH)
        package_manager = reliability.get("packageManager")
        agent_dependencies = (
            package_manager.get("agentDependencies")
            if isinstance(package_manager, dict)
            else None
        )
        if agent_dependencies != [CURRENT_MCP_REQUIREMENT]:
            errors.append(
                f"reliability agent dependency must be {CURRENT_MCP_REQUIREMENT}"
            )
        notes = reliability.get("notes")
        if not isinstance(notes, list) or CURRENT_MCP_NOTE not in notes:
            errors.append("reliability MCP dependency note is not current")

        runtime = reliability.get("runtime")
        managed = runtime.get("managedGodotChannels") if isinstance(runtime, dict) else None
        if not isinstance(managed, dict) or managed.get("4.7") != CURRENT_GODOT_47:
            errors.append(
                f"reliability Godot 4.7 channel must be {CURRENT_GODOT_47}"
            )
    except (
        OSError,
        UnicodeError,
        RuntimeError,
        json.JSONDecodeError,
        tomllib.TOMLDecodeError,
    ) as error:
        errors.append(str(error))
    return errors


def _compatible_text_loader(
    original: Callable[[str, int], str],
) -> Callable[[str, int], str]:
    def load(relative: str, maximum_bytes: int = 4_000_000) -> str:
        source = original(relative, maximum_bytes)
        if relative == PYPROJECT_PATH:
            source = source.replace(
                f'"{CURRENT_MCP_REQUIREMENT}"',
                f'"{BASE_MCP_REQUIREMENT}"',
                1,
            )
        return source

    return load


def _compatible_json_loader(
    original: Callable[[str], dict[str, Any]],
) -> Callable[[str], dict[str, Any]]:
    def load(relative: str) -> dict[str, Any]:
        value = copy.deepcopy(original(relative))
        if relative == ENGINE_LOCK_PATH:
            channels = value.get("channels")
            if isinstance(channels, dict) and channels.get("4.7") == CURRENT_GODOT_47:
                channels["4.7"] = BASE_GODOT_47
        elif relative == RELIABILITY_PATH:
            package_manager = value.get("packageManager")
            if isinstance(package_manager, dict):
                dependencies = package_manager.get("agentDependencies")
                if dependencies == [CURRENT_MCP_REQUIREMENT]:
                    package_manager["agentDependencies"] = [BASE_MCP_REQUIREMENT]
            runtime = value.get("runtime")
            managed = runtime.get("managedGodotChannels") if isinstance(runtime, dict) else None
            if isinstance(managed, dict) and managed.get("4.7") == CURRENT_GODOT_47:
                managed["4.7"] = BASE_GODOT_47
        return value

    return load


def _current_agent_installed_validator(
    fail: Callable[[str], None],
) -> Callable[[], None]:
    def validate() -> None:
        try:
            observed = metadata.version("mcp")
        except metadata.PackageNotFoundError:
            fail(
                "agent-installed validation requires "
                f"{CURRENT_MCP_REQUIREMENT}"
            )
            return
        if observed != CURRENT_MCP_VERSION:
            fail(
                f"installed mcp must be {CURRENT_MCP_VERSION}; "
                f"observed {observed}"
            )

    return validate


def main() -> int:
    errors = _authority_errors()
    if errors:
        print("Godot lab current authority check failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    namespace = runpy.run_path(
        str(BASE_PATH),
        run_name="godot_repository_toolchain_core_base",
    )
    base_main = namespace.get("main")
    if not callable(base_main):
        raise RuntimeError("stable repository toolchain base does not expose callable main")
    globals_ = base_main.__globals__
    base_scripts = globals_.get("EXPECTED_SCRIPTS")
    original_text = globals_.get("read_text")
    original_json = globals_.get("canonical_json")
    base_fail = globals_.get("fail")
    if (
        not isinstance(base_scripts, dict)
        or not callable(original_text)
        or not callable(original_json)
        or not callable(base_fail)
    ):
        raise RuntimeError("stable repository toolchain base contract changed")
    base_scripts.clear()
    base_scripts.update(EXPECTED_SCRIPTS)
    globals_["read_text"] = _compatible_text_loader(original_text)
    globals_["canonical_json"] = _compatible_json_loader(original_json)
    globals_["validate_agent_installed_state"] = _current_agent_installed_validator(
        base_fail
    )

    result = base_main()
    if not isinstance(result, int):
        raise RuntimeError("stable repository toolchain base must return an integer")
    if result == 0:
        print(
            f"- all {len(EXPECTED_SCRIPTS)} package entrypoints, MCP "
            f"{CURRENT_MCP_VERSION} and Godot 4.7 channel {CURRENT_GODOT_47} agree"
        )
    return result


if __name__ == "__main__":
    raise SystemExit(main())
