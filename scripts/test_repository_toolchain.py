#!/usr/bin/env python3
"""Run stable adversarial fixtures plus current command and engine regressions."""

from __future__ import annotations

import runpy
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

ROOT = Path.cwd().resolve(strict=True)
BASE_PATH = ROOT / "scripts" / "_repository_toolchain_tests_base.py"
CORE_BASE_RELATIVE = "scripts/_repository_toolchain_core_base.py"
CORE_CHECKER_PATH = ROOT / "scripts" / "check_repository_toolchain_core.py"
ENTRYPOINT_DRIFT_CASES = (
    (
        "godot_game_test_lab.sprite_animation_probe_runner:main",
        "godot_game_test_lab.sprite_animation_probe_runner:unsafe_main",
        "sprite animation probe entrypoint drift",
    ),
    (
        "godot_game_test_lab.movie_evidence_cli:main",
        "godot_game_test_lab.movie_evidence_cli:unsafe_main",
        "movie evidence entrypoint drift",
    ),
    (
        "godot_game_test_lab.movie_temporal_cli:main",
        "godot_game_test_lab.movie_temporal_cli:unsafe_main",
        "movie temporal entrypoint drift",
    ),
    (
        "godot_game_test_lab.movie_source_identity_cli:main",
        "godot_game_test_lab.movie_source_identity_cli:unsafe_main",
        "movie source identity entrypoint drift",
    ),
)


def _read_base() -> None:
    if BASE_PATH.is_symlink() or not BASE_PATH.is_file():
        raise RuntimeError("stable repository adversarial test base must be a regular file")
    if BASE_PATH.resolve(strict=True) != BASE_PATH.absolute():
        raise RuntimeError("stable repository adversarial test base must be canonical")
    if BASE_PATH.stat().st_size > 4_000_000:
        raise RuntimeError("stable repository adversarial test base is too large")
    source = BASE_PATH.read_text(encoding="utf-8")
    if source.startswith("\ufeff") or "def main() -> int:" not in source:
        raise RuntimeError("stable repository adversarial test base is invalid")


def _current_command_count() -> int:
    if CORE_CHECKER_PATH.is_symlink() or not CORE_CHECKER_PATH.is_file():
        raise RuntimeError("current repository checker must be a regular file")
    namespace = runpy.run_path(
        str(CORE_CHECKER_PATH),
        run_name="godot_repository_toolchain_current_contract",
    )
    expected_scripts = namespace.get("EXPECTED_SCRIPTS")
    if not isinstance(expected_scripts, dict) or not expected_scripts:
        raise RuntimeError("current repository command contract is invalid")
    return len(expected_scripts)


def main() -> int:
    _read_base()
    namespace = runpy.run_path(
        str(BASE_PATH),
        run_name="godot_repository_toolchain_tests_base",
    )
    base_main = namespace.get("main")
    if not callable(base_main):
        raise RuntimeError("stable repository adversarial test base has no main")
    globals_ = base_main.__globals__
    core_files = globals_.get("CORE_FILES")
    if not isinstance(core_files, tuple):
        raise RuntimeError("stable repository adversarial file inventory changed")
    if CORE_BASE_RELATIVE not in core_files:
        globals_["CORE_FILES"] = (*core_files, CORE_BASE_RELATIVE)

    result = base_main()
    if not isinstance(result, int) or result != 0:
        return int(result) if isinstance(result, int) else 1

    exercise = cast(Callable[[Callable[[Path], None], str], None], globals_["exercise"])
    mutate_text = cast(
        Callable[[Path, str, Callable[[str], str]], None],
        globals_["mutate_text"],
    )
    mutate_json = cast(
        Callable[[Path, str, Callable[[dict[str, Any]], None]], None],
        globals_["mutate_json"],
    )

    for current, drifted, label in ENTRYPOINT_DRIFT_CASES:
        exercise(
            lambda root, old=current, new=drifted: mutate_text(
                root,
                "pyproject.toml",
                lambda value: value.replace(old, new),
            ),
            label,
        )
    exercise(
        lambda root: mutate_json(
            root,
            "src/godot_game_test_lab/godot-engine-lock.json",
            lambda value: value["channels"].update({"4.7": "4.7.1"}),
        ),
        "managed Godot 4.7 channel rollback",
    )
    exercise(
        lambda root: mutate_json(
            root,
            "evavo.reliability.json",
            lambda value: value["runtime"]["managedGodotChannels"].update(
                {"4.7": "4.7.1"}
            ),
        ),
        "reliability Godot 4.7 channel rollback",
    )

    print("Godot lab current authority adversarial tests passed.")
    print(
        f"- all {_current_command_count()} commands and both Godot 4.7 authorities "
        "fail closed on drift"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
