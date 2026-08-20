from __future__ import annotations

import importlib
import os
from collections.abc import Callable, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

_SCENE_SUFFIXES = {".escn", ".scn", ".tscn"}
_SCRIPT_SUFFIXES = {".gd"}
_SCRIPT_CACHE_PARTS = (".godot", "evavo-test-lab")
_INSTALL_MARKER = "__godot_lab_scene_guard__"


def _project_root_from_command(values: Sequence[str], cwd: Path) -> Path:
    path_indexes = [index for index, value in enumerate(values) if value == "--path"]
    if len(path_indexes) > 1:
        raise ValueError("Godot command may contain at most one --path option")
    if path_indexes:
        index = path_indexes[0]
        if index + 1 >= len(values) or not values[index + 1].strip():
            raise ValueError("Godot --path requires a project directory")
        candidate = Path(values[index + 1]).expanduser()
        if not candidate.is_absolute():
            candidate = cwd / candidate
    else:
        candidate = cwd
    root = candidate.resolve(strict=True)
    if not root.is_dir():
        raise ValueError(f"Godot project path is not a directory: {root}")
    project_file = root / "project.godot"
    if not project_file.is_file() or project_file.is_symlink():
        raise ValueError(
            f"Godot project path does not contain a regular project.godot: {root}"
        )
    return root


def validate_scene_argument(scene: str, project_root: Path) -> str:
    value = scene.strip()
    if (
        not value.startswith("res://")
        or "\\" in value
        or "\x00" in value
        or "\n" in value
        or "\r" in value
    ):
        raise ValueError("scene must be a canonical res:// path")
    relative_text = value[6:]
    pure = PurePosixPath(relative_text)
    if (
        not relative_text
        or pure.is_absolute()
        or any(part in {"", ".", ".."} for part in pure.parts)
        or pure.suffix.casefold() not in _SCENE_SUFFIXES
    ):
        raise ValueError("scene must identify a canonical Godot scene resource")
    candidate = project_root.joinpath(*pure.parts)
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(project_root)
    except (FileNotFoundError, OSError, ValueError) as error:
        raise ValueError(
            f"scene does not resolve to a file inside the project: {value}"
        ) from error
    if not resolved.is_file() or resolved.is_symlink():
        raise ValueError(f"scene must resolve to a regular file: {value}")
    return "res://" + pure.as_posix()


def _script_candidate(script: str, project_root: Path) -> Path:
    value = script.strip()
    if not value or any(character in value for character in ("\x00", "\n", "\r")):
        raise ValueError("Godot --script requires a bounded script path")
    if value.startswith("res://"):
        relative_text = value[6:]
        pure = PurePosixPath(relative_text)
        if (
            not relative_text
            or pure.is_absolute()
            or any(part in {"", ".", ".."} for part in pure.parts)
        ):
            raise ValueError("Godot --script res:// path is invalid")
        return project_root.joinpath(*pure.parts)
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = project_root / candidate
    return Path(os.path.abspath(candidate))


def validate_script_argument(script: str, project_root: Path) -> str:
    cache_root = project_root.joinpath(*_SCRIPT_CACHE_PARTS)
    if not cache_root.is_dir() or cache_root.is_symlink():
        raise ValueError("Godot --script requires the governed project probe cache")
    canonical_cache = cache_root.resolve(strict=True)
    if canonical_cache != cache_root:
        raise ValueError("Godot project probe cache may not traverse a symbolic link")

    candidate = _script_candidate(script, project_root)
    try:
        lexical_relative = candidate.relative_to(cache_root)
    except ValueError as error:
        raise ValueError(
            "Godot --script must remain beneath .godot/evavo-test-lab"
        ) from error
    if any(part in {"", ".", ".."} for part in lexical_relative.parts):
        raise ValueError("Godot --script contains an unsafe path segment")

    current = cache_root
    for part in lexical_relative.parts:
        current = current / part
        if current.exists() and current.is_symlink():
            raise ValueError("Godot --script may not traverse a symbolic link")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(canonical_cache)
    except (FileNotFoundError, OSError, ValueError) as error:
        raise ValueError(
            "Godot --script does not resolve inside the governed project probe cache"
        ) from error
    if (
        not resolved.is_file()
        or resolved.is_symlink()
        or resolved.suffix.casefold() not in _SCRIPT_SUFFIXES
    ):
        raise ValueError("Godot --script must resolve to a regular .gd probe file")
    return str(resolved)


def _normalize_script_options(values: list[str], cwd: Path) -> list[str]:
    positions: list[tuple[int, str, bool]] = []
    index = 0
    while index < len(values):
        value = values[index]
        if value == "--script":
            if index + 1 >= len(values):
                raise ValueError("--script requires a governed Godot script path")
            positions.append((index, values[index + 1], False))
            index += 2
            continue
        if value.startswith("--script="):
            positions.append((index, value.split("=", 1)[1], True))
        index += 1
    if not positions:
        return values
    if len(positions) != 1:
        raise ValueError("Godot command may select exactly one --script")
    project_root = _project_root_from_command(values, cwd)
    position, script, joined = positions[0]
    canonical = validate_script_argument(script, project_root)
    normalized = list(values)
    if joined:
        normalized[position] = f"--script={canonical}"
    else:
        normalized[position + 1] = canonical
    return normalized


def normalize_godot_scene_command(command: Sequence[str], cwd: Path) -> list[str]:
    values = [str(part) for part in command]
    if not values:
        raise ValueError("command must contain an executable")
    executable_name = Path(values[0]).name.casefold()
    if not executable_name.startswith("godot"):
        return values

    working_directory = cwd.expanduser().resolve()
    values = _normalize_script_options(values, working_directory)

    scene_values: list[str] = []
    retained: list[str] = []
    index = 0
    while index < len(values):
        value = values[index]
        if value == "--scene":
            if index + 1 >= len(values):
                raise ValueError("--scene requires a res:// scene path")
            scene_values.append(values[index + 1])
            index += 2
            continue
        if value.startswith("--scene="):
            scene_values.append(value.split("=", 1)[1])
            index += 1
            continue
        retained.append(value)
        index += 1

    if not scene_values:
        return values
    if len(scene_values) != 1:
        raise ValueError("Godot command may select exactly one scene")

    project_root = _project_root_from_command(retained, working_directory)
    scene = validate_scene_argument(scene_values[0], project_root)

    user_delimiters = [index for index, value in enumerate(retained) if value == "--"]
    if len(user_delimiters) > 1:
        raise ValueError("Godot command may contain at most one user-argument delimiter")
    insertion_index = user_delimiters[0] if user_delimiters else len(retained)

    before_user_arguments = retained[:insertion_index]
    after_user_arguments = retained[insertion_index:]
    before_user_arguments = [value for value in before_user_arguments if value != scene]
    return [*before_user_arguments, scene, *after_user_arguments]


def install() -> None:
    core = importlib.import_module(f"{__package__}.core")

    current: Callable[..., Any] = core.run_command
    if getattr(current, _INSTALL_MARKER, False):
        return

    def guarded_run_command(command: Sequence[str], cwd: Path, timeout_seconds: int):
        normalized = normalize_godot_scene_command(command, cwd)
        return current(normalized, cwd, timeout_seconds)

    setattr(guarded_run_command, _INSTALL_MARKER, True)
    core.run_command = guarded_run_command


__all__ = [
    "install",
    "normalize_godot_scene_command",
    "validate_scene_argument",
    "validate_script_argument",
]
